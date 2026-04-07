"""Scorer Agent — ranks recipes by pantry match and logs the run to LangSmith.

For each recipe in ``state["search_results"]``, scores how many of its
ingredients the user has, sorts by score descending, slices to the configured
top-N, and writes the result to ``state["scored_recipes"]``.

After scoring, logs the completed pipeline run to LangSmith via MCP tools and
stores the public trace URL in state for the frontend to surface as a
"View trace" link.

LangSmith logging is best-effort: a failure here never blocks the scored
recipes from being returned.

MCP tools used:
    langsmith://log_search_run  — record inputs, outputs, latency; returns share token.
    langsmith://get_run_url     — construct public trace URL from share token.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from backend.agents.base import BaseAgent
from backend.graph import AgentState, ScoredRecipe
from backend.tools.ingredient_matcher import score_ingredient_match

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MCP_SERVERS_DIR = Path(__file__).resolve().parents[1] / "mcp_servers"
_DEFAULT_TOP_RECIPE_COUNT = 10

_MCP_CONFIG: dict = {
    "langsmith": {
        "command": sys.executable,
        "args": [str(_MCP_SERVERS_DIR / "langsmith_server.py")],
        "transport": "stdio",
    }
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_text(value: object) -> str:
    """Extract a plain string from a tool invocation result.

    ``langchain-mcp-adapters`` may return either a plain ``str`` or a list of
    MCP ``TextContent`` dicts (``[{"type": "text", "text": "..."}]``) for
    tools declared to return ``str``.  This helper normalises both forms.

    Args:
        value: Raw return value from ``tool.ainvoke()``.

    Returns:
        The text string, or ``""`` if the value cannot be extracted.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return first.get("text", "") or ""
        return str(first)
    return ""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ScorerAgent(BaseAgent):
    """Scores and ranks recipes against the user's available ingredients.

    Scoring is fully deterministic Python (``temperature=0.0`` is used only
    if the LLM is ever invoked for dietary-tag inference in a future
    extension; the current implementation does not call the LLM).

    Attributes:
        None beyond those inherited from ``BaseAgent``.
    """

    def __init__(self) -> None:
        super().__init__(temperature=0.0)

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Return the agent identifier.

        Returns:
            ``"scorer_agent"``
        """
        return "scorer_agent"

    async def run(self, state: AgentState) -> AgentState:
        """Score recipes, sort, slice, log to LangSmith, and update state.

        Steps:

        1. Emit a start log and record the pipeline start time for latency.
        2. For each recipe in ``state["search_results"]``, call
           ``score_ingredient_match`` and build a ``ScoredRecipe`` dict.
        3. Sort descending by ``match_score``; slice to ``TOP_RECIPE_COUNT``.
        4. Write ``state["scored_recipes"]``.
        5. Log the run to LangSmith (best-effort; errors are caught and logged
           but do not affect ``scored_recipes``).
        6. Set ``state["current_step"] = "done"`` and emit an end log.

        Args:
            state: Shared pipeline state.  Reads ``search_results``,
                ``parsed_ingredients``, ``raw_input``, ``session_id``, and
                ``start_time``; writes ``scored_recipes``,
                ``langsmith_run_url``, and ``current_step``.

        Returns:
            Updated ``AgentState``.
        """
        start = self._now_ms()
        self._log_start(state)

        try:
            top_n = int(os.getenv("TOP_RECIPE_COUNT", str(_DEFAULT_TOP_RECIPE_COUNT)))
            pantry: list[str] = state.get("parsed_ingredients") or []
            search_results: list[dict] = state.get("search_results") or []

            # --- Score every candidate recipe ---
            scored: list[ScoredRecipe] = []
            for recipe in search_results:
                ingredient_list: list[str] = recipe.get("ingredient_list") or []
                match = score_ingredient_match(pantry, ingredient_list)

                scored_recipe: ScoredRecipe = {
                    "name": recipe.get("name", ""),
                    "url": recipe.get("url", ""),
                    "source": recipe.get("source", ""),
                    "ingredient_list": ingredient_list,
                    "steps_summary": recipe.get("steps_summary", ""),
                    "cook_time_minutes": recipe.get("cook_time_minutes"),
                    "cuisine": recipe.get("cuisine"),
                    "dietary_tags": recipe.get("dietary_tags") or [],
                    "match_score": match["score"],
                    "ingredients_have": match["have"],
                    "ingredients_missing": match["missing"],
                    "ingredients_staple": match["staples"],
                }
                scored.append(scored_recipe)

            # --- Sort descending, slice to top-N ---
            scored.sort(key=lambda r: r["match_score"], reverse=True)
            top_scored = scored[:top_n]

            state["scored_recipes"] = top_scored  # type: ignore[assignment]
            state["current_step"] = "done"

        except Exception as exc:
            # Scoring failure: preserve whatever partial state exists.
            state["scored_recipes"] = state.get("scored_recipes") or []
            state["current_step"] = "error"
            import json as _json
            import logging as _logging
            _logging.getLogger(__name__).error(
                _json.dumps(
                    {
                        "event": "scorer_error",
                        "agent": self.name,
                        "session_id": state.get("session_id"),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            )

        finally:
            # --- LangSmith logging (best-effort) ---
            await self._log_to_langsmith(state, start)
            self._log_end(state, self._now_ms() - start)

        return state

    # ------------------------------------------------------------------
    # LangSmith helper
    # ------------------------------------------------------------------

    async def _log_to_langsmith(
        self,
        state: AgentState,
        agent_start_ms: float,
    ) -> None:
        """Record the completed pipeline run in LangSmith.

        Calculates latency from ``state["start_time"]`` (set at graph entry)
        when available; falls back to the scorer agent's own start time.

        All exceptions are silently caught — LangSmith logging must never
        block the response.

        Args:
            state: Current pipeline state; read-only in this method.
            agent_start_ms: Scorer agent's own start timestamp in milliseconds,
                used as a latency fallback.
        """
        try:
            graph_start: float = state.get("start_time") or (agent_start_ms / 1000)
            latency_ms = self._now_ms() - (graph_start * 1000)

            scored: list[dict] = state.get("scored_recipes") or []
            top_score: float = scored[0]["match_score"] if scored else 0.0

            inputs = {
                "raw_input": state.get("raw_input", ""),
                "parsed_ingredients": state.get("parsed_ingredients") or [],
                "tavily_candidates": state.get("tavily_recipe_count", 0),
                "spoonacular_candidates": state.get("spoonacular_recipe_count", 0),
            }
            outputs = {
                "recipe_count": len(scored),
                "top_score": top_score,
                "tavily_recipes": state.get("tavily_recipe_count", 0),
                "spoonacular_recipes": state.get("spoonacular_recipe_count", 0),
            }

            # Yield to the event loop before opening a new subprocess session.
            # Prevents Windows ProactorEventLoop IOCP hangs after prior sessions close.
            await asyncio.sleep(0)
            mcp_client = MultiServerMCPClient(_MCP_CONFIG)
            async with mcp_client.session("langsmith") as session:
                tools = {t.name: t for t in await load_mcp_tools(session)}

                log_tool = tools.get("log_search_run")
                url_tool = tools.get("get_run_url")

                if log_tool:
                    token_raw = await log_tool.ainvoke(
                        {
                            "session_id": state.get("session_id", ""),
                            "inputs": inputs,
                            "outputs": outputs,
                            "latency_ms": round(latency_ms, 2),
                            "tags": state.get("run_tags") or [],
                        }
                    )
                    # langchain-mcp-adapters may return str or list[dict]
                    # (MCP TextContent objects) for string-typed tools.
                    # log_search_run now returns the share token directly.
                    share_token: str = _extract_text(token_raw)
                    if url_tool and share_token:
                        url_raw = await url_tool.ainvoke({"share_token": share_token})
                        url: str = _extract_text(url_raw)
                        state["langsmith_run_url"] = url or None

        except Exception:
            # LangSmith errors are intentionally swallowed.
            state["langsmith_run_url"] = None
