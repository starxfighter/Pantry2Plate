"""Unit tests for backend/agents/scorer_agent.py.

Tests the _extract_text helper and ScorerAgent.run() with _log_to_langsmith
patched so no MCP/LLM calls occur.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.agents.scorer_agent import ScorerAgent, _extract_text
from backend.graph import AgentState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_recipe(name: str, url: str, ingredients: list[str]) -> dict:
    return {
        "name": name,
        "url": url,
        "source": "Test",
        "ingredient_list": ingredients,
        "steps_summary": "",
        "cook_time_minutes": None,
        "cuisine": None,
        "dietary_tags": [],
    }


@pytest.fixture
def state() -> AgentState:
    return AgentState(
        session_id="test-session",
        raw_input="chicken garlic lemon",
        filters={},
        parsed_ingredients=["chicken", "garlic", "lemon"],
        parse_error=None,
        search_results=[],
        search_error=None,
        tavily_recipe_count=3,
        spoonacular_recipe_count=2,
        scored_recipes=[],
        langsmith_run_url=None,
        current_step="scoring",
        start_time=0.0,
    )


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_plain_string(self) -> None:
        assert _extract_text("hello") == "hello"

    def test_text_content_dict(self) -> None:
        assert _extract_text([{"type": "text", "text": "token-abc"}]) == "token-abc"

    def test_empty_list(self) -> None:
        assert _extract_text([]) == ""

    def test_non_text_type_dict(self) -> None:
        # List with a dict that is not a TextContent
        result = _extract_text([{"other": "value"}])
        assert isinstance(result, str)

    def test_none_returns_empty(self) -> None:
        assert _extract_text(None) == ""  # type: ignore[arg-type]

    def test_list_with_plain_string(self) -> None:
        result = _extract_text(["some-string"])
        assert result == "some-string"


# ---------------------------------------------------------------------------
# ScorerAgent.run()
# ---------------------------------------------------------------------------


class TestScorerAgentRun:
    async def test_scores_and_sorts_recipes(self, state: AgentState) -> None:
        """Recipes should be sorted descending by match_score."""
        state["search_results"] = [
            _make_recipe("Low Match", "https://a.com/1", ["tuna", "seaweed"]),
            _make_recipe("High Match", "https://a.com/2", ["chicken", "garlic"]),
        ]

        agent = ScorerAgent()
        with patch.object(agent, "_log_to_langsmith", AsyncMock(return_value=None)):
            result = await agent.run(state)

        recipes = result["scored_recipes"]
        assert len(recipes) == 2
        assert recipes[0]["name"] == "High Match"
        assert recipes[0]["match_score"] > recipes[1]["match_score"]

    async def test_slices_to_top_n(self, state: AgentState, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only TOP_RECIPE_COUNT recipes returned."""
        monkeypatch.setenv("TOP_RECIPE_COUNT", "2")
        state["search_results"] = [
            _make_recipe(f"Recipe {i}", f"https://a.com/{i}", ["chicken"])
            for i in range(5)
        ]

        agent = ScorerAgent()
        with patch.object(agent, "_log_to_langsmith", AsyncMock(return_value=None)):
            result = await agent.run(state)

        assert len(result["scored_recipes"]) == 2

    async def test_empty_search_results(self, state: AgentState) -> None:
        """Empty search_results → empty scored_recipes, current_step=done."""
        state["search_results"] = []

        agent = ScorerAgent()
        with patch.object(agent, "_log_to_langsmith", AsyncMock(return_value=None)):
            result = await agent.run(state)

        assert result["scored_recipes"] == []
        assert result["current_step"] == "done"

    async def test_sets_current_step_done(self, state: AgentState) -> None:
        state["search_results"] = [
            _make_recipe("Chicken Stew", "https://a.com/1", ["chicken", "garlic"])
        ]

        agent = ScorerAgent()
        with patch.object(agent, "_log_to_langsmith", AsyncMock(return_value=None)):
            result = await agent.run(state)

        assert result["current_step"] == "done"

    async def test_scored_recipe_has_required_keys(self, state: AgentState) -> None:
        state["search_results"] = [
            _make_recipe("Lemon Chicken", "https://a.com/1", ["chicken", "lemon"])
        ]

        agent = ScorerAgent()
        with patch.object(agent, "_log_to_langsmith", AsyncMock(return_value=None)):
            result = await agent.run(state)

        recipe = result["scored_recipes"][0]
        required_keys = {
            "name", "url", "source", "ingredient_list", "steps_summary",
            "cook_time_minutes", "cuisine", "dietary_tags",
            "match_score", "ingredients_have", "ingredients_missing", "ingredients_staple",
        }
        assert required_keys.issubset(recipe.keys())

    async def test_staple_ingredients_in_staple_field(self, state: AgentState) -> None:
        """Staples absent from pantry go to ingredients_staple, not missing."""
        state["parsed_ingredients"] = ["chicken"]
        state["search_results"] = [
            _make_recipe("Chicken with Salt", "https://a.com/1", ["chicken", "salt"])
        ]

        agent = ScorerAgent()
        with patch.object(agent, "_log_to_langsmith", AsyncMock(return_value=None)):
            result = await agent.run(state)

        recipe = result["scored_recipes"][0]
        assert "salt" in recipe["ingredients_staple"]
        assert "salt" not in recipe["ingredients_missing"]

    async def test_langsmith_error_does_not_crash(self, state: AgentState) -> None:
        """MCP failure inside _log_to_langsmith must not crash run()."""
        state["search_results"] = [
            _make_recipe("Garlic Pasta", "https://a.com/1", ["garlic", "pasta"])
        ]

        agent = ScorerAgent()
        # Patch MultiServerMCPClient so the MCP session raises.
        # _log_to_langsmith wraps its body in try/except, so this should be swallowed.
        with patch(
            "backend.agents.scorer_agent.MultiServerMCPClient",
            side_effect=RuntimeError("LangSmith down"),
        ):
            result = await agent.run(state)

        assert len(result["scored_recipes"]) == 1
        assert result["langsmith_run_url"] is None
