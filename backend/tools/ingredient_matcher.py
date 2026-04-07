"""Ingredient matching utilities for the Pantry-to-Plate scorer pipeline.

Provides four public functions:

* ``normalize`` — clean and standardise a single ingredient string.
* ``is_duplicate`` — fuzzy equality check between two ingredient strings.
* ``is_staple`` — return True if an ingredient is a common kitchen staple.
* ``score_ingredient_match`` — compare a pantry list against a recipe's
  ingredient list and return a structured match report (have / missing /
  staples / score).

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

# Common kitchen staples that are almost always available in a home pantry.
# Ingredients that fuzzy-match any entry here are excluded from the "missing"
# list and from the match-score denominator, preventing them from unfairly
# depressing a recipe's score.
STAPLES: frozenset[str] = frozenset(
    {
        # Fats & oils
        "oil", "olive oil", "vegetable oil", "canola oil", "coconut oil",
        "butter", "margarine", "cooking spray",
        # Salt & pepper
        "salt", "sea salt", "kosher salt", "black pepper", "white pepper",
        "pepper",
        # Aromatics
        "garlic", "onion", "shallot", "green onion", "scallion",
        # Pantry basics
        "water", "flour", "all-purpose flour", "bread flour",
        "sugar", "brown sugar", "powdered sugar", "confectioners sugar",
        "baking soda", "baking powder", "cornstarch",
        "vinegar", "white vinegar", "apple cider vinegar",
        # Dried herbs & spices
        "oregano", "thyme", "rosemary", "basil", "parsley",
        "cilantro", "cumin", "paprika", "smoked paprika",
        "chili powder", "cayenne", "cayenne pepper",
        "turmeric", "coriander", "bay leaf", "bay leaves",
        "cinnamon", "nutmeg", "ginger", "garlic powder", "onion powder",
        "red pepper flakes", "dried oregano", "dried thyme", "dried basil",
        # Condiments / staple liquids
        "soy sauce", "worcestershire sauce", "hot sauce",
        "chicken broth", "vegetable broth", "beef broth",
        "lemon juice", "lime juice",
        # Dairy basics
        "milk", "eggs", "egg",
    }
)

# Strips leading quantity expressions such as "2 cups of", "500g", "1/2 teaspoon",
# "a handful of", or "some" from the start of an ingredient string.
_QUANTITY_PATTERN = re.compile(
    r"""
    ^\s*
    (?:
        # "a/an" + unit + optional "of"
        an?\s+
        (?:cups?|tablespoons?|tbsps?|tbsp|teaspoons?|tsps?|tsp|
           handfuls?|pinch(?:es)?|dashes?|slices?|pieces?|
           heads?|bunches?|cans?|stalks?|sprigs?|cloves?)
        \s*(?:of\s+)?
    |
        # "some"
        some\s+
    |
        # number (integer, decimal, or fraction) + optional unit + optional "of"
        (?:\d[\d\s./]*)
        \s*
        (?:grams?|g|kilograms?|kg|milliliters?|ml|liters?|l|
           ounces?|oz|pounds?|lbs?|lb|
           cups?|tablespoons?|tbsps?|tbsp|teaspoons?|tsps?|tsp|
           cloves?|slices?|sprigs?|handfuls?|pinch(?:es)?|dashes?|
           cans?|bunches?|heads?|stalks?|pieces?)?
        \s*
        (?:of\s+)?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

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


def is_staple(ingredient: str) -> bool:
    """Return ``True`` if an ingredient is a common kitchen staple.

    Normalises *ingredient* before checking against the ``STAPLES`` set, so
    preparation-state prefixes (e.g. ``"minced garlic"``) are handled
    correctly.

    Args:
        ingredient: Raw ingredient string.

    Returns:
        ``True`` if the normalised ingredient fuzzy-matches any entry in
        ``STAPLES`` with a similarity score ≥ 85.

    Examples:
        >>> is_staple("minced garlic")
        True
        >>> is_staple("chicken breast")
        False
    """
    norm = normalize(ingredient)
    # Exact match first (fast path)
    if norm in STAPLES:
        return True
    # Fuzzy match — handles minor plurals / wording variations
    match = process.extractOne(norm, STAPLES, scorer=fuzz.ratio, score_cutoff=85)
    return match is not None


def normalize(ingredient: str) -> str:
    """Normalise an ingredient string for consistent comparison.

    Applies the following transformations in order:

    1. Strip leading and trailing whitespace.
    2. Convert to lowercase.
    3. Remove leading quantity expressions: numbers, units, and connective
       words such as ``"2 cups of"``, ``"500g"``, ``"1/2 teaspoon"``,
       ``"a handful of"``, or ``"some"``.
    4. Remove common preparation-state prefixes (e.g. ``"fresh"``,
       ``"dried"``, ``"chopped"``, ``"minced"``, ``"sliced"``, ``"diced"``),
       including optional adverb qualifiers such as ``"finely"`` or
       ``"roughly"``.
    5. Collapse any run of multiple spaces to a single space.
    6. Strip again to remove any residual leading/trailing whitespace.

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
    text = _QUANTITY_PATTERN.sub("", text)
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

    Ingredients identified as common kitchen staples (via ``is_staple``) that
    are *not* in the user's pantry are placed in the ``"staples"`` bucket.
    They are excluded from both the ``"missing"`` list and the score
    denominator so they do not unfairly depress match scores.

    The match score is defined as::

        effective_total = len(recipe_ingredients) - len(staples)
        score = len(have) / effective_total * 100   # 100.0 when effective_total == 0

    An empty recipe ingredient list yields ``score = 0.0`` and all three
    lists empty.

    Args:
        pantry: Normalised ingredient strings the user has available, e.g.
            ``["chicken breast", "garlic", "olive oil"]``.
        recipe_ingredients: Ingredient strings required by the recipe.  These
            are normalised internally before matching, so raw strings from an
            API response are acceptable.

    Returns:
        A dict with four keys:

        * ``"have"`` (``list[str]``): Recipe ingredients matched in pantry.
        * ``"missing"`` (``list[str]``): Non-staple ingredients absent from pantry.
        * ``"staples"`` (``list[str]``): Staple ingredients absent from pantry
          (excluded from scoring).
        * ``"score"`` (``float``): Percentage of non-staple recipe ingredients
          covered, ``0.0``–``100.0``.

    Examples:
        >>> result = score_ingredient_match(
        ...     ["chicken", "garlic", "lemon"],
        ...     ["chicken breast", "garlic", "thyme", "lemon juice", "salt"],
        ... )
        >>> result["score"]
        75.0
        >>> result["have"]
        ['chicken breast', 'garlic', 'lemon juice']
        >>> result["missing"]
        ['thyme']
        >>> result["staples"]
        ['salt']
    """
    threshold: int = int(os.getenv("INGREDIENT_MATCH_THRESHOLD", str(_DEFAULT_MATCH_THRESHOLD)))

    if not recipe_ingredients:
        return {"have": [], "missing": [], "staples": [], "score": 0.0}

    normalised_pantry: list[str] = [normalize(p) for p in pantry]

    have: list[str] = []
    missing: list[str] = []
    staples: list[str] = []

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
        elif is_staple(raw_ingredient):
            staples.append(raw_ingredient)
        else:
            missing.append(raw_ingredient)

    effective_total = len(recipe_ingredients) - len(staples)
    score = (len(have) / effective_total * 100) if effective_total > 0 else 100.0
    return {"have": have, "missing": missing, "staples": staples, "score": round(score, 2)}
