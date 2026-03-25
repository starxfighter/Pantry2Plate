# AGENTS.md — Pantry-to-Plate AI Agent System

> **Global agent reference for all AI coding assistants, Claude, Copilot, Cursor, and similar tools.**
> This file defines agent roles, responsibilities, tool access, communication contracts, and
> behavioral rules for the Pantry-to-Plate multi-agent recipe finder system.

---

## System overview

Pantry-to-Plate uses a **LangGraph StateGraph** to orchestrate three specialized agents that
collaborate to help home cooks find recipes from ingredients they already have on hand.
All agents share a typed state object, communicate exclusively through that state, and are
observable via LangSmith tracing.

```
User Input → Parser Agent → Search Agent → Scorer Agent → Ranked Recipe Output
                  ↕               ↕               ↕
            [MCP: Pantry]  [MCP: Tavily]   [MCP: LangSmith]
                           [MCP: Spoonacular]
```

---

## Agent registry

### 1. Parser Agent
**File:** `backend/agents/parser_agent.py`
**Class:** `ParserAgent`
**Model:** `claude-sonnet-4-20250514`
**Temperature:** `0.0` (deterministic extraction)

**Purpose:** Converts freeform natural language ingredient descriptions into a clean,
normalized, deduplicated list of ingredients suitable for search queries.

**Reads from state:**
- `raw_input: str` — the user's freeform text

**Writes to state:**
- `parsed_ingredients: list[str]` — normalized ingredient list (e.g. `["chicken breast", "cheddar cheese"]`)
- `parse_error: str | None` — set if extraction fails

**MCP tools allowed:**
- `pantry://save_pantry(session_id, ingredients)` — persist ingredients to session store
- `pantry://get_pantry(session_id)` — retrieve previously saved pantry

**MCP tools forbidden:** All Tavily, Spoonacular, and LangSmith tools.

**System prompt location:** `backend/prompts/parser_system.txt`

**Output contract:**
```json
["ingredient_1", "ingredient_2", "ingredient_3"]
```
Return a JSON array only. No markdown, no preamble, no commentary.
Normalize: lowercase, singular form, remove brand names, expand abbreviations.

**Behavioral rules:**
- If input is fewer than 2 words and contains no recognizable food terms, set `parse_error` and return an empty list.
- Never invent ingredients not present in the user's input.
- Treat quantities and units (e.g. "2 cups of flour") as a single ingredient: `"flour"`.
- Maximum 30 ingredients per parse call.

---

### 2. Search Agent
**File:** `backend/agents/search_agent.py`
**Class:** `SearchAgent`
**Model:** `claude-sonnet-4-20250514`
**Temperature:** `0.2`

**Purpose:** Searches for recipes using the normalized ingredient list. Queries both
Tavily web search and the Spoonacular API in parallel, then consolidates and deduplicates
results into a unified list of up to 15 candidate recipes.

**Reads from state:**
- `parsed_ingredients: list[str]`
- `filters: dict` — optional: `{cuisine, dietary, max_cook_time_minutes}`

**Writes to state:**
- `search_results: list[RecipeCandidate]`
- `search_error: str | None`

**MCP tools allowed:**
- `tavily://web_search_recipes(query, max_results)` — web search
- `tavily://fetch_recipe_page(url)` — retrieve and parse a recipe page
- `spoonacular://search_recipes_by_ingredients(ingredients, number)` — API search
- `spoonacular://get_recipe_detail(recipe_id)` — full recipe data

**MCP tools forbidden:** Pantry and LangSmith tools.

**RecipeCandidate schema:**
```python
class RecipeCandidate(TypedDict):
    name: str
    url: str
    source: str                      # e.g. "AllRecipes", "Spoonacular"
    ingredient_list: list[str]       # all ingredients the recipe requires
    steps_summary: str               # 2-3 sentence summary of method
    cook_time_minutes: int | None
    cuisine: str | None
    dietary_tags: list[str]          # e.g. ["vegetarian", "gluten-free"]
```

**Behavioral rules:**
- Run Tavily and Spoonacular queries concurrently using `asyncio.gather`.
- Deduplicate by URL and by name similarity (fuzzy match threshold: 85%).
- If Spoonacular returns fewer than 5 results, make a second Tavily query with expanded search terms.
- Never fabricate recipe content. If a page cannot be fetched, skip it.
- Apply `filters` to exclude non-matching results before writing to state.
- Limit output to 15 candidates maximum.

---

### 3. Scorer Agent
**File:** `backend/agents/scorer_agent.py`
**Class:** `ScorerAgent`
**Model:** `claude-sonnet-4-20250514` (used only for dietary tag inference; scoring is deterministic Python)
**Temperature:** `0.0`

**Purpose:** Scores each recipe candidate against the user's available ingredients,
ranks the results, and logs the completed search run to LangSmith.

**Reads from state:**
- `search_results: list[RecipeCandidate]`
- `parsed_ingredients: list[str]`

**Writes to state:**
- `scored_recipes: list[ScoredRecipe]`
- `langsmith_run_url: str | None`

**MCP tools allowed:**
- `langsmith://log_search_run(session_id, inputs, outputs, latency_ms)` — observability
- `langsmith://get_run_url(run_id)` — retrieve trace URL for UI display

**MCP tools forbidden:** Tavily, Spoonacular, and Pantry tools.

**ScoredRecipe schema:**
```python
class ScoredRecipe(TypedDict):
    name: str
    url: str
    source: str
    match_score: float               # 0.0–100.0, % of recipe ingredients user has
    ingredients_have: list[str]      # intersection with parsed_ingredients
    ingredients_missing: list[str]   # recipe ingredients not in pantry
    steps_summary: str
    cook_time_minutes: int | None
    cuisine: str | None
    dietary_tags: list[str]
```

**Scoring algorithm:**
```
match_score = len(ingredients_have) / len(recipe.ingredient_list) * 100
```
Ingredient matching uses lowercase normalization and fuzzy matching (threshold: 80%).
Sort descending by `match_score`. Top 10 results go into `scored_recipes`.

**Behavioral rules:**
- Always call `langsmith://log_search_run` regardless of result quality.
- If `scored_recipes` is empty after filtering, do not set an error — return the empty list and let the UI handle the empty state.
- Never alter recipe content from what was received from the Search Agent.

---

## Shared state definition

**File:** `backend/graph.py`

```python
from typing import TypedDict, Optional

class AgentState(TypedDict):
    # Input
    session_id: str
    raw_input: str
    filters: dict

    # Parser output
    parsed_ingredients: list[str]
    parse_error: Optional[str]

    # Search output
    search_results: list[dict]
    search_error: Optional[str]

    # Scorer output
    scored_recipes: list[dict]
    langsmith_run_url: Optional[str]

    # Graph metadata
    current_step: str                # "parsing" | "searching" | "scoring" | "done" | "error"
    start_time: float
```

---

## Graph topology

```
START
  │
  ▼
parse_node ──(parse_error?)──► error_node ──► END
  │
  ▼
search_node ──(no results?)──► empty_node ──► END
  │
  ▼
score_node
  │
  ▼
output_node ──► END
```

**Conditional edges:**
- After `parse_node`: if `parse_error` is set → route to `error_node`
- After `search_node`: if `search_results` is empty → route to `empty_node`
- All other transitions are unconditional

**Checkpointing:** `MemorySaver` is attached at compile time. Every node transition
is checkpointed. `thread_id = session_id` for per-session isolation.

---

## MCP server registry

| Server name | Mount prefix | Transport | File |
|---|---|---|---|
| Pantry Store | `pantry://` | stdio | `backend/mcp_servers/pantry_server.py` |
| Tavily Search | `tavily://` | stdio | `backend/mcp_servers/tavily_server.py` |
| Spoonacular | `spoonacular://` | stdio | `backend/mcp_servers/spoonacular_server.py` |
| LangSmith | `langsmith://` | stdio | `backend/mcp_servers/langsmith_server.py` |

All MCP servers are started as subprocesses by `main.py` on application startup.
Each server runs in an isolated process and exposes its tools via FastMCP stdio transport.

---

## Inter-agent communication rules

1. Agents communicate **only** through `AgentState`. No direct agent-to-agent calls.
2. Each agent reads only from fields it is explicitly listed as reading above.
3. Each agent writes only to fields it is explicitly listed as writing above.
4. An agent must never modify a field written by a prior agent (read-only after written).
5. All agent responses must be validated against their output schema before writing to state.
6. If validation fails, the agent sets the appropriate `*_error` field and halts its node.

---

## Observability

- All agent LLM calls are automatically traced in LangSmith via `LANGCHAIN_TRACING_V2=true`.
- The Scorer Agent additionally logs a structured run record via `langsmith://log_search_run`.
- The `langsmith_run_url` written to state is surfaced in the frontend as a "View trace" link.
- LangSmith project name: `pantry-to-plate` (configured via `LANGSMITH_PROJECT` env var).

---

## Adding a new agent

1. Create `backend/agents/your_agent.py` implementing `BaseAgent` (see `backend/agents/base.py`).
2. Add the agent's node function to `backend/graph.py`.
3. Wire it into the `StateGraph` with appropriate edges.
4. Add its state fields to `AgentState`.
5. Register any new MCP tools it needs in the MCP server registry above.
6. Document the agent in this file following the template above.
7. Add unit tests to `tests/unit/test_your_agent.py`.

---

## Coding conventions for agents

- All agent classes inherit from `BaseAgent` in `backend/agents/base.py`.
- Agent node functions are `async def` and accept/return `AgentState`.
- Use `langchain_anthropic.ChatAnthropic` for all LLM calls.
- Bind MCP tools using `langchain_mcp_adapters` before invoking the LLM.
- All external calls (LLM + MCP) must be wrapped in `try/except` with structured error logging.
- Respect the temperature settings defined in this document — do not override without updating here.
- Agent files must not import from other agent files. Shared utilities live in `backend/utils/`.
