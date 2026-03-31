"""LangGraph state definitions, agent nodes, and graph builder for Pantry-to-Plate.

Defines the shared AgentState TypedDict, the RecipeCandidate and ScoredRecipe
data contracts, six async node functions backed by module-level agent singletons,
and build_graph() / compile_graph() which assemble and compile the StateGraph.
"""

from __future__ import annotations

from typing import Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph


# ---------------------------------------------------------------------------
# Recipe data contracts
# ---------------------------------------------------------------------------


class RecipeCandidate(TypedDict):
    """A single recipe returned by the Search Agent before scoring.

    Attributes:
        name: Human-readable recipe title.
        url: Canonical URL of the recipe source page.
        source: Publisher name (e.g. "AllRecipes", "Spoonacular").
        ingredient_list: All ingredients the recipe requires, lowercase singular.
        steps_summary: 2–3 sentence summary of the cooking method.
        cook_time_minutes: Total cook + prep time in minutes, or None if unknown.
        cuisine: Cuisine category (e.g. "Italian", "Mexican"), or None.
        dietary_tags: Zero or more tags, e.g. ["vegetarian", "gluten-free"].
    """

    name: str
    url: str
    source: str
    ingredient_list: list[str]
    steps_summary: str
    cook_time_minutes: Optional[int]
    cuisine: Optional[str]
    dietary_tags: list[str]


class ScoredRecipe(TypedDict):
    """A RecipeCandidate enriched with pantry-match scoring by the Scorer Agent.

    Attributes:
        name: Human-readable recipe title.
        url: Canonical URL of the recipe source page.
        source: Publisher name.
        ingredient_list: All ingredients the recipe requires.
        steps_summary: 2–3 sentence summary of the cooking method.
        cook_time_minutes: Total cook + prep time in minutes, or None if unknown.
        cuisine: Cuisine category, or None.
        dietary_tags: Zero or more dietary tags.
        match_score: Percentage (0.0–100.0) of recipe ingredients the user has.
        ingredients_have: Subset of ingredient_list present in the user's pantry.
        ingredients_missing: Subset of ingredient_list absent from the user's pantry
            (excludes staples).
        ingredients_staple: Subset of ingredient_list that are common kitchen staples
            absent from the pantry; excluded from scoring.
    """

    name: str
    url: str
    source: str
    ingredient_list: list[str]
    steps_summary: str
    cook_time_minutes: Optional[int]
    cuisine: Optional[str]
    dietary_tags: list[str]
    match_score: float
    ingredients_have: list[str]
    ingredients_missing: list[str]
    ingredients_staple: list[str]


# ---------------------------------------------------------------------------
# Shared graph state
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    """Shared state object threaded through every node in the LangGraph StateGraph.

    All agents read from and write to this object exclusively — no direct
    agent-to-agent communication is permitted.  Fields are grouped by the
    agent that owns them; downstream agents treat upstream fields as read-only.

    Attributes:
        session_id: UUID string identifying the current user session.
        raw_input: Freeform text submitted by the user (e.g. "chicken, rice, tomatoes").
        filters: Optional search filters supplied by the user.
            Recognised keys: ``cuisine`` (str), ``dietary`` (str),
            ``max_cook_time_minutes`` (int).

        parsed_ingredients: Normalised ingredient list produced by the Parser Agent.
        parse_error: Non-None if the Parser Agent failed; downstream nodes should
            short-circuit when this field is set.

        search_results: Flat list of RecipeCandidate dicts produced by the Search Agent.
        search_error: Non-None if the Search Agent encountered an unrecoverable error.

        scored_recipes: Ranked list of ScoredRecipe dicts produced by the Scorer Agent.
        langsmith_run_url: Public LangSmith trace URL written by the Scorer Agent;
            surfaced in the frontend as a "View trace" link.

        current_step: Machine-readable pipeline stage.
            One of: ``"parsing"``, ``"searching"``, ``"scoring"``,
            ``"done"``, ``"error"``, ``"empty"``.
        start_time: Unix timestamp (float) recorded at graph entry; used to
            calculate total pipeline latency for LangSmith logging.
    """

    # --- Input ---
    session_id: str
    raw_input: str
    filters: dict

    # --- Parser Agent output ---
    parsed_ingredients: list[str]
    parse_error: Optional[str]

    # --- Search Agent output ---
    search_results: list[dict]
    search_error: Optional[str]
    tavily_recipe_count: int
    spoonacular_recipe_count: int

    # --- Scorer Agent output ---
    scored_recipes: list[dict]
    langsmith_run_url: Optional[str]

    # --- Graph metadata ---
    current_step: str
    start_time: float


# ---------------------------------------------------------------------------
# Agent singletons
# ---------------------------------------------------------------------------

# Imported here (after TypedDicts are defined) to avoid circular imports.
from backend.agents.parser_agent import ParserAgent  # noqa: E402
from backend.agents.search_agent import SearchAgent  # noqa: E402
from backend.agents.scorer_agent import ScorerAgent  # noqa: E402

_parser = ParserAgent()
_search = SearchAgent()
_scorer = ScorerAgent()


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


async def parse_node(state: AgentState) -> AgentState:
    """Set current_step and delegate to the Parser Agent."""
    state["current_step"] = "parsing"
    return await _parser.run(state)


async def search_node(state: AgentState) -> AgentState:
    """Set current_step and delegate to the Search Agent."""
    state["current_step"] = "searching"
    return await _search.run(state)


async def score_node(state: AgentState) -> AgentState:
    """Set current_step and delegate to the Scorer Agent."""
    state["current_step"] = "scoring"
    return await _scorer.run(state)


async def output_node(state: AgentState) -> AgentState:
    """Mark the pipeline as successfully completed."""
    state["current_step"] = "done"
    return state


async def error_node(state: AgentState) -> AgentState:
    """Mark the pipeline as failed (parse or unrecoverable error)."""
    state["current_step"] = "error"
    return state


async def empty_node(state: AgentState) -> AgentState:
    """Mark the pipeline as completed with no matching recipes found."""
    state["current_step"] = "empty"
    return state


# ---------------------------------------------------------------------------
# Edge routers
# ---------------------------------------------------------------------------


def _route_parse(state: AgentState) -> str:
    """Route after parse_node: error path if parsing failed, else search."""
    if state["parse_error"]:
        return "error_node"
    return "search_node"


def _route_search(state: AgentState) -> str:
    """Route after search_node: empty path if no results found, else score."""
    if not state["search_results"]:
        return "empty_node"
    return "score_node"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph() -> StateGraph:
    """Assemble and return the uncompiled StateGraph.

    Full topology::

        START
          │
          ▼
        parse_node ──(parse_error?)──► error_node ──► END
          │
          ▼
        search_node ──(no results?)──► empty_node ──► END
          │
          ▼
        score_node ──► output_node ──► END

    MemorySaver compilation is deferred to Phase 5 (``compile_graph()``),
    once all agent node implementations are in place.

    Returns:
        A configured but uncompiled ``StateGraph[AgentState]`` instance.
    """
    builder = StateGraph(AgentState)

    # Nodes
    builder.add_node("parse_node", parse_node)
    builder.add_node("search_node", search_node)
    builder.add_node("score_node", score_node)
    builder.add_node("output_node", output_node)
    builder.add_node("error_node", error_node)
    builder.add_node("empty_node", empty_node)

    # Entry edge
    builder.add_edge(START, "parse_node")

    # Conditional edges
    builder.add_conditional_edges(
        "parse_node",
        _route_parse,
        {"error_node": "error_node", "search_node": "search_node"},
    )
    builder.add_conditional_edges(
        "search_node",
        _route_search,
        {"empty_node": "empty_node", "score_node": "score_node"},
    )

    # Unconditional edges
    builder.add_edge("score_node", "output_node")
    builder.add_edge("output_node", END)
    builder.add_edge("error_node", END)
    builder.add_edge("empty_node", END)

    return builder


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


def compile_graph():
    """Compile the StateGraph with a MemorySaver checkpointer.

    Each node transition is persisted in-memory, keyed by ``thread_id``
    (set to ``session_id`` by callers via ``CONFIG_TEMPLATE``).

    Returns:
        A compiled LangGraph ``CompiledStateGraph`` ready to invoke.
    """
    builder = build_graph()
    return builder.compile(checkpointer=MemorySaver())


# Module-level compiled graph instance — import and invoke directly.
graph = compile_graph()

# Callers copy this dict and set thread_id = session_id before invoking.
CONFIG_TEMPLATE: dict = {"configurable": {"thread_id": None}}
