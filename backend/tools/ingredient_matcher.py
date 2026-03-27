"""Ingredient matching utilities for the Pantry-to-Plate scorer pipeline.

Provides three public functions:

* ``normalize`` — clean and standardise a single ingredient string.
* ``is_duplicate`` — fuzzy equality check between two ingredient strings.
* ``score_ingredient_match`` — compare a pantry list against a recipe's
  ingredient list and return a structured match report.

All fuzzy matching uses ``rapidfuzz`` for performance.  Match thresholds are
configurable via environment variables so they can be tuned without code
changes.
"""

from __future__ import annotations

import os
import re

from rapidfuzz import fuzz, process

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MATCH_THRESHOLD = 80

# Prefixes stripped during normalisation.  Sorted longest-first so the regex
# alternation matches greedily (e.g. "finely chopped" before "chopped").
_PREFIX_PATTERN = re.compile(
    r"^\s*(?:finely\s+|roughly\s+|coarsely\s+)?"
    r"(?:fresh|dried|frozen|chopped|minced|sliced|diced|grated|"
    r"crushed|peeled|trimmed|shredded|halved|quartered|ground)\s+",
    re.IGNORECASE,
)

_MULTI_SPACE = re.compile(r"\s{2,}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize(ingredient: str) -> str:
    """Normalise an ingredient string for consistent comparison.

    Applies the following transformations in order:

    1. Strip leading and trailing whitespace.
    2. Convert to lowercase.
    3. Remove common preparation-state prefixes (e.g. ``"fresh"``,
       ``"dried"``, ``"chopped"``, ``"minced"``, ``"sliced"``, ``"diced"``),
       including optional adverb qualifiers such as ``"finely"`` or
       ``"roughly"``.
    4. Collapse any run of multiple spaces to a single space.
    5. Strip again to remove any residual leading/trailing whitespace.

    Args:
        ingredient: Raw ingredient string, e.g. ``"Finely chopped Onion"``.

    Returns:
        Normalised string, e.g. ``"onion"``.

    Examples:
        >>> normalize("2 cups of Fresh Spinach")
        'fresh spinach'
        >>> normalize("minced garlic")
        'garlic'
        >>> normalize("  dried   oregano  ")
        'oregano'
        >>> normalize("finely chopped parsley")
        'parsley'
    """
    text = ingredient.strip().lower()
    text = _PREFIX_PATTERN.sub("", text)
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()


def is_duplicate(a: str, b: str, threshold: int = 85) -> bool:
    """Return ``True`` if two ingredient strings are fuzzy-equal.

    Comparison is performed on the lowercased raw strings (not normalised)
    using ``rapidfuzz.fuzz.ratio``, which measures character-level similarity
    on a 0–100 scale.

    Args:
        a: First ingredient string.
        b: Second ingredient string.
        threshold: Minimum ``fuzz.ratio`` score (inclusive) to treat the
            strings as duplicates.  Defaults to ``85``.

    Returns:
        ``True`` if ``fuzz.ratio(a.lower(), b.lower()) >= threshold``.

    Examples:
        >>> is_duplicate("tomato", "tomatoes")
        False
        >>> is_duplicate("chicken breast", "chicken breasts", threshold=80)
        True
    """
    return fuzz.ratio(a.lower(), b.lower()) >= threshold


def score_ingredient_match(
    pantry: list[str],
    recipe_ingredients: list[str],
) -> dict[str, list[str] | float]:
    """Score how well a pantry covers a recipe's ingredient list.

    Each recipe ingredient is normalised and matched against every normalised
    pantry ingredient using ``rapidfuzz.process.extractOne`` with
    ``fuzz.ratio`` as the scorer.  A match is accepted when the best score
    meets or exceeds the threshold from the ``INGREDIENT_MATCH_THRESHOLD``
    environment variable (default: ``80``).

    The match score is defined as::

        score = len(have) / len(recipe_ingredients) * 100

    An empty recipe ingredient list yields ``score = 0.0`` and both ``have``
    and ``missing`` as empty lists.

    Args:
        pantry: Normalised ingredient strings the user has available, e.g.
            ``["chicken breast", "garlic", "olive oil"]``.
        recipe_ingredients: Ingredient strings required by the recipe.  These
            are normalised internally before matching, so raw strings from an
            API response are acceptable.

    Returns:
        A dict with three keys:

        * ``"have"`` (``list[str]``): Recipe ingredients that were matched
          against the pantry (in their original, un-normalised form).
        * ``"missing"`` (``list[str]``): Recipe ingredients with no pantry
          match (in their original form).
        * ``"score"`` (``float``): Percentage of recipe ingredients covered,
          ``0.0``–``100.0``.

    Examples:
        >>> result = score_ingredient_match(
        ...     ["chicken", "garlic", "lemon"],
        ...     ["chicken breast", "garlic", "thyme", "lemon juice"],
        ... )
        >>> result["score"]
        75.0
        >>> result["have"]
        ['chicken breast', 'garlic', 'lemon juice']
        >>> result["missing"]
        ['thyme']
    """
    threshold: int = int(os.getenv("INGREDIENT_MATCH_THRESHOLD", str(_DEFAULT_MATCH_THRESHOLD)))

    if not recipe_ingredients:
        return {"have": [], "missing": [], "score": 0.0}

    normalised_pantry: list[str] = [normalize(p) for p in pantry]

    have: list[str] = []
    missing: list[str] = []

    for raw_ingredient in recipe_ingredients:
        norm_ingredient = normalize(raw_ingredient)

        match = process.extractOne(
            norm_ingredient,
            normalised_pantry,
            scorer=fuzz.ratio,
            score_cutoff=threshold,
        )

        if match is not None:
            have.append(raw_ingredient)
        else:
            missing.append(raw_ingredient)

    score = len(have) / len(recipe_ingredients) * 100
    return {"have": have, "missing": missing, "score": round(score, 2)}
