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

## Session memory
- Use the project-memory skill at `.claude/skills/project-memory/`
- On session start: read progress.md, context.md, todo.md
- On session end: update progress.md with "Resume here" line, mark completed todos
- Log architecture decisions in decisions.md using ADR format
- Log bugs in bugs.md with root cause and fix

## Key references
- `AGENTS.md` — full agent roles, tool access, state contracts, behavioral rules
- `backend/agents/agents.md` — Python implementation details, test patterns
- `.env.example` — all 18+ environment variables documented
