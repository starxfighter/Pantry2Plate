"""Tavily Search MCP server for the Pantry-to-Plate pipeline.

Exposes two tools:

* ``web_search_recipes`` — full-text web search via the Tavily search API.
* ``fetch_recipe_page`` — extracts clean text from a recipe URL via Tavily extract.

All exceptions are caught, logged as structured JSON to stderr, and converted
to safe return values so a single failed tool call never crashes the pipeline.

Transport: stdio (launched as a subprocess by ``backend/main.py``).
Mount prefix used by agents: ``tavily://``

Required environment variable:
    TAVILY_API_KEY: Tavily API key.
"""

from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from tavily import TavilyClient

load_dotenv()

logging.basicConfig(
    format="%(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = FastMCP("tavily-search")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_client() -> TavilyClient:
    """Instantiate a TavilyClient from the environment.

    Returns:
        An authenticated ``TavilyClient``.

    Raises:
        ValueError: If ``TAVILY_API_KEY`` is not set.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("TAVILY_API_KEY environment variable is not set")
    return TavilyClient(api_key=api_key)


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
def web_search_recipes(query: str, max_results: int = 10) -> list[dict]:
    """Search the web for recipes matching a query using the Tavily search API.

    Uses ``search_depth="advanced"`` to retrieve richer content snippets
    suitable for recipe extraction without a separate page-fetch call.

    Args:
        query: Natural-language search query, e.g.
            ``"chicken and rice recipes with tomatoes"``.
        max_results: Maximum number of results to return (1–20).
            Defaults to 10.

    Returns:
        A list of result dicts, each containing:

        * ``url`` (str): Source page URL.
        * ``title`` (str): Page title.
        * ``content`` (str): Extracted text snippet from the page.

        Returns an empty list if the search fails or yields no results.
    """
    try:
        client = _get_client()
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",
        )
        results = response.get("results", [])
        return [
            {
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "content": r.get("content", ""),
            }
            for r in results
        ]
    except Exception as exc:
        _log_error("web_search_recipes", exc, query=query, max_results=max_results)
        return []


@mcp.tool()
def fetch_recipe_page(url: str) -> str:
    """Extract clean text content from a recipe page URL via Tavily extract.

    Args:
        url: Fully-qualified URL of the recipe page to extract.

    Returns:
        Extracted plain-text content of the page, or an empty string if
        extraction fails or the response contains no content.
    """
    try:
        client = _get_client()
        response = client.extract(urls=[url])
        results = response.get("results", [])
        if not results:
            return ""
        return results[0].get("raw_content", "")
    except Exception as exc:
        _log_error("fetch_recipe_page", exc, url=url)
        return ""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
