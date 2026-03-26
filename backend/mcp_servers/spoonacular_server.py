"""Spoonacular Recipe API MCP server for the Pantry-to-Plate pipeline.

Exposes two tools:

* ``search_recipes_by_ingredients`` — find recipes that use a given list of
  ingredients, ranked by how many of the user's ingredients are used.
* ``get_recipe_detail`` — fetch full metadata for a single recipe by ID.

All HTTP calls use ``httpx`` with a fixed 10-second timeout.  All exceptions
are caught, logged as structured JSON to stderr, and converted to safe return
values so a failed API call never crashes the pipeline.

Transport: stdio (launched as a subprocess by ``backend/main.py``).
Mount prefix used by agents: ``spoonacular://``

Required environment variable:
    SPOONACULAR_API_KEY: Spoonacular API key.
"""

from __future__ import annotations

import json
import logging
import os

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(
    format="%(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_BASE_URL = "https://api.spoonacular.com"
_TIMEOUT = 10  # seconds

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = FastMCP("spoonacular")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _api_key() -> str:
    """Return the Spoonacular API key from the environment.

    Raises:
        ValueError: If ``SPOONACULAR_API_KEY`` is not set.
    """
    key = os.getenv("SPOONACULAR_API_KEY")
    if not key:
        raise ValueError("SPOONACULAR_API_KEY environment variable is not set")
    return key


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
def search_recipes_by_ingredients(
    ingredients: list[str],
    number: int = 10,
) -> list[dict]:
    """Search for recipes that use the supplied ingredients.

    Calls ``GET /recipes/findByIngredients``.  Results are ranked by the
    number of matched ingredients (``ranking=2``) and pantry-staples such as
    salt and water are not filtered out (``ignorePantry=False``) so that
    scoring remains accurate.

    Args:
        ingredients: Normalised ingredient strings to match against,
            e.g. ``["chicken breast", "cheddar cheese", "rice"]``.
        number: Maximum number of recipes to return (1–100).
            Defaults to 10.

    Returns:
        A list of recipe dicts as returned by the Spoonacular API.  Each dict
        includes at minimum ``id``, ``title``, ``image``, ``usedIngredients``,
        and ``missedIngredients``.  Returns an empty list on failure.
    """
    try:
        params = {
            "apiKey": _api_key(),
            "ingredients": ",".join(ingredients),
            "number": number,
            "ranking": 2,
            "ignorePantry": False,
        }
        response = httpx.get(
            f"{_BASE_URL}/recipes/findByIngredients",
            params=params,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        _log_error(
            "search_recipes_by_ingredients",
            exc,
            ingredients=ingredients,
            number=number,
        )
        return []


@mcp.tool()
def get_recipe_detail(recipe_id: int) -> dict:
    """Fetch full metadata for a single recipe.

    Calls ``GET /recipes/{recipe_id}/information``.  Nutrition data is
    excluded to keep response payloads small (``includeNutrition=False``).

    Args:
        recipe_id: Spoonacular numeric recipe identifier.

    Returns:
        A dict containing the following keys (empty dict on failure):

        * ``id`` (int): Spoonacular recipe ID.
        * ``title`` (str): Recipe title.
        * ``sourceUrl`` (str): URL of the original recipe page.
        * ``readyInMinutes`` (int): Total preparation + cook time.
        * ``cuisines`` (list[str]): Cuisine tags, e.g. ``["Italian"]``.
        * ``diets`` (list[str]): Dietary tags, e.g. ``["vegetarian"]``.
        * ``extendedIngredients`` (list[dict]): Full ingredient objects
          including ``name``, ``amount``, and ``unit``.
    """
    try:
        params = {
            "apiKey": _api_key(),
            "includeNutrition": False,
        }
        response = httpx.get(
            f"{_BASE_URL}/recipes/{recipe_id}/information",
            params=params,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return {
            "id": data.get("id"),
            "title": data.get("title", ""),
            "sourceUrl": data.get("sourceUrl", ""),
            "readyInMinutes": data.get("readyInMinutes"),
            "cuisines": data.get("cuisines", []),
            "diets": data.get("diets", []),
            "extendedIngredients": data.get("extendedIngredients", []),
        }
    except Exception as exc:
        _log_error("get_recipe_detail", exc, recipe_id=recipe_id)
        return {}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
