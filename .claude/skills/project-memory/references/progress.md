# Progress — Pantry-to-Plate

---

## ▶ RESUME HERE

**Last session ended:** 2026-04-07
**Stopped at:** All backlog and gap items completed. 197 tests passing, 87% coverage, 0 ruff errors.

**Next action:**
- Docker: manual install WSL2 (`wsl --install`, reboot) + Docker Desktop (`winget install Docker.DockerDesktop`), then `docker compose up --build`
- GitHub Actions: add integration test job (requires API key secrets in repo settings)
- Open question: consider merging develop → main via PR once the above are tested

**Known state:**
- 197 tests: 183 unit + 14 integration, 2 skipped (live graph tests, need real API key)
- Pantry store: SQLite (`data/pantry.db`), `PANTRY_DB_PATH=:memory:` in tests
- `GET /pantry` and `DELETE /pantry` read/write SQLite directly (not MemorySaver)
- `POST /search` has 120s timeout (`SEARCH_TIMEOUT_SECONDS`), max 2000 char input, min 1 char session_id
- Frontend: ingredient pills capped at 30, filter state persisted to localStorage
- `test_graph.py` skip guard: skips if key is missing OR starts with `"test-"`
- All backlog items except Docker test and GitHub Actions integration job are done

> Note: `D:\GenAI Workspace\Work Files\` is retired — do not read those files.
> Canonical memory lives in `.claude/skills/project-memory/references/`.

---

## Session Log

### 2026-04-07 — Session 10 (Backlog + Gap fixes)

**Completed:**

**Persistent pantry (SQLite):**
- Replaced `_store` dict in `pantry_server.py` with `sqlite3` connection
- DB at `data/pantry.db` (configurable via `PANTRY_DB_PATH`; tests use `:memory:`)
- `GET /pantry` and `DELETE /pantry` in `main.py` now call `_db_get_pantry` / `_db_clear_pantry` directly instead of reading MemorySaver checkpoint (ADR-005 superseded by ADR-008)
- Updated `tests/conftest.py` to set `PANTRY_DB_PATH=:memory:` before any imports
- Updated pantry tests: replaced `_store.clear()` fixture with `DELETE FROM pantry` via `_conn`
- Added `data/.gitkeep`; `data/*.db` excluded from git

**Gap fixes — backend:**
- `run_tags: None` added to initial `AgentState` in `_search_generator`
- `session_id` validated `min_length=1, max_length=128` on `POST /search`
- `raw_input` validated `max_length=2000` (added earlier, confirmed working)
- `asyncio.timeout(_SEARCH_TIMEOUT)` wraps `graph.astream` loop; emits error SSE event on expiry
- `TimeoutError` caught explicitly before generic `Exception` in generator
- `SEARCH_TIMEOUT_SECONDS` env var (default 120) added to `.env.example`

**Gap fixes — frontend:**
- Ingredient pills capped at `MAX_PILLS=30`; count label shows "limit reached" when at cap
- Filter state (cuisine, dietary, cook-time) persisted to `localStorage` via `saveFilters()` / `restoreFilters()`
- `restoreFilters()` called at page load alongside `restorePantry()` and `checkServerHealth()`

**Bug fixes:**
- `test_graph.py` skip guard now also skips when `ANTHROPIC_API_KEY` starts with `"test-"` (conftest fallback was bypassing the guard, causing 401 errors in CI)
- `GET /pantry` was reading in-memory MemorySaver (lost on restart) instead of SQLite — fixed
- `DELETE /pantry` was clearing MemorySaver instead of SQLite — fixed

**Integration tests updated:**
- Rewrote `TestPantryGetEndpoint` and `TestPantryDeleteEndpoint` to use SQLite directly
- Added `clear_pantry_db` autouse fixture (DELETE FROM pantry between tests)
- Added: `test_search_empty_session_id_returns_422`, `test_search_timeout_emits_error_event`, `test_delete_pantry_removes_data`

**Commits:**
- `8aa23ed` — Persist pantry across sessions via SQLite
- `ca4a68c` — Fix pantry API endpoints and minor state gaps
- `c4eaa2c` — Fix remaining gaps: timeout, validation, pill cap, filter persistence

**Decisions:** ADR-007, ADR-008, ADR-009 added to `decisions.md`
**Bugs:** BUG-007 added to `bugs.md`

**Blockers:** None

---

### 2026-03-31 — Session 9 (Phase 8 — Testing)

**Completed:**
- Created `pytest.ini` with `asyncio_mode = auto`, `asyncio_default_fixture_loop_scope = function`, `integration` mark registered
- Created `tests/conftest.py`: sets fallback env vars; imports `backend.graph` to pre-populate module cache and avoid circular import errors when individual agent modules are imported in tests
- `tests/unit/test_ingredient_matcher.py` — 46 tests; 100% coverage of `normalize`, `is_duplicate`, `is_staple`, `score_ingredient_match`
- `tests/unit/test_parser_agent.py` — 16 tests; covers `_try_parse`, `_strip_fences`, and `ParserAgent.run()` (mocked LLM + MCP)
- `tests/unit/test_search_agent.py` — 38 tests; covers all pure helpers + `SearchAgent.run()` (patched `_search_tavily`/`_search_spoonacular`)
- `tests/unit/test_scorer_agent.py` — 17 tests; covers `_extract_text` + `ScorerAgent.run()` (patched `_log_to_langsmith`)
- `tests/unit/test_mcp_servers.py` — 27 tests; covers all four MCP servers
- `tests/unit/test_mcp_manager.py` — 17 tests
- `tests/integration/test_api.py` — 14 tests (updated this session)
- `tests/integration/test_graph.py` — 2 live tests with skip guard
- Final result: 197 tests passing, 2 skipped, 0 ruff errors

**Blockers:** None
