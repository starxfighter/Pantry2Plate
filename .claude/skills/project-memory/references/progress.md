# Progress — Pantry-to-Plate

---

## ▶ RESUME HERE

**Last session ended:** 2026-03-27
**Stopped at:** Session 7 complete. Bug fixes pushed to `develop`. Spoonacular free-tier quota
exhausted during debugging — **re-test the full pipeline first** before continuing Phase 8.

**Next action (immediate):** Re-test with fresh Spoonacular quota:
- Run a search with 4+ ingredients and confirm 10 recipes returned
- Confirm LangSmith trace link appears in the UI

**Next action (Phase 8):**
- `pytest.ini` / `pyproject.toml` with asyncio mode config
- Unit tests for each agent in `tests/unit/`
- Unit tests for each MCP server in `tests/unit/`
- Integration test: full graph run with mocked MCP tools
- Integration tests for API endpoints (`POST /search`, `GET /health`, `GET /pantry`, `DELETE /pantry`)
- Reach ≥ 80% unit test coverage on `backend/`
- Final `ruff` pass

**Queued UI polish (after Phase 8):**
- Yellow chips for spices/herbs/staples (currently shown as red "missing")
- Scorer should exclude staples from match scoring denominator

> Note: `D:\GenAI Workspace\Work Files\` is retired — do not read those files.
> Canonical memory lives in `.claude/skills/project-memory/references/`.

---

## Session Log

### 2026-03-25 — Session 1

**Completed:**
- Created full project directory structure from README spec
- Added `__init__.py` to all Python backend packages
- Added `.gitkeep` to empty test subdirectories
- Wrote `.env.example` with all 19 env vars across 7 sections
- Wrote `.gitignore` for Python + HTML project
- Wrote `.github/workflows/ci.yml` (lint + unit test + coverage upload)
- Created `.claude/skills/project-memory/` system (this file)

**Decisions made:** None (pure scaffolding, no architectural choices yet)

**Blockers:** None

---

### 2026-03-27 — Session 7

**Completed:**
- Fixed LangSmith trace link not showing (BUG-005, BUG-006):
  - Root cause: `POST /runs` returns 202 Accepted (async); immediate `PUT /share` got 404
  - Fix: consolidated share call into `log_search_run` with 3-retry / 2s-delay loop; `get_run_url` now just constructs URL string from share token
- Fixed critical recipe count bug (BUG-004):
  - Root cause: `langchain-mcp-adapters` wraps ALL tool results as TextContent dicts `{"type":"text","text":"<json>"}` — not just `str` tools
  - In `_search_spoonacular`, `c.get("id")` on TextContent returned None → ALL Spoonacular candidates silently skipped (0 recipes from Spoonacular)
  - In `_search_tavily`, TextContent wrappers were JSON-serialized to LLM instead of actual search content
  - Fix: added `_unwrap_tool_list()` helper in `search_agent.py`; applied to all 4 tool call sites
- Increased `_DEFAULT_MAX_RESULTS` from 15 to 20 and Tavily `max_results` from 10 to 15
- Added 3 new todo items: re-test pipeline, yellow staple chips, scorer staple exclusion
- Pushed all changes to `develop` branch

**Decisions made:**
- ADR-006: Consolidated LangSmith share call into `log_search_run` to avoid eventual-consistency 404 race (see decisions.md)

**Blockers:**
- Spoonacular free-tier quota exhausted during debugging session; re-test tomorrow

---

### 2026-03-27 — Session 6

**Completed:**
- Resolved Malwarebytes false-positive on `uv` executables — confirmed not used in project, not installed in Anaconda; flagged files were in `C:\Users\User\bin` and `AppData\Local\Temp`, quarantined by Malwarebytes
- Added `GET /pantry/{session_id}` and `DELETE /pantry/{session_id}` to `backend/main.py`
  - Discovered pantry MCP subprocess is ephemeral (dies after parser agent's `async with` exits)
  - Correct data source is LangGraph MemorySaver checkpoint; endpoints use `graph.aget_state` / `graph.aupdate_state`
- Created `backend/utils/log_config.py` — `get_logger(name)` returns JSON-structured logger; reads `LOG_LEVEL` env var; emits `timestamp`, `level`, `name`, `message`, optional `session_id`/`current_step`/`duration_ms` from `extra={}`
- Updated `backend/main.py` to use `get_logger(__name__)` — removed `_LOG_CONFIG` dict and `dictConfig` call; uvicorn access log silenced with one-liner
- Confirmed end-to-end pipeline via `curl`: 5 ranked recipes returned, LangSmith trace URL present, 4 SSE events (searching, scoring, done message, done event)
- Implemented `frontend/index.html` (Phase 7 complete):
  - CSS design tokens, Playfair Display + Lato fonts, 960px centered layout
  - Textarea with comma/blur → ingredient pill parsing; X to remove; "N ingredients detected" count
  - Session ID generated with `crypto.randomUUID()`, persisted in localStorage
  - Filter bar: cuisine toggle pills, dietary checkboxes, cook time slider (0–120 min)
  - 4-step horizontal stepper with pulse animation (active) and fill animation (complete); collapses after results render
  - Error state card with retry button wired to `searchRecipes()`
  - SSE consumed via `fetch` + `ReadableStream` (EventSource is GET-only)
  - Recipe cards: match % badge, cuisine/time/source meta, dietary tags, ingredient chips (have/missing), steps summary, full recipe link
  - "View agent trace ↗" LangSmith link (hidden until `done` SSE event)

**Decisions made:**
- ADR-005: Pantry REST endpoints read from LangGraph checkpoint, not MCP (see decisions.md)

**Blockers:** None

---

### 2026-03-27 — Session 5

**Completed:**
- Implemented `backend/main.py` — Phase 6 done:
  - `asynccontextmanager` lifespan with `MCPServerManager` start/stop
  - `CORSMiddleware` reading `CORS_ORIGINS` env var
  - JSON-structured logging config; uvicorn access logs silenced
  - `GET /health` — returns `status` + `mcp_servers_running`
  - `SearchRequest` Pydantic model (`raw_input`, `filters`, `session_id`)
  - `POST /search` — `EventSourceResponse` streaming `graph.astream` chunks
  - SSE events: `message` per node (`step` + `data`), `done` with LangSmith URL, `error` on exception
- Fixed conda init "Did not find path entry" warning — added `2>/dev/null` to eval in `~/.bash_profile`

**Decisions made:** None (implementation followed existing ADRs)

**Blockers:** None

---

### 2026-03-26 — Session 4

**Completed:**
- Implemented all 4 MCP servers (pantry, tavily, spoonacular, langsmith) — Phase 3 done
- Implemented BaseAgent, ParserAgent, SearchAgent, ScorerAgent — Phase 4 done
- Implemented ingredient_matcher.py (rapidfuzz), graph.py with LangGraph StateGraph — Phase 5 done
- Implemented MCPServerManager (backend/utils/mcp_manager.py)
- Wrote and ran backend/utils/graph_test.py — all assertions pass
- Fixed Windows ProactorEventLoop IOCP hang: `await asyncio.sleep(0)` between sessions
- Fixed LangSmith MCP response parsing: `langchain-mcp-adapters` returns `[{'type':'text','text':...}]` not `str`; added `_extract_text()` helper in scorer_agent.py
- Fixed LangSmith server: replaced `langsmith.Client` (spawns background threads that block stdio) with direct `httpx.Client` POST to the REST API
- Created `docs/` folder with `architecture.md` and `cross_platform.md`

**Decisions made:**
- ADR-003: Direct httpx over langsmith.Client in the MCP server (thread isolation)
- ADR-004: Sequential Spoonacular detail fetches (not concurrent) to avoid IOCP hang

**Blockers:** None

---

### 2026-03-26 — Session 3

**Completed:**
- Fixed memory skill so future sessions load correct state on start
- Added "resume" and related trigger words to SKILL.md
- Strengthened CLAUDE.md session-start instructions to read skill references first
- Retired stale `Work Files/` — canonical memory is now solely in `references/`

**Decisions made:** None

**Blockers:** None

---

### 2026-03-25 — Session 2

**Completed:**
- Installed `gh` CLI and created PR #1 (develop → main)
- Fixed CI failure: added `tests/unit/test_placeholder.py` (pytest exits code 5 on no tests)
- Fixed `.gitignore`: added `!.env.example` to un-ignore the template file
- Installed all dependencies from `backend/requirements.txt` into Anaconda environment
- Renamed `backend/utils/logging.py` → `backend/utils/log_config.py` (shadowed stdlib `logging`)
- Created `.env` from `.env.example` and populated all API keys
- Wrote and ran `backend/utils/smoke_test.py` — all 4 APIs passing
- Verified LangSmith trace appears in `pantry-to-plate` project
- Resolved Anaconda `bin` folder warning (created `D:\anaconda3\bin`)
- Added `python` and `pip` aliases to `~/.bash_profile`
- Added plan-before-code rule to `~/.claude/CLAUDE.md`
- Pushed environment setup commit to `develop`

**Decisions made:** None beyond prior ADRs

**Blockers:** None
