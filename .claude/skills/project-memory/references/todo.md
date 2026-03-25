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

- [ ] Write `backend/requirements.txt` with pinned versions
- [ ] Write `backend/utils/logging.py` (structured logging setup)
- [ ] Write `backend/utils/session.py` (session ID generation + storage helpers)

---

## Phase 3 — MCP Servers

- [ ] `backend/mcp_servers/pantry_server.py` — in-memory ingredient store per session
- [ ] `backend/mcp_servers/tavily_server.py` — Tavily web search wrapper
- [ ] `backend/mcp_servers/spoonacular_server.py` — Spoonacular API wrapper
- [ ] `backend/mcp_servers/langsmith_server.py` — trace logging helpers
- [ ] Unit tests for each MCP server in `tests/unit/`

---

## Phase 4 — Agents

- [ ] `backend/agents/base.py` — `BaseAgent` ABC (model client, prompt loading)
- [ ] `backend/prompts/parser_system.txt` — Parser Agent system prompt
- [ ] `backend/agents/parser_agent.py` — ingredient extraction
- [ ] `backend/prompts/search_system.txt` — Search Agent system prompt
- [ ] `backend/agents/search_agent.py` — parallel Tavily + Spoonacular search
- [ ] `backend/agents/scorer_agent.py` — fuzzy match scoring + deduplication
- [ ] `backend/tools/ingredient_matcher.py` — fuzzy matching utility
- [ ] Unit tests for each agent in `tests/unit/`

---

## Phase 5 — LangGraph Orchestration

- [ ] `backend/graph.py` — `StateGraph` wiring Parser → Search → Scorer
- [ ] Define `GraphState` TypedDict
- [ ] Wire `MemorySaver` checkpointer
- [ ] Integration test: full graph run with mocked MCP tools

---

## Phase 6 — FastAPI Gateway

- [ ] `backend/main.py` — FastAPI app, lifespan (MCP startup/shutdown), CORS
- [ ] `POST /search` endpoint — accepts ingredient text, streams SSE
- [ ] `GET /health` endpoint
- [ ] SSE streaming of partial results and final ranked list
- [ ] Integration tests for API endpoints

---

## Phase 7 — Frontend

- [ ] `frontend/index.html` — ingredient input form
- [ ] SSE consumption and live result rendering
- [ ] "View agent trace" link using LangSmith run URL
- [ ] Error state and loading indicator

---

## Phase 8 — Testing & Polish

- [ ] Fill `tests/integration/` with end-to-end graph + API tests
- [ ] Add `pytest.ini` or `pyproject.toml` with asyncio mode config
- [ ] Reach ≥ 80 % unit test coverage on `backend/`
- [ ] Write `docs/architecture.md`
- [ ] Final `ruff` + manual review pass

---

## Backlog / Nice-to-Have

- [ ] Docker Compose for local development
- [ ] GitHub Actions: add integration test job (requires secrets)
- [ ] Rate-limit handling for Spoonacular free tier
- [ ] Ingredient quantity parsing (e.g. "2 cups of flour")
- [ ] Persistent pantry across sessions (replace in-memory store)
