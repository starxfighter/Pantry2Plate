"""Pantry Store MCP server for the Pantry-to-Plate pipeline.

Provides three tools for managing per-session ingredient lists, persisted in a
SQLite database.  Data survives server restarts and is keyed by session_id.

The database file path is controlled by the ``PANTRY_DB_PATH`` environment
variable (default: ``data/pantry.db`` relative to the working directory).
Set ``PANTRY_DB_PATH=:memory:`` in tests to use an in-memory database.

Transport: stdio (launched as a subprocess by ``backend/main.py``).
Mount prefix used by agents: ``pantry://``
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

_DB_PATH: str = os.getenv("PANTRY_DB_PATH", "data/pantry.db")

# Create parent directory if needed (skip for in-memory DB).
if _DB_PATH != ":memory:":
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)

_conn: sqlite3.Connection = sqlite3.connect(_DB_PATH, check_same_thread=False)
_conn.execute(
    """
    CREATE TABLE IF NOT EXISTS pantry (
        session_id TEXT PRIMARY KEY,
        ingredients TEXT NOT NULL
    )
    """
)
_conn.commit()

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = FastMCP("pantry-store")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def save_pantry(session_id: str, ingredients: list[str]) -> bool:
    """Persist an ingredient list for a session, replacing any prior value.

    Args:
        session_id: Unique identifier for the current user session.
        ingredients: Normalised ingredient strings to store
            (e.g. ``["chicken breast", "cheddar cheese"]``).

    Returns:
        ``True`` on success.
    """
    _conn.execute(
        "INSERT OR REPLACE INTO pantry (session_id, ingredients) VALUES (?, ?)",
        (session_id, json.dumps(ingredients)),
    )
    _conn.commit()
    return True


@mcp.tool()
def get_pantry(session_id: str) -> list[str]:
    """Retrieve the ingredient list for a session.

    Args:
        session_id: Unique identifier for the current user session.

    Returns:
        The stored ingredient list, or an empty list if no pantry has been
        saved for this session.
    """
    row = _conn.execute(
        "SELECT ingredients FROM pantry WHERE session_id = ?", (session_id,)
    ).fetchone()
    return json.loads(row[0]) if row else []


@mcp.tool()
def clear_pantry(session_id: str) -> bool:
    """Delete the ingredient list for a session.

    Args:
        session_id: Unique identifier for the current user session.

    Returns:
        ``True`` whether or not a pantry existed for the session.
    """
    _conn.execute("DELETE FROM pantry WHERE session_id = ?", (session_id,))
    _conn.commit()
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
