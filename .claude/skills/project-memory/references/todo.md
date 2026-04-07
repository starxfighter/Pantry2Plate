# Todo — Pantry-to-Plate

Phased build plan. Check off tasks as they are completed.
Add newly discovered sub-tasks inline under the relevant phase.

---

## Phase 1 — Project Scaffolding

- [x] Create full directory structure from README spec
- [x] Add `__init__.py` to all Python backend packages
- [x] Add `.gitkeep` to empty test subdirectories
- [x] Write `.env.example` with all env vars and comments
- [x] Write `.gitignore` (Python + HTML)
- [x] Write `.github/workflows/ci.yml` (lint + test + coverage)
- [x] Create `.claude/skills/project-memory/` session memory system

---

## Phase 2 — Dependencies & Configuration

- [x] Write `backend/requirements.txt` with pinned versions
- [x] Rename `backend/utils/logging.py` → `log_config.py` (stdlib name conflict)
- [x] Write `backend/utils/smoke_test.py` — verify all 4 API connections
- [x] Verify LangSmith trace appears in `pantry-to-plate` project
- [x] Write `backend/utils/log_config.py` (structured logging setup)
- [x] ~~Write `backend/utils/session.py`~~ — superseded; session_id generated in frontend via `crypto.randomUUID()` and passed through state; no backend helper needed

---

## Phase 3 — MCP Servers ✅

- [x] `backend/mcp_servers/pantry_server.py` — in-memory ingredient store per session
- [x] `backend/mcp_servers/tavily_server.py` — Tavily web search wrapper
- [x] `backend/mcp_servers/spoonacular_server.py` — Spoonacular API wrapper
- [x] `backend/mcp_servers/langsmith_server.py` — trace logging helpers
- [x] Unit tests for each MCP server in `tests/unit/` — 27 tests in `test_mcp_servers.py`

---

## Phase 4 — Agents ✅

- [x] `backend/agents/base.py` — `BaseAgent` ABC (model client, prompt loading)
- [x] `backend/prompts/parser_system.txt` — Parser Agent system prompt
- [x] `backend/agents/parser_agent.py` — ingredient extraction
- [x] `backend/prompts/search_system.txt` — Search Agent system prompt
- [x] `backend/agents/search_agent.py` — Tavily + Spoonacular search
- [x] `backend/agents/scorer_agent.py` — fuzzy match scoring + ranking
- [x] `backend/tools/ingredient_matcher.py` — fuzzy matching utility
- [x] Unit tests for each agent in `tests/unit/` — 16 parser, 38 search, 17 scorer tests

---

## Phase 5 — LangGraph Orchestration ✅

- [x] `backend/graph.py` — `StateGraph` wiring Parser → Search → Scorer
- [x] Define `AgentState` TypedDict + `RecipeCandidate` + `ScoredRecipe`
- [x] Wire `MemorySaver` checkpointer
- [x] End-to-end smoke test (`backend/utils/graph_test.py`) — all assertions pass
- [x] Integration test: full graph run — `tests/integration/test_graph.py` (2 live tests, skip guard if no API key)

---

## Phase 6 — FastAPI Gateway ✅

- [x] `backend/main.py` — FastAPI app, lifespan (MCP startup/shutdown), CORS
- [x] `POST /search` endpoint — accepts ingredient text, streams SSE
- [x] `GET /health` endpoint
- [x] SSE streaming of partial results and final ranked list
- [x] Integration tests for API endpoints — 10 tests in `tests/integration/test_api.py`

---

## Phase 7 — Frontend ✅

- [x] `frontend/index.html` — ingredient input form
- [x] SSE consumption and live result rendering
- [x] "View agent trace" link using LangSmith run URL
- [x] Error state and loading indicator
- [x] Ingredient pill parsing (comma/blur, X to remove, count label)
- [x] Session ID from localStorage (`crypto.randomUUID()`)
- [x] Filter bar: cuisine toggles, dietary checkboxes, cook time slider
- [x] 4-step horizontal stepper with CSS transitions (active pulse, complete fill)

---

## Phase 8 — Testing & Polish

- [x] **Re-test full pipeline** — 10/10 eval cases passed 2026-04-07 via `eval_runner.py`; LangSmith trace links confirmed; Spoonacular 402 (quota) degrades gracefully to Tavily-only
- [x] Fill `tests/integration/` with end-to-end graph + API tests (10 integration tests in `tests/integration/test_api.py`)
- [x] Add `pytest.ini` with asyncio mode config (`asyncio_mode = auto`, `asyncio_default_fixture_loop_scope = function`)
- [x] Reach ≥ 80 % unit test coverage on `backend/` — **87% achieved** (176 tests: 46 ingredient_matcher, 16 parser_agent, 38 search_agent, 13 scorer_agent, 27 mcp_servers, 17 mcp_manager, 10 integration API; `.coveragerc` excludes utility scripts)
- [x] Write `docs/architecture.md` — exists, last updated 2026-03-27; Phase 8 "What's next" section is stale (still describes Phase 8 as future work)
- [x] Final `ruff` pass — 0 errors (`search_agent.py` E402 fixed, 3 unused test imports removed)

---

## Backlog / Nice-to-Have

- [ ] Docker Compose for local development
- [ ] GitHub Actions: add integration test job (requires secrets)
- [ ] GitHub Actions: bump action versions to Node.js 24-compatible releases before 2026-06-02 deadline — in `.github/workflows/ci.yml` replace `actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4` with their latest major versions that ship with Node.js 24 (check each repo's releases). Current warning fires on every CI run.
- [ ] Rate-limit handling for Spoonacular free tier
- [ ] Ingredient quantity parsing (e.g. "2 cups of flour")
- [ ] Persistent pantry across sessions (replace in-memory store)

## UI Polish

- [x] **Spice/herb/staple chips should be yellow** — ingredients identified as common spices, herbs, or kitchen staples (e.g. salt, pepper, olive oil, garlic) should render as yellow chips, not red "missing" chips, since users almost always have them
- [x] **Scorer should ignore spices/herbs/staples** — the ingredient match score should not count common spices, herbs, and kitchen staples as "missing". They inflate the missing count and depress scores unfairly. Define a staple list (salt, pepper, olive oil, butter, garlic, onion, flour, sugar, water, vinegar, etc.) and exclude them from the scoring denominator and missing list.
