"""Pantry Store MCP server for the Pantry-to-Plate pipeline.

Provides three tools for managing per-session ingredient lists in memory.
The store is process-scoped: data persists for the lifetime of the server
process and is lost on restart.  This is intentional for the local-only,
single-user use case; a persistent store can replace ``_store`` in a future
iteration without changing the tool interface.

Transport: stdio (launched as a subprocess by ``backend/main.py``).
Mount prefix used by agents: ``pantry://``
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# In-memory store  {session_id: [ingredient, ...]}
# ---------------------------------------------------------------------------

_store: dict[str, list[str]] = {}

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
    _store[session_id] = list(ingredients)
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
    return _store.get(session_id, [])


@mcp.tool()
def clear_pantry(session_id: str) -> bool:
    """Delete the ingredient list for a session.

    Args:
        session_id: Unique identifier for the current user session.

    Returns:
        ``True`` whether or not a pantry existed for the session.
    """
    _store.pop(session_id, None)
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
