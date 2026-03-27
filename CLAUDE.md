# Pantry-to-Plate — Project CLAUDE.md

## Architecture
- LangGraph StateGraph orchestrating 3 agents: Parser, Search, Scorer
- 4 FastMCP servers (stdio): Pantry Store, Tavily Search, Spoonacular, LangSmith
- FastAPI gateway with SSE streaming on POST /search
- Single-file HTML frontend (no build tools, no npm for frontend)
- All agents share a typed AgentState; communicate only through state fields
- MemorySaver checkpointer keyed by session_id

## Tech stack
- Python 3.11, LangGraph, langchain-anthropic, FastMCP, FastAPI, uvicorn
- Tavily (web search), Spoonacular (recipe DB), LangSmith (observability)
- rapidfuzz (ingredient matching + dedup)
- Frontend: vanilla HTML/CSS/JS, Playfair Display + Lato fonts
- Model: claude-sonnet-4-20250514

## Directory layout
```
pantry-to-plate/
├── backend/
│   ├── agents/          # One file per agent + base.py
│   ├── mcp_servers/     # One file per MCP server
│   ├── prompts/         # .txt prompt files loaded at init
│   ├── tools/           # ingredient_matcher.py, shared utils
│   ├── utils/           # logging, mcp_manager, smoke_test
│   ├── graph.py         # AgentState, StateGraph, compile_graph()
│   └── main.py          # FastAPI app + lifespan
├── frontend/
│   └── index.html       # Single-file UI
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── .claude/skills/project-memory/   # Session memory skill
├── AGENTS.md            # Global agent reference
├── CLAUDE.md            # This file
├── .env.example
└── .github/workflows/ci.yml
```

## Conventions
- Use type hints on all Python functions and variables
- Use functional React patterns only (no class components)
- Define each LangGraph agent node in its own file under backend/agents/
- Define each MCP tool in its own server file under backend/mcp_servers/
- Load prompt text from backend/prompts/*.txt — never hardcode in agent files
- Wrap all external calls (LLM + MCP) in try/except with structured logging
- Commit messages: imperative mood, e.g. "Add ingredient parser tool"

## Commands
- Install deps: `pip install -r backend/requirements.txt`
- Run server: `uvicorn backend.main:app --reload --port 8000`
- Run unit tests: `pytest tests/unit/ -v`
- Run integration tests: `pytest tests/integration/ -v -m integration`
- Lint: `ruff check backend/ tests/`
- Verify graph: `python -c "from backend.graph import graph; print(graph.get_graph().draw_mermaid())"`
- Smoke test APIs: `python backend/utils/smoke_test.py`
- Graph smoke test: `PYTHONPATH="D:/GenAI Workspace/Pantry2Plate" /d/anaconda3/python.exe -u backend/utils/graph_test.py`

## Session memory
- **FIRST THING every session**: read all five files below before doing anything else:
  - `.claude/skills/project-memory/references/progress.md` — resume point + session log
  - `.claude/skills/project-memory/references/context.md` — stable project facts
  - `.claude/skills/project-memory/references/todo.md` — phased task list
  - `AGENTS.md` — agent roles, state contracts, tool access, schemas
  - `docs/architecture.md` — current system architecture overview
- Summarize what was completed last session and what's next; ask user to confirm before starting
- On session end: update the following before closing:
  - `progress.md` — "Resume here" line + session log entry
  - `todo.md` — mark completed tasks, reprioritize if needed
  - `decisions.md` — add any ADRs made this session
  - `bugs.md` — log any bugs found and fixed
  - `docs/architecture.md` — reflect any structural changes made this session
- Log architecture decisions in `decisions.md` using ADR format
- Log bugs in `bugs.md` with root cause and fix
- **Do NOT read `D:\GenAI Workspace\Work Files\` — those files are stale and retired**

## Architecture documentation rules
- **Update `AGENTS.md`** whenever: an agent's state fields, MCP tools, output schema, or behavioral rules change
- **Update `docs/architecture.md`** whenever: a new component is added, a layer changes, or data flow changes
- **Update `backend/agents/agents.md`** whenever: implementation patterns, class structure, or test patterns change
- **Update `references/context.md`** whenever: a port, env var, tool version, or tech stack choice is confirmed or changed
- Never let code diverge from its documentation — update the relevant markdown in the same session the code changes

## Key references
- `AGENTS.md` — full agent roles, tool access, state contracts, behavioral rules
- `backend/agents/agents.md` — Python implementation details, test patterns
- `docs/architecture.md` — system architecture, data flow, component overview
- `docs/cross_platform.md` — changes needed to run on Linux/macOS
- `.env.example` — all 18+ environment variables documented
