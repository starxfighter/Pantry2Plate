"""Integration tests for the full LangGraph pipeline.

These tests invoke the compiled graph end-to-end against real LLM, MCP, and
external API calls (Anthropic, Tavily, Spoonacular, LangSmith).  They are
marked ``@pytest.mark.integration`` and ``@pytest.mark.slow``.

Skip condition:
    ``ANTHROPIC_API_KEY`` not present in the environment.

Run with:
    pytest tests/integration/test_graph.py -v -m "integration and slow"
"""

from __future__ import annotations

import os
import time
import uuid

import pytest

from backend.graph import CONFIG_TEMPLATE, AgentState, graph


# ---------------------------------------------------------------------------
# Skip guard
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _require_anthropic_key() -> None:
    """Skip every test in this module when ANTHROPIC_API_KEY is not configured."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set — skipping live graph integration tests")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED_SCORED_RECIPE_FIELDS: frozenset[str] = frozenset(
    {"name", "url", "match_score", "ingredients_have", "ingredients_missing"}
)


def _make_state(raw_input: str, filters: dict | None = None) -> AgentState:
    """Build a minimal AgentState for a graph invocation."""
    return AgentState(
        session_id=str(uuid.uuid4()),
        raw_input=raw_input,
        filters=filters or {},
        parsed_ingredients=[],
        parse_error=None,
        search_results=[],
        search_error=None,
        tavily_recipe_count=0,
        spoonacular_recipe_count=0,
        scored_recipes=[],
        langsmith_run_url=None,
        current_step="",
        start_time=time.time(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
class TestGraphFullFlow:
    async def test_full_flow_basic(self) -> None:
        """Full pipeline with a simple ingredient list returns scored recipes."""
        state = _make_state("eggs, cheddar cheese, pasta")
        config = {**CONFIG_TEMPLATE, "configurable": {"thread_id": state["session_id"]}}

        result = await graph.ainvoke(state, config=config)

        assert result["parse_error"] is None
        assert len(result["parsed_ingredients"]) >= 2
        assert len(result["scored_recipes"]) >= 1

        for recipe in result["scored_recipes"]:
            assert _REQUIRED_SCORED_RECIPE_FIELDS.issubset(recipe.keys())
            assert isinstance(recipe["name"], str) and recipe["name"]
            assert isinstance(recipe["url"], str)
            assert isinstance(recipe["match_score"], float)
            assert isinstance(recipe["ingredients_have"], list)
            assert isinstance(recipe["ingredients_missing"], list)

    async def test_full_flow_with_filters(self) -> None:
        """Pipeline with a cuisine filter completes without error."""
        state = _make_state(
            "eggs, cheddar cheese, pasta",
            filters={"cuisine": "Italian"},
        )
        config = {**CONFIG_TEMPLATE, "configurable": {"thread_id": state["session_id"]}}

        result = await graph.ainvoke(state, config=config)

        assert result["parse_error"] is None
        assert result["current_step"] in {"done", "empty"}
        assert isinstance(result["scored_recipes"], list)
