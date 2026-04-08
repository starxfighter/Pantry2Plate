"""FastAPI gateway for the Pantry-to-Plate pipeline.

Exposes:
    POST /search  — accepts ingredient text, streams ranked recipes via SSE.
    GET  /health  — liveness check; reports MCP server status.

MCP servers are launched at startup via ``MCPServerManager`` and shut down
cleanly when the process exits.  The manager instance is stored on
``app.state.mcp_manager`` so request handlers can inspect it.

Environment variables:
    CORS_ORIGINS: Comma-separated list of allowed origins for CORS.
        Defaults to ``*`` (all origins) when unset.
    APP_HOST:     Host to bind.  Defaults to ``0.0.0.0``.
    APP_PORT:     Port to bind.  Defaults to ``8000``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from backend.graph import AgentState, graph
from backend.mcp_servers.pantry_server import (
    clear_pantry as _db_clear_pantry,
    get_pantry as _db_get_pantry,
)
from backend.utils.log_config import get_logger
from backend.utils.mcp_manager import MCPServerManager

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hard cap on total pipeline execution time per request.  If the graph does
# not complete within this many seconds an SSE error event is emitted and the
# stream closes.  Configurable via SEARCH_TIMEOUT_SECONDS env var.
_SEARCH_TIMEOUT: int = int(os.getenv("SEARCH_TIMEOUT_SECONDS", "120"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = get_logger(__name__)

# Silence uvicorn access log noise; keep error logs.
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# CORS origins
# ---------------------------------------------------------------------------

_raw_origins = os.getenv("CORS_ORIGINS", "").strip()
_CORS_ORIGINS: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else ["*"]
)

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage MCP server subprocess lifecycle for the application.

    Starts all four FastMCP stdio servers before the first request is served
    and shuts them down cleanly when the application exits.

    Args:
        app: The FastAPI application instance.  The ``MCPServerManager``
            is stored on ``app.state.mcp_manager`` for use by route handlers.

    Yields:
        Nothing — control passes to the ASGI framework while servers run.

    Raises:
        RuntimeError: If any MCP server exits during the startup timeout
            (propagated from ``MCPServerManager.start_all``).
    """
    manager = MCPServerManager()
    app.state.mcp_manager = manager

    logger.info('{"event": "mcp_startup_begin"}')
    await manager.start_all()
    logger.info('{"event": "mcp_startup_complete", "running": %s}', manager.is_running)

    try:
        yield
    finally:
        logger.info('{"event": "mcp_shutdown_begin"}')
        await manager.stop_all()
        logger.info('{"event": "mcp_shutdown_complete"}')


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Pantry-to-Plate API",
    version="0.1.0",
    description=(
        "Multi-agent recipe discovery API. "
        "POST ingredient text and receive ranked recipes via SSE."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    """Body for POST /search.

    Attributes:
        raw_input:  Freeform ingredient text from the user, e.g.
            ``"I have eggs, cheddar, leftover chicken and pasta"``.
        filters:    Optional key/value filters forwarded to the graph
            (cuisine, dietary restrictions, max cook time, etc.).
        session_id: Client-supplied session identifier used as the
            LangGraph thread ID for MemorySaver checkpointing.
    """

    raw_input: str = Field(..., max_length=2000)
    filters: dict = {}
    session_id: str = Field(..., min_length=1, max_length=128)


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------


async def _search_generator(request: SearchRequest) -> AsyncGenerator[dict, None]:
    """Yield SSE events for a single search pipeline run.

    Streams one event per graph node as ``graph.astream`` yields each
    state snapshot.  The final event carries the full ``scored_recipes``
    list; all intermediate events carry an empty ``data`` payload so the
    client can update a progress indicator.

    Event shape (both intermediate and final)::

        {"step": "<current_step>", "data": {<scored_recipes>} | {}}

    On any unhandled exception an ``error`` event is emitted and the
    generator returns cleanly.

    Args:
        request: Validated ``SearchRequest`` from the POST body.

    Yields:
        ``dict`` values consumed by ``EventSourceResponse``:
        ``{"event": "<name>", "data": "<json-string>"}``.
    """
    state: AgentState = {
        "session_id": request.session_id,
        "raw_input": request.raw_input,
        "filters": request.filters,
        "parsed_ingredients": [],
        "parse_error": None,
        "search_results": [],
        "search_error": None,
        "tavily_recipe_count": 0,
        "spoonacular_recipe_count": 0,
        "scored_recipes": [],
        "langsmith_run_url": None,
        "run_tags": None,
        "current_step": "start",
        "start_time": time.time(),
    }

    config = {"configurable": {"thread_id": request.session_id}}

    try:
        async with asyncio.timeout(_SEARCH_TIMEOUT):
            async for chunk in graph.astream(state, config=config):
                # Each chunk is {node_name: state_snapshot}.
                node_name = next(iter(chunk.keys()))
                node_state: AgentState = chunk[node_name]
                step: str = node_state.get("current_step", "")
                scored = node_state.get("scored_recipes") or []

                logger.info(
                    '{"event": "sse_chunk", "node": "%s", "step": "%s",'
                    ' "scored": %d, "search_results": %d, "tavily": %d, "spoonacular": %d}',
                    node_name, step, len(scored),
                    len(node_state.get("search_results") or []),
                    node_state.get("tavily_recipe_count", 0),
                    node_state.get("spoonacular_recipe_count", 0),
                )

                payload: dict = {
                    "step": step,
                    "data": {"scored_recipes": scored} if scored else {},
                }
                yield {"event": "message", "data": json.dumps(payload)}

            # After the stream completes, read the final checkpointed state.
            # The checkpoint is the authoritative source for both the LangSmith
            # trace URL and the complete scored_recipes list.
            final = await graph.aget_state(config)
            run_url: str | None = None
            final_recipes: list = []
            if final and final.values:
                run_url = final.values.get("langsmith_run_url")
                final_recipes = final.values.get("scored_recipes") or []

            logger.info(
                '{"event": "done_checkpoint", "session_id": "%s", "recipe_count": %d}',
                request.session_id, len(final_recipes),
            )

            yield {
                "event": "done",
                "data": json.dumps(
                    {"langsmith_run_url": run_url, "scored_recipes": final_recipes}
                ),
            }

    except TimeoutError:
        logger.error(
            '{"event": "search_timeout", "session_id": "%s", "timeout_s": %d}',
            request.session_id,
            _SEARCH_TIMEOUT,
        )
        yield {
            "event": "error",
            "data": json.dumps({"message": f"Request timed out after {_SEARCH_TIMEOUT}s"}),
        }

    except Exception as exc:
        logger.error(
            '{"event": "search_error", "session_id": "%s", "error": "%s"}',
            request.session_id,
            str(exc),
        )
        yield {
            "event": "error",
            "data": json.dumps({"message": str(exc)}),
        }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.post("/search", summary="Stream recipe results via SSE")
async def search(request: SearchRequest) -> EventSourceResponse:
    """Accept ingredient text and stream ranked recipes as SSE events.

    The response is a ``text/event-stream`` where each event carries a JSON
    payload ``{"step": "<stage>", "data": {...}}``.  The final event has
    ``event: done`` and contains the optional LangSmith trace URL.

    Args:
        request: ``SearchRequest`` body with ``raw_input``, ``filters``,
            and ``session_id``.

    Returns:
        An ``EventSourceResponse`` that streams SSE events until the graph
        run completes or an error occurs.
    """
    logger.info(
        '{"event": "search_request", "session_id": "%s"}', request.session_id
    )
    return EventSourceResponse(_search_generator(request))


@app.get("/pantry/{session_id}", summary="Retrieve pantry ingredients for a session")
async def get_pantry_route(session_id: str) -> list[str]:
    """Return the stored ingredient list for a session from the persistent pantry DB.

    Reads from the SQLite pantry store written by the Parser Agent after each
    successful parse.  Data survives server restarts.  Returns an empty list if
    no pantry has been saved for this session.

    Args:
        session_id: The session identifier generated by the frontend.

    Returns:
        List of normalised ingredient strings, or ``[]`` if none found.
    """
    try:
        return _db_get_pantry(session_id)
    except Exception as exc:
        logger.error(
            '{"event": "get_pantry_error", "session_id": "%s", "error": "%s"}',
            session_id,
            str(exc),
        )
        return []


@app.delete("/pantry/{session_id}", summary="Clear pantry ingredients for a session")
async def delete_pantry_route(session_id: str) -> dict:
    """Delete the stored ingredient list for a session from the persistent pantry DB.

    Returns ``{"cleared": true}`` regardless of whether the session existed.

    Args:
        session_id: The session identifier generated by the frontend.

    Returns:
        ``{"cleared": true}`` always.
    """
    try:
        _db_clear_pantry(session_id)
    except Exception as exc:
        logger.error(
            '{"event": "delete_pantry_error", "session_id": "%s", "error": "%s"}',
            session_id,
            str(exc),
        )
    return {"cleared": True}


@app.get("/health", summary="Liveness check")
async def health() -> dict:
    """Return application liveness status and MCP server health.

    Returns:
        A dict with ``status`` (``"ok"`` or ``"degraded"``) and
        ``mcp_servers_running`` (bool).
    """
    manager: MCPServerManager = app.state.mcp_manager
    running = manager.is_running
    return {
        "status": "ok" if running else "degraded",
        "mcp_servers_running": running,
    }
