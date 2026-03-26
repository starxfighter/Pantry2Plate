"""LangSmith observability MCP server for the Pantry-to-Plate pipeline.

Exposes two tools:

* ``log_search_run`` — records a completed pipeline run as a LangSmith trace.
* ``get_run_url`` — constructs a public shareable URL for a given run ID.

All exceptions are caught, logged as structured JSON to stderr, and converted
to safe return values (empty string) so observability failures never block
the pipeline from returning results to the user.

Transport: stdio (launched as a subprocess by ``backend/main.py``).
Mount prefix used by agents: ``langsmith://``

Required environment variables:
    LANGSMITH_API_KEY: LangSmith API key.
    LANGSMITH_PROJECT: Project name to log runs under (e.g. ``pantry-to-plate``).

Optional environment variables:
    LANGSMITH_ENDPOINT: Base URL of a self-hosted LangSmith instance.
        Defaults to ``https://api.smith.langchain.com``.
"""

from __future__ import annotations

import json
import logging
import os
import uuid

from dotenv import load_dotenv
from langsmith import Client
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(
    format="%(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_DEFAULT_ENDPOINT = "https://api.smith.langchain.com"
_PUBLIC_UI_BASE = "https://smith.langchain.com/public"

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = FastMCP("langsmith")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_client() -> Client:
    """Instantiate an authenticated LangSmith Client from the environment.

    Returns:
        A configured ``langsmith.Client`` instance.

    Raises:
        ValueError: If ``LANGSMITH_API_KEY`` is not set.
    """
    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        raise ValueError("LANGSMITH_API_KEY environment variable is not set")
    endpoint = os.getenv("LANGSMITH_ENDPOINT", _DEFAULT_ENDPOINT)
    return Client(api_url=endpoint, api_key=api_key)


def _log_error(tool: str, error: Exception, **context: object) -> None:
    """Emit a structured JSON error record to the logger."""
    logger.error(
        json.dumps(
            {"tool": tool, "error": type(error).__name__, "detail": str(error), **context}
        )
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def log_search_run(
    session_id: str,
    inputs: dict,
    outputs: dict,
    latency_ms: float,
) -> str:
    """Record a completed pipeline search run as a LangSmith trace.

    Creates a run of type ``"chain"`` under the project configured via
    ``LANGSMITH_PROJECT``.  Session ID and latency are attached as extra
    metadata for filtering and analysis in the LangSmith UI.

    Args:
        session_id: Unique identifier for the current user session.
        inputs: Pipeline inputs to record, e.g.
            ``{"raw_input": "chicken rice tomatoes", "filters": {}}``.
        outputs: Pipeline outputs to record, e.g.
            ``{"scored_recipes": [...], "total_results": 8}``.
        latency_ms: Total pipeline wall-clock time in milliseconds.

    Returns:
        The LangSmith run ID as a string (UUID), or an empty string on failure.
    """
    try:
        client = _get_client()
        project = os.getenv("LANGSMITH_PROJECT", "pantry-to-plate")
        run_id = str(uuid.uuid4())
        client.create_run(
            id=run_id,
            name="pantry-search",
            run_type="chain",
            inputs=inputs,
            outputs=outputs,
            extra={"session_id": session_id, "latency_ms": latency_ms},
            project_name=project,
        )
        return run_id
    except Exception as exc:
        _log_error(
            "log_search_run",
            exc,
            session_id=session_id,
            latency_ms=latency_ms,
        )
        return ""


@mcp.tool()
def get_run_url(run_id: str) -> str:
    """Return a shareable URL for viewing a LangSmith run trace.

    Uses the custom ``LANGSMITH_ENDPOINT`` base when set (self-hosted
    instances), otherwise falls back to the public ``smith.langchain.com``
    URL format.

    Args:
        run_id: LangSmith run ID string (UUID) as returned by
            ``log_search_run``.

    Returns:
        A fully-qualified URL string, or an empty string on failure.
    """
    try:
        if not run_id:
            return ""
        endpoint = os.getenv("LANGSMITH_ENDPOINT", "")
        if endpoint and endpoint != _DEFAULT_ENDPOINT:
            base = endpoint.rstrip("/")
            return f"{base}/public/{run_id}/r"
        return f"{_PUBLIC_UI_BASE}/{run_id}/r"
    except Exception as exc:
        _log_error("get_run_url", exc, run_id=run_id)
        return ""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
