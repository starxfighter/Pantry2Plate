# Project context — Pantry-to-Plate

## What this app does
A local web app where users enter ingredients they have on hand and the app
surfaces recipes they can make. Uses a multi-agent AI pipeline for parsing,
searching, and scoring. Runs entirely locally — no cloud deployment.

## Tech stack
| Layer | Technology |
|---|---|
| Frontend | Single-file HTML (vanilla JS, CSS) |
| Backend API | Python 3.11, FastAPI, uvicorn |
| Agent orchestration | LangGraph StateGraph |
| LLM | claude-sonnet-4-20250514 via langchain-anthropic |
| Tool integration | FastMCP (stdio transport), 4 servers |
| Recipe search | Tavily (web), Spoonacular (API) |
| Ingredient matching | rapidfuzz |
| Observability | LangSmith |
| Dev assistant | Claude Code CLI |

## Agents
| Agent | File | Purpose |
|---|---|---|
| Parser | backend/agents/parser_agent.py | Extract + normalize ingredients from freeform text |
| Search | backend/agents/search_agent.py | Query Tavily + Spoonacular concurrently, deduplicate |
| Scorer | backend/agents/scorer_agent.py | Score recipes by pantry match %, log to LangSmith |

## MCP servers
| Server | File | Tools |
|---|---|---|
| Pantry Store | backend/mcp_servers/pantry_server.py | save_pantry, get_pantry, clear_pantry |
| Tavily | backend/mcp_servers/tavily_server.py | web_search_recipes, fetch_recipe_page |
| Spoonacular | backend/mcp_servers/spoonacular_server.py | search_recipes_by_ingredients, get_recipe_detail |
| LangSmith | backend/mcp_servers/langsmith_server.py | log_search_run, get_run_url |

## Project structure
```
pantry-to-plate/
├── backend/{agents,mcp_servers,prompts,tools,utils}/ + graph.py + main.py
├── frontend/index.html
├── tests/{unit,integration,e2e}/
├── .claude/skills/project-memory/
├── AGENTS.md, CLAUDE.md, README.md
├── .env.example, .gitignore
└── .github/workflows/ci.yml
```

## Ports and local config
| Service | Port | Notes |
|---|---|---|
| FastAPI backend | 8000 | uvicorn --reload |
| Frontend | file:// | Open index.html directly in browser |

## Environment variables (.env)
| Variable | Purpose |
|---|---|
| ANTHROPIC_API_KEY | LLM auth |
| ANTHROPIC_MODEL | Model name (claude-sonnet-4-20250514) |
| TAVILY_API_KEY | Tavily search auth |
| SPOONACULAR_API_KEY | Spoonacular API auth |
| LANGSMITH_API_KEY | LangSmith auth |
| LANGSMITH_PROJECT | pantry-to-plate |
| LANGCHAIN_TRACING_V2 | true to enable tracing |
| APP_HOST / APP_PORT | FastAPI host/port |
| CORS_ORIGINS | Allowed origins (comma-separated) |
| INGREDIENT_MATCH_THRESHOLD | Fuzzy match threshold (default 80) |
| RECIPE_DEDUP_THRESHOLD | Dedup threshold (default 85) |
| MAX_RECIPE_RESULTS | Max candidates from search (default 15) |
| TOP_RECIPE_COUNT | Top N scored results (default 10) |

## Coding conventions
- Python: type hints throughout, async/await for I/O
- Frontend: vanilla JS, no frameworks, no build tools
- Agents: one file per agent inheriting BaseAgent
- MCP servers: one file per server using FastMCP
- Prompts: load from backend/prompts/*.txt, never hardcode
- Commit messages: imperative mood

## Key commands
- Install: `pip install -r backend/requirements.txt`
- Run: `uvicorn backend.main:app --reload --port 8000`
- Test: `pytest tests/unit/ -v`
- Lint: `ruff check backend/ tests/`

---
_Last updated: 2026-03-25_
