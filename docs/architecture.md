# Architecture — Pantry-to-Plate

_Last updated: 2026-04-07_

---

## Overview

Pantry-to-Plate is a local web application that accepts a user's available
ingredients and returns ranked recipes they can cook right now.  The backend
is a LangGraph multi-agent pipeline exposed via a FastAPI SSE gateway; the
frontend is a single-page HTML file.

---

## System layers

```
Browser (frontend/index.html)
       │  POST /search  +  EventSource SSE
       ▼
FastAPI Gateway (backend/main.py)
       │  LangGraph graph.ainvoke(state)
       ▼
LangGraph StateGraph
  ┌─────────────────────────────────────────────┐
  │  parse_node → search_node → score_node      │
  │       │              │            │          │
  │  error_node    empty_node   output_node      │
  └─────────────────────────────────────────────┘
       │  MCP stdio tool calls (subprocess)
       ▼
4 FastMCP Servers (stdio subprocesses)
  ├── pantry_server.py      — SQLite ingredient store (data/pantry.db)
  ├── tavily_server.py      — web recipe search
  ├── spoonacular_server.py — recipe database search
  └── langsmith_server.py   — observability trace logging
       │  REST / HTTP
       ▼
External APIs
  ├── Anthropic (Claude Sonnet)
  ├── Tavily Search API
  ├── Spoonacular Recipe API
  └── LangSmith Tracing
```

---

## Key components

### `backend/graph.py`

Defines the shared `AgentState` TypedDict, `RecipeCandidate` and `ScoredRecipe`
data contracts, six async node functions, and the compiled `StateGraph`.

**Node topology:**
```
START → parse_node → (error?) → error_node → END
                   → search_node → (empty?) → empty_node → END
                                → score_node → output_node → END
```

**State fields:**

| Field | Owner | Description |
|---|---|---|
| `session_id` | Input | UUID identifying the user session |
| `raw_input` | Input | Freeform ingredient text from the user |
| `filters` | Input | Optional cuisine / dietary / time filters |
| `parsed_ingredients` | ParserAgent | Normalised ingredient list |
| `parse_error` | ParserAgent | Non-None if parsing failed |
| `search_results` | SearchAgent | Raw `RecipeCandidate` dicts |
| `search_error` | SearchAgent | Non-None if both search sources failed |
| `scored_recipes` | ScorerAgent | Ranked `ScoredRecipe` dicts |
| `langsmith_run_url` | ScorerAgent | Public LangSmith trace URL |
| `run_tags` | Caller | Optional LangSmith tags (e.g. `["eval-v0.1"]`) |
| `current_step` | Graph nodes | Pipeline stage label |
| `start_time` | Caller | Unix timestamp for latency tracking |

---

### `backend/agents/`

All agents extend `BaseAgent` (ABC):

| Agent | Model temp | MCP tools used | Output |
|---|---|---|---|
| `ParserAgent` | 0.0 | `pantry://save_pantry` | `parsed_ingredients` |
| `SearchAgent` | 0.2 | `tavily://web_search_recipes`, `spoonacular://search_recipes_by_ingredients`, `spoonacular://get_recipe_detail` | `search_results` |
| `ScorerAgent` | 0.0 | `langsmith://log_search_run`, `langsmith://get_run_url` | `scored_recipes`, `langsmith_run_url` |

---

### `backend/mcp_servers/`

Four FastMCP stdio servers launched as subprocesses by `MCPServerManager`.
Agents create their own short-lived `MultiServerMCPClient` sessions per call
(see `decisions.md` ADR-001).

| Server | Tools |
|---|---|
| `pantry_server.py` | `save_pantry`, `get_pantry`, `clear_pantry` |
| `tavily_server.py` | `web_search_recipes`, `fetch_recipe_page` |
| `spoonacular_server.py` | `search_recipes_by_ingredients`, `get_recipe_detail` |
| `langsmith_server.py` | `log_search_run`, `get_run_url` |

**Windows-specific:** Spoonacular detail fetches run sequentially (not concurrently)
to avoid a Windows ProactorEventLoop IOCP hang after many subprocess reads.
See `docs/cross_platform.md` for what changes on Linux/macOS.

---

### `backend/tools/ingredient_matcher.py`

Pure Python utility using `rapidfuzz` for fuzzy ingredient matching.
`score_ingredient_match(pantry, recipe_ingredients)` returns the percentage of
recipe ingredients the user has, plus `have` / `missing` lists.

---

## Data flow (happy path)

1. User submits ingredient text via `POST /search`.
2. FastAPI creates `AgentState`, starts SSE response, invokes `graph.ainvoke`.
3. **parse_node**: LLM extracts ingredient list → saved to pantry MCP server.
4. **search_node**: Tavily web search + Spoonacular API search run sequentially;
   results merged, deduplicated, filtered, capped at 15.
5. **score_node**: Each recipe scored against pantry (rapidfuzz); sorted, sliced
   to top 10; pipeline run logged to LangSmith via MCP.
6. **output_node**: `current_step = "done"`.
7. FastAPI streams `scored_recipes` to the browser via SSE.

---

## Environment variables

See `.env.example` for the full list.  Key variables:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude model access |
| `ANTHROPIC_MODEL` | Model ID (default: `claude-sonnet-4-20250514`) |
| `TAVILY_API_KEY` | Tavily search |
| `SPOONACULAR_API_KEY` | Spoonacular recipe DB |
| `LANGSMITH_API_KEY` | LangSmith tracing |
| `LANGSMITH_PROJECT` | LangSmith project name |
| `TOP_RECIPE_COUNT` | Max ranked recipes returned (default: 10) |
| `MAX_RECIPE_RESULTS` | Max raw search results (default: 15) |
| `PANTRY_DB_PATH` | SQLite file for pantry store (default: `data/pantry.db`) |
| `SEARCH_TIMEOUT_SECONDS` | Hard cap on `/search` pipeline execution (default: 120) |
| `SPOONACULAR_ENABLED` | Set `false` to skip Spoonacular when quota exhausted |

---

### `backend/main.py` — additional endpoints (added 2026-03-27)

| Endpoint | Purpose |
|---|---|
| `GET /pantry/{session_id}` | Returns `parsed_ingredients` from LangGraph MemorySaver checkpoint |
| `DELETE /pantry/{session_id}` | Clears `parsed_ingredients` in checkpoint via `graph.aupdate_state` |

Both return 200 even when no checkpoint exists (`[]` / `{"cleared": true}`).

---

### `backend/utils/log_config.py` (added 2026-03-27)

`get_logger(name)` returns a `logging.Logger` emitting one JSON line per record to stderr.
Fields: `timestamp` (ISO-8601 ms UTC), `level`, `name`, `message`, plus optional
`session_id`, `current_step`, `duration_ms` when passed via `extra={}`.
Log level from `LOG_LEVEL` env var (default `INFO`). Idempotent — handler attached once.

---

### `frontend/index.html` (completed Phase 7 — 2026-03-27)

Single-file vanilla HTML/CSS/JS UI. Key features:

- **Ingredient input**: textarea → comma/blur triggers pill parsing; X button removes;
  "N ingredients detected" count; session ID from `crypto.randomUUID()` in `localStorage`.
- **Filter bar**: cuisine toggles (Any/Italian/Mexican/Asian/American/Mediterranean),
  dietary checkboxes (Vegetarian/Vegan/Gluten-Free), cook time slider (0–120 min, step 5).
- **SSE consumption**: `fetch` + `ReadableStream` manual parser (EventSource is GET-only).
  Step mapping: `step:"searching"` → step 1 done; `step:"scoring"` → step 2 done;
  `step:"done"` → step 3 done; `event:done` → step 4 done.
- **4-step stepper**: pulse ring on active, terracotta fill + ✓ on complete, connector
  `scaleX` fill transition. Collapses (`max-height`) after results render.
- **Recipe cards**: match % badge, meta, dietary tags, ingredient chips, 3-line summary,
  full recipe link.
- **Error state**: red card with message + "Try Again" → `searchRecipes()`.
- **LangSmith link**: appears after `event:done` carries `langsmith_run_url`.

---

## Phase 8 — Testing & Eval (completed 2026-04-07)

### Test suite

| File | Tests | Coverage |
|---|---|---|
| `tests/unit/test_ingredient_matcher.py` | 49 | 100% of `ingredient_matcher.py` |
| `tests/unit/test_parser_agent.py` | 16 | `parser_agent.py` |
| `tests/unit/test_search_agent.py` | 38 | `search_agent.py` |
| `tests/unit/test_scorer_agent.py` | 17 | `scorer_agent.py` |
| `tests/unit/test_mcp_servers.py` | 27 | all 4 MCP servers |
| `tests/unit/test_mcp_manager.py` | 17 | `mcp_manager.py` |
| `tests/integration/test_api.py` | 10 | FastAPI endpoints |
| `tests/integration/test_graph.py` | 2 | full graph (live, skip-guarded) |

**Total: 176 unit + 12 integration tests. Coverage: 87% on `backend/`. Ruff: 0 errors.**

`pytest.ini` configures `asyncio_mode = auto`, `pythonpath = .` (CI compatibility), and registers `integration` + `slow` markers.

### Eval harness

`backend/utils/eval_runner.py` — 10 test cases covering simple, complex, dietary, vague, and non-English inputs. Each run tagged `eval-v0.1` in LangSmith. 10/10 passed on 2026-04-07.

### Parser improvement (2026-04-07)

Added rule 8 to `backend/prompts/parser_system.txt`: translate non-English ingredient names to English before normalising. Confirmed Spanish input (`pollo→chicken`, `frijoles→black bean`) now scores correctly.

### LangSmith tagging

`AgentState` gained an optional `run_tags: list[str]` field. `log_search_run` MCP tool accepts `tags: list[str]` and includes them in the LangSmith run payload. Scorer agent threads `state["run_tags"]` through to the MCP call.
