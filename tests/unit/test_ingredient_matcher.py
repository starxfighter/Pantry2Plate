"""Unit tests for backend/tools/ingredient_matcher.py.

All tests are pure-function calls — no I/O, no network, no mocks needed.
The INGREDIENT_MATCH_THRESHOLD env var is unset so tests use the default (80).
"""

from __future__ import annotations

import os

import pytest

# Ensure env default is used (not whatever is in .env)
os.environ.pop("INGREDIENT_MATCH_THRESHOLD", None)

from backend.tools.ingredient_matcher import (  # noqa: E402
    STAPLES,
    is_duplicate,
    is_staple,
    normalize,
    score_ingredient_match,
)


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_lowercases(self) -> None:
        assert normalize("Chicken Breast") == "chicken breast"

    def test_strips_whitespace(self) -> None:
        assert normalize("  garlic  ") == "garlic"

    def test_strips_prep_prefix_fresh(self) -> None:
        assert normalize("fresh spinach") == "spinach"

    def test_strips_prep_prefix_dried(self) -> None:
        assert normalize("dried oregano") == "oregano"

    def test_strips_prep_prefix_chopped(self) -> None:
        assert normalize("chopped onion") == "onion"

    def test_strips_prep_prefix_minced(self) -> None:
        assert normalize("minced garlic") == "garlic"

    def test_strips_adverb_and_prefix(self) -> None:
        assert normalize("finely chopped parsley") == "parsley"

    def test_strips_adverb_roughly(self) -> None:
        assert normalize("roughly chopped tomatoes") == "tomatoes"

    def test_collapses_multiple_spaces(self) -> None:
        # After prefix removal there could be extra spaces
        result = normalize("sliced   mushrooms")
        assert "  " not in result

    def test_plain_word_unchanged(self) -> None:
        assert normalize("eggs") == "eggs"

    def test_empty_string(self) -> None:
        assert normalize("") == ""


# ---------------------------------------------------------------------------
# is_duplicate
# ---------------------------------------------------------------------------


class TestIsDuplicate:
    def test_identical_strings(self) -> None:
        assert is_duplicate("tomato", "tomato") is True

    def test_case_insensitive(self) -> None:
        assert is_duplicate("Tomato", "tomato") is True

    def test_very_different_strings(self) -> None:
        assert is_duplicate("chicken", "broccoli") is False

    def test_close_but_below_default_threshold(self) -> None:
        # "tomato" vs "tomatoes": ratio ~86 — above default 85
        # Use strings that are clearly different enough
        assert is_duplicate("apple", "pineapple") is False

    def test_close_strings_pass_lower_threshold(self) -> None:
        assert is_duplicate("chicken breast", "chicken breasts", threshold=80) is True

    def test_default_threshold_85(self) -> None:
        # fuzz.ratio("garlic", "garlic") == 100 — well above 85
        assert is_duplicate("garlic", "garlic") is True

    def test_is_duplicate_above_threshold(self) -> None:
        # fuzz.ratio("chicken breast", "chicken breasts") ≈ 96 — above default 85
        assert is_duplicate("chicken breast", "chicken breasts") is True

    def test_empty_strings(self) -> None:
        assert is_duplicate("", "") is True


# ---------------------------------------------------------------------------
# is_staple
# ---------------------------------------------------------------------------


class TestIsStaple:
    @pytest.mark.parametrize(
        "ingredient",
        ["salt", "olive oil", "garlic", "pepper", "butter", "flour", "sugar", "water"],
    )
    def test_known_staples_exact(self, ingredient: str) -> None:
        assert is_staple(ingredient) is True

    @pytest.mark.parametrize(
        "ingredient",
        ["minced garlic", "dried oregano", "fresh basil", "chopped onion"],
    )
    def test_staples_with_prep_prefix(self, ingredient: str) -> None:
        assert is_staple(ingredient) is True

    @pytest.mark.parametrize(
        "ingredient",
        ["chicken breast", "salmon fillet", "broccoli", "cheddar cheese", "pasta"],
    )
    def test_non_staples(self, ingredient: str) -> None:
        assert is_staple(ingredient) is False

    def test_staples_set_nonempty(self) -> None:
        assert len(STAPLES) > 0

    def test_case_insensitive(self) -> None:
        assert is_staple("SALT") is True


# ---------------------------------------------------------------------------
# score_ingredient_match
# ---------------------------------------------------------------------------


class TestScoreIngredientMatch:
    def test_empty_recipe_returns_zero_score(self) -> None:
        result = score_ingredient_match(["chicken", "garlic"], [])
        assert result == {"have": [], "missing": [], "staples": [], "score": 0.0}

    def test_empty_pantry_all_missing_or_staple(self) -> None:
        result = score_ingredient_match([], ["chicken breast", "salt"])
        assert "chicken breast" in result["missing"]
        assert "salt" in result["staples"]
        assert result["score"] == 0.0

    def test_perfect_match(self) -> None:
        pantry = ["chicken", "lemon", "thyme"]
        recipe = ["chicken", "lemon", "thyme"]
        result = score_ingredient_match(pantry, recipe)
        assert result["score"] == 100.0
        assert result["missing"] == []
        assert result["staples"] == []
        assert set(result["have"]) == {"chicken", "lemon", "thyme"}

    def test_partial_match_score(self) -> None:
        # 2 have, 1 missing, 0 staples → 2/3 * 100 ≈ 66.67
        pantry = ["chicken", "lemon"]
        recipe = ["chicken", "lemon", "broccoli"]
        result = score_ingredient_match(pantry, recipe)
        assert result["score"] == pytest.approx(66.67, abs=0.01)
        assert "broccoli" in result["missing"]

    def test_staples_excluded_from_denominator(self) -> None:
        # pantry has chicken; recipe has chicken + salt (staple)
        # effective_total = 2 - 1 = 1; have = 1 → score = 100.0
        pantry = ["chicken"]
        recipe = ["chicken", "salt"]
        result = score_ingredient_match(pantry, recipe)
        assert result["score"] == 100.0
        assert "salt" in result["staples"]
        assert "salt" not in result["missing"]

    def test_all_staples_score_100(self) -> None:
        # Recipe consists entirely of staples user doesn't have
        pantry: list[str] = []
        recipe = ["salt", "pepper", "olive oil"]
        result = score_ingredient_match(pantry, recipe)
        assert result["score"] == 100.0
        assert result["have"] == []
        assert result["missing"] == []
        assert len(result["staples"]) == 3

    def test_prep_prefix_normalisation_in_matching(self) -> None:
        # Pantry has "garlic"; recipe has "minced garlic" → should match
        pantry = ["garlic", "chicken"]
        recipe = ["minced garlic", "chicken"]
        result = score_ingredient_match(pantry, recipe)
        assert result["score"] == 100.0

    def test_return_keys(self) -> None:
        result = score_ingredient_match(["egg"], ["egg"])
        assert set(result.keys()) == {"have", "missing", "staples", "score"}

    def test_score_is_rounded_to_two_decimal_places(self) -> None:
        # 1/3 = 33.333... → should round to 33.33
        pantry = ["chicken"]
        recipe = ["chicken", "salmon", "tuna"]
        result = score_ingredient_match(pantry, recipe)
        score_str = str(result["score"])
        # At most 2 decimal places
        if "." in score_str:
            assert len(score_str.split(".")[1]) <= 2

    def test_score_none_match(self) -> None:
        # Empty pantry, only non-staple ingredients → all in missing, score 0.0
        result = score_ingredient_match([], ["chicken", "broccoli", "pasta", "salmon"])
        assert result["score"] == 0.0
        assert set(result["missing"]) == {"chicken", "broccoli", "pasta", "salmon"}
        assert result["have"] == []
        assert result["staples"] == []

    def test_score_partial_match(self) -> None:
        # 4 non-staple ingredients, pantry has 2 → 2/4 * 100 = 50.0
        pantry = ["chicken", "broccoli"]
        recipe = ["chicken", "broccoli", "salmon", "pasta"]
        result = score_ingredient_match(pantry, recipe)
        assert result["score"] == 50.0
        assert set(result["have"]) == {"chicken", "broccoli"}
        assert set(result["missing"]) == {"salmon", "pasta"}
