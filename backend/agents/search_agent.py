"""Search Agent — finds recipes matching the user's parsed ingredient list.

Queries Tavily (web search) and Spoonacular (recipe API) concurrently via MCP
tools, merges the results, deduplicates by URL and name similarity, applies
any user-supplied filters, and writes a capped list of RecipeCandidate dicts
to ``state["search_results"]``.

A partial failure (one source errors, one succeeds) is treated as success —
results from the working source are used.  Only when *both* sources fail is
``state["search_error"]`` set.

MCP tools used:
    tavily://web_search_recipes       — web search for recipe pages.
    tavily://fetch_recipe_page        — extract content from a recipe URL.
    spoonacular://search_recipes_by_ingredients — ingredient-based recipe lookup.
    spoonacular://get_recipe_detail   — full recipe metadata by ID.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from rapidfuzz import fuzz

from backend.agents.base import BaseAgent
from backend.graph import AgentState

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_MCP_SERVERS_DIR = Path(__file__).resolve().parents[1] / "mcp_servers"

_DEFAULT_DEDUP_THRESHOLD = 85
_DEFAULT_MAX_RESULTS = 20
_TOP_INGREDIENTS = 5  # number of ingredients used to build the search query


# ---------------------------------------------------------------------------
# MCP client configuration
# ---------------------------------------------------------------------------

_MCP_CONFIG: dict = {
    "tavily": {
        "command": sys.executable,
        "args": [str(_MCP_SERVERS_DIR / "tavily_server.py")],
        "transport": "stdio",
    },
    "spoonacular": {
        "command": sys.executable,
        "args": [str(_MCP_SERVERS_DIR / "spoonacular_server.py")],
        "transport": "stdio",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_prompt(filename: str) -> str:
    """Read a prompt file from ``backend/prompts/``.

    Args:
        filename: Filename relative to the prompts directory.

    Returns:
        File contents stripped of leading/trailing whitespace.
    """
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


def _build_query(ingredients: list[str]) -> str:
    """Build a search query string from the top N ingredients.

    Args:
        ingredients: Normalised ingredient list from the parser agent.

    Returns:
        A space-joined query string using up to ``_TOP_INGREDIENTS`` items,
        with "recipe" appended, e.g. ``"chicken breast garlic lemon recipe"``.
    """
    top = ingredients[:_TOP_INGREDIENTS]
    return " ".join(top) + " recipe"


def _is_duplicate(a: dict, b: dict, threshold: int) -> bool:
    """Return True if two recipe dicts are considered duplicates.

    Duplicates are defined as sharing the same URL, or having a name
    similarity score at or above ``threshold`` (rapidfuzz ratio, 0–100).

    Args:
        a: First recipe dict.
        b: Second recipe dict.
        threshold: Minimum fuzz.ratio score to treat names as duplicates.

    Returns:
        ``True`` if the recipes should be considered the same.
    """
    url_a = (a.get("url") or "").rstrip("/")
    url_b = (b.get("url") or "").rstrip("/")
    if url_a and url_b and url_a == url_b:
        return True
    name_a = a.get("name") or ""
    name_b = b.get("name") or ""
    if name_a and name_b:
        return fuzz.ratio(name_a.lower(), name_b.lower()) >= threshold
    return False


def _deduplicate(recipes: list[dict], threshold: int) -> list[dict]:
    """Remove duplicate recipes from a list, keeping the first occurrence.

    Args:
        recipes: Raw merged list of recipe dicts.
        threshold: Fuzz ratio threshold passed to ``_is_duplicate``.

    Returns:
        Deduplicated list preserving original ordering.
    """
    seen: list[dict] = []
    for candidate in recipes:
        if not any(_is_duplicate(candidate, kept, threshold) for kept in seen):
            seen.append(candidate)
    return seen


def _apply_filters(recipes: list[dict], filters: dict) -> list[dict]:
    """Exclude recipes that do not match the user-supplied filters.

    Recognised filter keys:
        cuisine (str): Case-insensitive match against ``recipe["cuisine"]``.
        dietary (str): Must appear in ``recipe["dietary_tags"]``.
        max_cook_time_minutes (int): ``recipe["cook_time_minutes"]`` must be
            <= this value; recipes with ``null`` cook time are kept.

    Args:
        recipes: List of RecipeCandidate dicts.
        filters: Dict of filter key/value pairs from ``state["filters"]``.

    Returns:
        Filtered list; original list returned unchanged if ``filters`` is empty.
    """
    if not filters:
        return recipes

    result: list[dict] = []
    cuisine_filter: str | None = (filters.get("cuisine") or "").lower() or None
    dietary_filter: str | None = (filters.get("dietary") or "").lower() or None
    max_time: int | None = filters.get("max_cook_time_minutes")

    for r in recipes:
        if cuisine_filter:
            recipe_cuisine = (r.get("cuisine") or "").lower()
            if cuisine_filter not in recipe_cuisine:
                continue
        if dietary_filter:
            tags = [t.lower() for t in (r.get("dietary_tags") or [])]
            if dietary_filter not in tags:
                continue
        if max_time is not None:
            cook_time = r.get("cook_time_minutes")
            if cook_time is not None and cook_time > max_time:
                continue
        result.append(r)

    return result


def _normalise_recipe(raw: Any) -> dict | None:
    """Best-effort normalisation of a raw recipe object to RecipeCandidate shape.

    Accepts dicts that may come from either the LLM JSON response or directly
    from Spoonacular's API shape.  Returns ``None`` if the result is unusable
    (missing both name and URL).

    Args:
        raw: Arbitrary value from a search result list.

    Returns:
        A RecipeCandidate-shaped dict, or ``None`` if the input is unusable.
    """
    if not isinstance(raw, dict):
        return None
    name = raw.get("name") or raw.get("title") or ""
    url = raw.get("url") or raw.get("sourceUrl") or ""
    if not name and not url:
        return None
    return {
        "name": name,
        "url": url,
        "source": raw.get("source") or _source_from_url(url),
        "ingredient_list": raw.get("ingredient_list") or raw.get("ingredients") or [],
        "steps_summary": raw.get("steps_summary") or "",
        "cook_time_minutes": raw.get("cook_time_minutes") or raw.get("readyInMinutes"),
        "cuisine": raw.get("cuisine") or (raw.get("cuisines") or [None])[0],
        "dietary_tags": raw.get("dietary_tags") or raw.get("diets") or [],
    }


def _unwrap_tool_list(raw: object) -> list[dict]:
    """Normalise a tool result to a plain list of dicts.

    ``langchain-mcp-adapters`` wraps each item returned by a tool as an MCP
    TextContent dict: ``{"type": "text", "text": "<json-string>"}``.  This
    helper unwraps those wrappers and parses the inner JSON so callers always
    receive a ``list[dict]`` regardless of how the adapter serialises the result.

    Args:
        raw: Raw value from ``tool.ainvoke()``.

    Returns:
        A flat list of plain Python dicts extracted from the result.
    """
    if not raw:
        return []

    # Normalise to a list first.
    items = raw if isinstance(raw, list) else [raw]

    result: list[dict] = []
    for item in items:
        if isinstance(item, dict):
            text = item.get("text") if item.get("type") == "text" else None
            if text is not None:
                # TextContent — parse the inner JSON string.
                try:
                    obj = json.loads(text)
                    if isinstance(obj, dict):
                        result.append(obj)
                    elif isinstance(obj, list):
                        result.extend(r for r in obj if isinstance(r, dict))
                except (json.JSONDecodeError, TypeError):
                    pass
            else:
                result.append(item)
        elif isinstance(item, str):
            try:
                obj = json.loads(item)
                if isinstance(obj, dict):
                    result.append(obj)
                elif isinstance(obj, list):
                    result.extend(r for r in obj if isinstance(r, dict))
            except (json.JSONDecodeError, TypeError):
                pass

    return result


def _source_from_url(url: str) -> str:
    """Derive a human-readable source name from a URL domain.

    Args:
        url: Fully-qualified recipe URL.

    Returns:
        Capitalised domain label, e.g. ``"Allrecipes"`` from
        ``"https://www.allrecipes.com/..."``, or ``""`` if parsing fails.
    """
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        parts = host.replace("www.", "").split(".")
        return parts[0].capitalize() if parts else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class SearchAgent(BaseAgent):
    """Searches Tavily and Spoonacular for recipes using the parsed ingredients.

    Runs both searches concurrently with ``asyncio.gather``.  Partial failures
    (one source down) are tolerated; both failing sets ``search_error``.
    Results are merged, deduplicated, filtered, and capped before being written
    to state.

    Attributes:
        _system_prompt: Contents of ``backend/prompts/search_system.txt``.
    """

    def __init__(self) -> None:
        super().__init__(temperature=0.2)
        self._system_prompt: str = _load_prompt("search_system.txt")

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Return the agent identifier.

        Returns:
            ``"search_agent"``
        """
        return "search_agent"

    async def run(self, state: AgentState) -> AgentState:
        """Search for recipes and write results to state.

        Args:
            state: Shared pipeline state.  Reads ``parsed_ingredients``,
                ``session_id``, and ``filters``; writes ``search_results``,
                ``search_error``, and ``current_step``.

        Returns:
            Updated ``AgentState``.
        """
        start = self._now_ms()
        self._log_start(state)

        dedup_threshold = int(
            os.getenv("RECIPE_DEDUP_THRESHOLD", str(_DEFAULT_DEDUP_THRESHOLD))
        )
        max_results = int(
            os.getenv("MAX_RECIPE_RESULTS", str(_DEFAULT_MAX_RESULTS))
        )

        try:
            ingredients: list[str] = state.get("parsed_ingredients") or []
            query = _build_query(ingredients)

            # Run sequentially, Tavily first.
            # yield after each session so the ProactorEventLoop can flush orphaned
            # IOCP completion notifications before the next subprocess is started.
            try:
                tavily_result = await self._search_tavily(query)
            except Exception as exc:
                tavily_result = exc  # type: ignore[assignment]
            await asyncio.sleep(0)

            try:
                spoonacular_result = await self._search_spoonacular(ingredients)
            except Exception as exc:
                spoonacular_result = exc  # type: ignore[assignment]
            await asyncio.sleep(0)

            # --- Determine success/failure per source ---
            tavily_error = isinstance(tavily_result, BaseException)
            spoonacular_error = isinstance(spoonacular_result, BaseException)

            if tavily_error and spoonacular_error:
                state["search_error"] = (
                    f"Both sources failed — "
                    f"Tavily: {tavily_result}; "
                    f"Spoonacular: {spoonacular_result}"
                )
                state["search_results"] = []
                return state

            tavily_raw: list[dict] = [] if tavily_error else list(tavily_result)  # type: ignore[arg-type]
            spoonacular_raw: list[dict] = [] if spoonacular_error else list(spoonacular_result)  # type: ignore[arg-type]
            raw_results = tavily_raw + spoonacular_raw

            # --- Normalise, deduplicate, filter, cap ---
            normalised = [r for r in (_normalise_recipe(r) for r in raw_results) if r]
            deduped = _deduplicate(normalised, dedup_threshold)
            filtered = _apply_filters(deduped, state.get("filters") or {})

            # Track per-source counts for observability (LangSmith outputs).
            n_tavily_norm = len([r for r in (_normalise_recipe(r) for r in tavily_raw) if r])
            n_spoon_norm = len([r for r in (_normalise_recipe(r) for r in spoonacular_raw) if r])
            state["tavily_recipe_count"] = n_tavily_norm
            state["spoonacular_recipe_count"] = n_spoon_norm

            _log.info(
                '{"event": "search_results", "session_id": "%s",'
                ' "tavily_raw": %d, "spoonacular_raw": %d,'
                ' "tavily_norm": %d, "spoonacular_norm": %d,'
                ' "after_dedup": %d, "after_filter": %d, "final": %d}',
                state.get("session_id", ""),
                len(tavily_raw), len(spoonacular_raw),
                n_tavily_norm, n_spoon_norm,
                len(deduped), len(filtered), min(len(filtered), max_results),
            )

            state["search_results"] = filtered[:max_results]
            state["search_error"] = None
            state["current_step"] = "scoring"

        except Exception as exc:
            state["search_error"] = f"{type(exc).__name__}: {exc}"
            state["search_results"] = []

        finally:
            self._log_end(state, self._now_ms() - start)

        return state

    # ------------------------------------------------------------------
    # Private search helpers
    # ------------------------------------------------------------------

    async def _search_tavily(self, query: str) -> list[dict]:
        """Search Tavily and parse the LLM-structured response.

        Creates its own ``MultiServerMCPClient`` so it can run concurrently
        with ``_search_spoonacular`` without sharing MCP connections.
        Applies a 90-second timeout across the tool call and LLM structuring.

        Args:
            query: Search query string.

        Returns:
            List of recipe dicts extracted from Tavily results.

        Raises:
            Exception: Any error from the MCP tool call or LLM invocation;
                caught by ``asyncio.gather`` in ``run()``.
        """
        _tavily_config = {
            "tavily": _MCP_CONFIG["tavily"],
        }
        client = MultiServerMCPClient(_tavily_config)
        async with client.session("tavily") as session:
            tools = {t.name: t for t in await load_mcp_tools(session)}

            search_tool = tools.get("web_search_recipes")
            if not search_tool:
                raise RuntimeError("web_search_recipes tool not available")

            tavily_max = int(os.getenv("TAVILY_MAX_RESULTS", "15"))
            raw_tool_output = await search_tool.ainvoke(
                {"query": query, "max_results": tavily_max}
            )
            raw_results: list[dict] = _unwrap_tool_list(raw_tool_output)

        if not raw_results:
            return []

        # Ask the LLM to extract structured recipe data from the search snippets.
        context = json.dumps(raw_results, ensure_ascii=False)
        messages = [
            SystemMessage(content=self._system_prompt),
            HumanMessage(
                content=(
                    f"Extract recipe data from these search results.\n\n"
                    f"Ingredients available: {query}\n\n"
                    f"Search results:\n{context}"
                )
            ),
        ]
        response = await asyncio.wait_for(self.model.ainvoke(messages), timeout=60)
        raw_text: str = (
            response.content if hasattr(response, "content") else str(response)
        )
        return _parse_recipe_json(raw_text)

    async def _search_spoonacular(self, ingredients: list[str]) -> list[dict]:
        """Search Spoonacular by ingredients and fetch full recipe details.

        Creates its own ``MultiServerMCPClient`` so it can run concurrently
        with ``_search_tavily`` without sharing MCP connections.

        Args:
            ingredients: Normalised ingredient list from the parser agent.

        Returns:
            List of recipe dicts assembled from Spoonacular API responses.

        Raises:
            Exception: Any error from the MCP tool calls; caught by
                ``asyncio.gather`` in ``run()``.
        """
        _spoonacular_config = {
            "spoonacular": _MCP_CONFIG["spoonacular"],
        }
        client = MultiServerMCPClient(_spoonacular_config)
        async with client.session("spoonacular") as session:
            tools = {t.name: t for t in await load_mcp_tools(session)}

            search_tool = tools.get("search_recipes_by_ingredients")
            detail_tool = tools.get("get_recipe_detail")
            if not search_tool or not detail_tool:
                raise RuntimeError(
                    "search_recipes_by_ingredients or get_recipe_detail tool not available"
                )

            candidates_raw = await search_tool.ainvoke(
                {"ingredients": ingredients, "number": 10}
            )
            candidates: list[dict] = _unwrap_tool_list(candidates_raw)
            if not candidates:
                return []

            # Fetch details sequentially — concurrent subprocess reads hang on Windows.
            details = []
            for c in candidates:
                if not c.get("id"):
                    continue
                try:
                    detail_raw = await detail_tool.ainvoke({"recipe_id": c["id"]})
                    detail = _unwrap_tool_list(detail_raw)
                    details.append(detail[0] if detail else {})
                except Exception as exc:
                    details.append(exc)

        results: list[dict] = []
        for detail in details:
            if isinstance(detail, BaseException) or not detail:
                continue
            normalised = _normalise_recipe(detail)
            if normalised:
                # Enrich ingredient_list from extendedIngredients if present.
                extended = detail.get("extendedIngredients") or []
                if extended:
                    normalised["ingredient_list"] = [
                        (i.get("name") or "").lower()
                        for i in extended
                        if i.get("name")
                    ]
                results.append(normalised)

        return results


# ---------------------------------------------------------------------------
# JSON parse helper
# ---------------------------------------------------------------------------


def _parse_recipe_json(text: str) -> list[dict]:
    """Parse an LLM response expected to contain a JSON array of recipe dicts.

    Attempts a direct parse, then strips markdown fences and retries once.

    Args:
        text: Raw LLM response string.

    Returns:
        List of recipe dicts, or ``[]`` if parsing fails.
    """
    def _try(s: str) -> list[dict] | None:
        try:
            value = json.loads(s.strip())
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
        except json.JSONDecodeError:
            pass
        return None

    result = _try(text)
    if result is not None:
        return result

    # Strip markdown fences and retry.
    cleaned = text.strip()
    for prefix in ("```json", "```"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]

    return _try(cleaned.strip()) or []
