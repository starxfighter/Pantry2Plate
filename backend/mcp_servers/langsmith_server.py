"""LangSmith observability MCP server for the Pantry-to-Plate pipeline.

Exposes two tools:

* ``log_search_run`` — records a completed pipeline run as a LangSmith trace.
* ``get_run_url`` — constructs a public shareable URL for a given share token.

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
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Resolve .env relative to this file so the subprocess finds it regardless of cwd.
load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

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

    Posts directly to the LangSmith REST API using a synchronous
    ``httpx.Client`` (no background threads, no async complexity).
    After creating the run, immediately calls ``PUT /runs/{id}/share``
    to obtain a share token, which is returned instead of the run ID.
    This avoids a second MCP round-trip in ``get_run_url``.

    Args:
        session_id: Unique identifier for the current user session.
        inputs: Pipeline inputs to record.
        outputs: Pipeline outputs to record.
        latency_ms: Total pipeline wall-clock time in milliseconds.

    Returns:
        The LangSmith share token (UUID string), or an empty string on failure.
    """
    try:
        api_key = os.getenv("LANGSMITH_API_KEY")
        if not api_key:
            raise ValueError("LANGSMITH_API_KEY environment variable is not set")

        endpoint = os.getenv("LANGSMITH_ENDPOINT", _DEFAULT_ENDPOINT).rstrip("/")
        project = os.getenv("LANGSMITH_PROJECT", "pantry-to-plate")
        run_id = str(uuid.uuid4())

        payload = {
            "id": run_id,
            "name": "pantry-search",
            "run_type": "chain",
            "inputs": inputs,
            "outputs": outputs,
            "extra": {"session_id": session_id, "latency_ms": latency_ms},
            "session_name": project,
        }

        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{endpoint}/runs",
                json=payload,
                headers={
                    "x-api-key": api_key,
                    "content-type": "application/json",
                },
            )
            response.raise_for_status()

            # Share the run to get a public share token.
            # POST /runs returns 202 Accepted (async) so the run may not be
            # indexed immediately. Retry the share call up to 3 times with a
            # 2-second pause between attempts to handle eventual consistency.
            share_token: str = ""
            for attempt in range(3):
                if attempt > 0:
                    time.sleep(2)
                share_response = client.put(
                    f"{endpoint}/runs/{run_id}/share",
                    headers={
                        "x-api-key": api_key,
                        "content-type": "application/json",
                    },
                )
                if share_response.status_code == 200:
                    share_token = share_response.json().get("share_token", "")
                    break
                # 404 means not indexed yet — retry; any other error, stop.
                if share_response.status_code != 404:
                    share_response.raise_for_status()

        return share_token
    except Exception as exc:
        _log_error(
            "log_search_run",
            exc,
            session_id=session_id,
            latency_ms=latency_ms,
        )
        return ""


@mcp.tool()
def get_run_url(share_token: str) -> str:
    """Construct a shareable URL for viewing a LangSmith run trace.

    ``log_search_run`` now returns the share token directly (obtained via
    ``PUT /runs/{id}/share``), so this tool only needs to build the URL
    string — no HTTP call required.

    Args:
        share_token: LangSmith share token (UUID) as returned by
            ``log_search_run``.

    Returns:
        A fully-qualified public URL string, or an empty string if the
        token is empty.
    """
    if not share_token:
        return ""
    endpoint = os.getenv("LANGSMITH_ENDPOINT", _DEFAULT_ENDPOINT).rstrip("/")
    if endpoint != _DEFAULT_ENDPOINT:
        return f"{endpoint}/public/{share_token}/r"
    return f"{_PUBLIC_UI_BASE}/{share_token}/r"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
