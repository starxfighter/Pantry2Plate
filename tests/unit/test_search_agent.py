"""Unit tests for backend/agents/search_agent.py.

Tests pure helper functions directly, and SearchAgent.run() with
_search_tavily/_search_spoonacular patched so no MCP/LLM calls occur.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.agents.search_agent import (
    SearchAgent,
    _apply_filters,
    _build_query,
    _deduplicate,
    _is_duplicate,
    _normalise_recipe,
    _parse_recipe_json,
    _source_from_url,
    _unwrap_tool_list,
)
from backend.graph import AgentState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state() -> AgentState:
    return AgentState(
        session_id="test-session",
        raw_input="chicken garlic lemon recipe",
        filters={},
        parsed_ingredients=["chicken", "garlic", "lemon"],
        parse_error=None,
        search_results=[],
        search_error=None,
        tavily_recipe_count=0,
        spoonacular_recipe_count=0,
        scored_recipes=[],
        langsmith_run_url=None,
        current_step="searching",
        start_time=0.0,
    )


@pytest.fixture
def sample_recipe() -> dict:
    return {
        "name": "Garlic Chicken",
        "url": "https://example.com/garlic-chicken",
        "source": "Example",
        "ingredient_list": ["chicken", "garlic", "olive oil"],
        "steps_summary": "Season chicken. Cook with garlic.",
        "cook_time_minutes": 30,
        "cuisine": "Italian",
        "dietary_tags": [],
    }


# ---------------------------------------------------------------------------
# _build_query
# ---------------------------------------------------------------------------


class TestBuildQuery:
    def test_basic_query(self) -> None:
        result = _build_query(["chicken", "garlic", "lemon"])
        assert result == "chicken garlic lemon recipe"

    def test_caps_at_five_ingredients(self) -> None:
        ingredients = ["a", "b", "c", "d", "e", "f", "g"]
        result = _build_query(ingredients)
        assert result == "a b c d e recipe"

    def test_empty_list(self) -> None:
        assert _build_query([]) == " recipe"

    def test_single_ingredient(self) -> None:
        assert _build_query(["salmon"]) == "salmon recipe"


# ---------------------------------------------------------------------------
# _is_duplicate
# ---------------------------------------------------------------------------


class TestIsDuplicateRecipe:
    def test_same_url(self) -> None:
        a = {"url": "https://example.com/pasta", "name": "Pasta"}
        b = {"url": "https://example.com/pasta", "name": "Pasta Dish"}
        assert _is_duplicate(a, b, threshold=85) is True

    def test_same_url_trailing_slash(self) -> None:
        a = {"url": "https://example.com/pasta/", "name": "Pasta"}
        b = {"url": "https://example.com/pasta", "name": "Pasta Dish"}
        assert _is_duplicate(a, b, threshold=85) is True

    def test_different_url_different_name(self) -> None:
        a = {"url": "https://example.com/pasta", "name": "Pasta"}
        b = {"url": "https://other.com/soup", "name": "Soup"}
        assert _is_duplicate(a, b, threshold=85) is False

    def test_similar_names_above_threshold(self) -> None:
        a = {"url": "", "name": "Garlic Butter Chicken"}
        b = {"url": "", "name": "Garlic Butter Chicken Recipe"}
        assert _is_duplicate(a, b, threshold=85) is True

    def test_empty_url_and_name(self) -> None:
        a = {"url": "", "name": ""}
        b = {"url": "", "name": ""}
        # Empty names → no match
        assert _is_duplicate(a, b, threshold=85) is False


# ---------------------------------------------------------------------------
# _deduplicate
# ---------------------------------------------------------------------------


class TestDeduplicate:
    def test_removes_url_duplicate(self) -> None:
        url = "https://example.com/chicken"
        recipes = [
            {"url": url, "name": "Chicken A"},
            {"url": url, "name": "Chicken B"},
        ]
        result = _deduplicate(recipes, threshold=85)
        assert len(result) == 1
        assert result[0]["name"] == "Chicken A"

    def test_keeps_unique_recipes(self) -> None:
        recipes = [
            {"url": "https://a.com/1", "name": "Garlic Chicken"},
            {"url": "https://b.com/2", "name": "Beef Stew"},
        ]
        assert len(_deduplicate(recipes, threshold=85)) == 2

    def test_empty_list(self) -> None:
        assert _deduplicate([], threshold=85) == []

    def test_preserves_order(self) -> None:
        recipes = [
            {"url": "https://a.com/1", "name": "First"},
            {"url": "https://b.com/2", "name": "Second"},
            {"url": "https://c.com/3", "name": "Third"},
        ]
        result = _deduplicate(recipes, threshold=85)
        assert [r["name"] for r in result] == ["First", "Second", "Third"]


# ---------------------------------------------------------------------------
# _apply_filters
# ---------------------------------------------------------------------------


class TestApplyFilters:
    def test_no_filters_returns_all(self, sample_recipe: dict) -> None:
        assert _apply_filters([sample_recipe], {}) == [sample_recipe]

    def test_cuisine_filter_match(self, sample_recipe: dict) -> None:
        result = _apply_filters([sample_recipe], {"cuisine": "italian"})
        assert len(result) == 1

    def test_cuisine_filter_no_match(self, sample_recipe: dict) -> None:
        result = _apply_filters([sample_recipe], {"cuisine": "mexican"})
        assert result == []

    def test_dietary_filter_match(self) -> None:
        recipe = {"dietary_tags": ["vegetarian"], "cuisine": None, "cook_time_minutes": None}
        result = _apply_filters([recipe], {"dietary": "vegetarian"})
        assert len(result) == 1

    def test_dietary_filter_no_match(self) -> None:
        recipe = {"dietary_tags": ["vegan"], "cuisine": None, "cook_time_minutes": None}
        result = _apply_filters([recipe], {"dietary": "gluten-free"})
        assert result == []

    def test_max_cook_time_pass(self, sample_recipe: dict) -> None:
        # cook_time_minutes=30, max=60 → include
        result = _apply_filters([sample_recipe], {"max_cook_time_minutes": 60})
        assert len(result) == 1

    def test_max_cook_time_fail(self, sample_recipe: dict) -> None:
        # cook_time_minutes=30, max=20 → exclude
        result = _apply_filters([sample_recipe], {"max_cook_time_minutes": 20})
        assert result == []

    def test_null_cook_time_kept(self) -> None:
        recipe = {"cook_time_minutes": None, "cuisine": None, "dietary_tags": []}
        result = _apply_filters([recipe], {"max_cook_time_minutes": 15})
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _normalise_recipe
# ---------------------------------------------------------------------------


class TestNormaliseRecipe:
    def test_standard_shape(self, sample_recipe: dict) -> None:
        result = _normalise_recipe(sample_recipe)
        assert result is not None
        assert result["name"] == "Garlic Chicken"
        assert result["url"] == "https://example.com/garlic-chicken"

    def test_spoonacular_shape(self) -> None:
        raw = {"title": "Pasta", "sourceUrl": "https://spoon.com/pasta", "readyInMinutes": 25}
        result = _normalise_recipe(raw)
        assert result is not None
        assert result["name"] == "Pasta"
        assert result["cook_time_minutes"] == 25

    def test_no_name_or_url_returns_none(self) -> None:
        assert _normalise_recipe({"ingredient_list": ["egg"]}) is None

    def test_non_dict_returns_none(self) -> None:
        assert _normalise_recipe("not a dict") is None  # type: ignore[arg-type]
        assert _normalise_recipe(None) is None  # type: ignore[arg-type]
        assert _normalise_recipe(42) is None  # type: ignore[arg-type]

    def test_source_derived_from_url(self) -> None:
        raw = {"name": "Pasta", "url": "https://www.allrecipes.com/pasta-recipe"}
        result = _normalise_recipe(raw)
        assert result is not None
        assert result["source"] == "Allrecipes"


# ---------------------------------------------------------------------------
# _unwrap_tool_list
# ---------------------------------------------------------------------------


class TestUnwrapToolList:
    def test_plain_dict_list(self) -> None:
        raw = [{"name": "Pasta", "url": "https://example.com"}]
        result = _unwrap_tool_list(raw)
        assert result == [{"name": "Pasta", "url": "https://example.com"}]

    def test_text_content_wrapping(self) -> None:
        import json
        inner = [{"name": "Soup", "url": "https://soup.com"}]
        raw = [{"type": "text", "text": json.dumps(inner)}]
        result = _unwrap_tool_list(raw)
        assert result == inner

    def test_text_content_single_dict(self) -> None:
        import json
        inner = {"name": "Salad", "url": "https://salad.com"}
        raw = [{"type": "text", "text": json.dumps(inner)}]
        result = _unwrap_tool_list(raw)
        assert result == [inner]

    def test_empty_input(self) -> None:
        assert _unwrap_tool_list([]) == []
        assert _unwrap_tool_list(None) == []  # type: ignore[arg-type]

    def test_json_string_item(self) -> None:
        import json
        inner = {"name": "Stew", "url": "https://stew.com"}
        result = _unwrap_tool_list([json.dumps(inner)])
        assert result == [inner]

    def test_invalid_json_text_skipped(self) -> None:
        raw = [{"type": "text", "text": "not valid json"}]
        result = _unwrap_tool_list(raw)
        assert result == []


# ---------------------------------------------------------------------------
# _source_from_url
# ---------------------------------------------------------------------------


class TestSourceFromUrl:
    def test_allrecipes(self) -> None:
        assert _source_from_url("https://www.allrecipes.com/recipe/123") == "Allrecipes"

    def test_foodnetwork(self) -> None:
        assert _source_from_url("https://www.foodnetwork.com/recipes/abc") == "Foodnetwork"

    def test_empty_url(self) -> None:
        assert _source_from_url("") == ""

    def test_malformed_url(self) -> None:
        result = _source_from_url("not-a-url")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _parse_recipe_json
# ---------------------------------------------------------------------------


class TestParseRecipeJson:
    def test_valid_json_array(self) -> None:
        text = '[{"name": "Pasta", "url": "https://example.com"}]'
        result = _parse_recipe_json(text)
        assert len(result) == 1
        assert result[0]["name"] == "Pasta"

    def test_markdown_fenced(self) -> None:
        text = '```json\n[{"name": "Soup"}]\n```'
        result = _parse_recipe_json(text)
        assert len(result) == 1

    def test_invalid_json_returns_empty(self) -> None:
        assert _parse_recipe_json("sorry, I can't help") == []

    def test_filters_non_dict_elements(self) -> None:
        text = '[{"name": "Pasta"}, "not a dict", 42]'
        result = _parse_recipe_json(text)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# SearchAgent.run()
# ---------------------------------------------------------------------------


class TestSearchAgentRun:
    async def test_successful_search_populates_results(
        self, state: AgentState
    ) -> None:
        agent = SearchAgent()
        fake_recipes = [
            {
                "name": "Garlic Chicken",
                "url": "https://example.com/1",
                "source": "Example",
                "ingredient_list": ["chicken", "garlic"],
                "steps_summary": "",
                "cook_time_minutes": 30,
                "cuisine": "Italian",
                "dietary_tags": [],
            }
        ]

        with patch.object(agent, "_search_tavily", AsyncMock(return_value=fake_recipes)):
            with patch.object(agent, "_search_spoonacular", AsyncMock(return_value=[])):
                result = await agent.run(state)

        assert len(result["search_results"]) == 1
        assert result["search_results"][0]["name"] == "Garlic Chicken"
        assert result["search_error"] is None
        assert result["current_step"] == "scoring"

    async def test_both_sources_fail_sets_search_error(
        self, state: AgentState
    ) -> None:
        agent = SearchAgent()

        with patch.object(agent, "_search_tavily", AsyncMock(side_effect=RuntimeError("Tavily down"))):
            with patch.object(agent, "_search_spoonacular", AsyncMock(side_effect=RuntimeError("Spoon down"))):
                result = await agent.run(state)

        assert result["search_results"] == []
        assert result["search_error"] is not None
        assert "Both sources failed" in result["search_error"]

    async def test_one_source_fails_uses_other(
        self, state: AgentState
    ) -> None:
        agent = SearchAgent()
        spoon_recipes = [
            {
                "name": "Lemon Chicken",
                "url": "https://spoon.com/1",
                "source": "Spoonacular",
                "ingredient_list": ["chicken", "lemon"],
                "steps_summary": "",
                "cook_time_minutes": 25,
                "cuisine": None,
                "dietary_tags": [],
            }
        ]

        with patch.object(agent, "_search_tavily", AsyncMock(side_effect=RuntimeError("Tavily down"))):
            with patch.object(agent, "_search_spoonacular", AsyncMock(return_value=spoon_recipes)):
                result = await agent.run(state)

        assert len(result["search_results"]) == 1
        assert result["search_error"] is None

    async def test_deduplication_applied(self, state: AgentState) -> None:
        agent = SearchAgent()
        url = "https://example.com/garlic-chicken"
        recipe = {
            "name": "Garlic Chicken",
            "url": url,
            "source": "X",
            "ingredient_list": [],
            "steps_summary": "",
            "cook_time_minutes": None,
            "cuisine": None,
            "dietary_tags": [],
        }

        with patch.object(agent, "_search_tavily", AsyncMock(return_value=[recipe])):
            with patch.object(agent, "_search_spoonacular", AsyncMock(return_value=[recipe])):
                result = await agent.run(state)

        assert len(result["search_results"]) == 1

    async def test_filters_applied(self, state: AgentState) -> None:
        state["filters"] = {"cuisine": "italian"}
        agent = SearchAgent()
        recipes = [
            {
                "name": "Pasta",
                "url": "https://example.com/pasta",
                "source": "X",
                "ingredient_list": [],
                "steps_summary": "",
                "cook_time_minutes": None,
                "cuisine": "Italian",
                "dietary_tags": [],
            },
            {
                "name": "Tacos",
                "url": "https://example.com/tacos",
                "source": "X",
                "ingredient_list": [],
                "steps_summary": "",
                "cook_time_minutes": None,
                "cuisine": "Mexican",
                "dietary_tags": [],
            },
        ]

        with patch.object(agent, "_search_tavily", AsyncMock(return_value=recipes)):
            with patch.object(agent, "_search_spoonacular", AsyncMock(return_value=[])):
                result = await agent.run(state)

        assert len(result["search_results"]) == 1
        assert result["search_results"][0]["name"] == "Pasta"

    async def test_per_source_counts_tracked(self, state: AgentState) -> None:
        agent = SearchAgent()
        tavily_recipes = [
            {"name": "R1", "url": "https://a.com/1", "ingredient_list": [], "steps_summary": "",
             "cook_time_minutes": None, "cuisine": None, "dietary_tags": []},
            {"name": "R2", "url": "https://a.com/2", "ingredient_list": [], "steps_summary": "",
             "cook_time_minutes": None, "cuisine": None, "dietary_tags": []},
        ]
        spoon_recipes = [
            {"name": "R3", "url": "https://b.com/1", "ingredient_list": [], "steps_summary": "",
             "cook_time_minutes": None, "cuisine": None, "dietary_tags": []},
        ]

        with patch.object(agent, "_search_tavily", AsyncMock(return_value=tavily_recipes)):
            with patch.object(agent, "_search_spoonacular", AsyncMock(return_value=spoon_recipes)):
                result = await agent.run(state)

        assert result["tavily_recipe_count"] == 2
        assert result["spoonacular_recipe_count"] == 1
