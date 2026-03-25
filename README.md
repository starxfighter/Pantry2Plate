# Pantry-to-Plate

A multi-agent AI recipe finder that helps home cooks discover recipes they can make
with ingredients already on hand. Built with Python, LangGraph, FastMCP, and FastAPI.

---

## What it does

Enter the ingredients you have — in plain language — and the system searches the web
and recipe databases to find the best matching recipes. Results are ranked by how many
of your ingredients each recipe uses, so you always see what you can make right now
before what requires a store run.

---

## Architecture

```
Browser UI (HTML/CSS/JS)
        │  HTTP POST + SSE stream
        ▼
  FastAPI Gateway
        │
        ▼
LangGraph StateGraph
  ├── Parser Agent     → extracts ingredients from freeform input
  ├── Search Agent     → queries Tavily + Spoonacular in parallel
  └── Scorer Agent     → ranks results, logs trace to LangSmith
        │
        ▼
  MCP Tool Layer
  ├── pantry_server    → session ingredient storage
  ├── tavily_server    → web recipe search
  ├── spoonacular_server → recipe database API
  └── langsmith_server → observability
```

See [AGENTS.md](./AGENTS.md) for the complete agent reference.

---

## Tech stack

| Layer | Technology |
|---|---|
| Agent orchestration | LangGraph `StateGraph` |
| Agent framework | LangChain + `langchain-anthropic` |
| LLM | Claude Sonnet (`claude-sonnet-4-20250514`) |
| MCP servers | FastMCP (Python, stdio transport) |
| Backend gateway | FastAPI + Server-Sent Events |
| Recipe search | Tavily Search API + Spoonacular API |
| Observability | LangSmith |
| Checkpointing | LangGraph `MemorySaver` |
| Frontend | Single HTML file (no build step) |

---

## Prerequisites

- Python 3.11+
- API keys for: Anthropic, Tavily, Spoonacular, LangSmith

---

## Quick start

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_ORG/pantry-to-plate.git
cd pantry-to-plate

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r backend/requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env and fill in your API keys

# 5. Start the backend
uvicorn backend.main:app --reload --port 8000

# 6. Open the frontend
open frontend/index.html            # or just open the file in your browser
```

---

## Environment variables

Copy `.env.example` to `.env` and fill in the values below.

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key |
| `TAVILY_API_KEY` | Yes | Tavily Search API key |
| `SPOONACULAR_API_KEY` | Yes | Spoonacular Recipe API key |
| `LANGSMITH_API_KEY` | Yes | LangSmith API key for tracing |
| `LANGSMITH_PROJECT` | No | LangSmith project name (default: `pantry-to-plate`) |
| `LANGCHAIN_TRACING_V2` | No | Set to `true` to enable LangSmith tracing |
| `LOG_LEVEL` | No | Logging level (default: `INFO`) |
| `MAX_RECIPE_RESULTS` | No | Max recipe candidates before scoring (default: `15`) |
| `CORS_ORIGINS` | No | Comma-separated allowed origins (default: `*`) |

---

## Project structure

```
pantry-to-plate/
├── AGENTS.md                    ← Global agent reference (read this first)
├── README.md                    ← This file
├── .env.example                 ← Environment variable template
├── .gitignore
├── backend/
│   ├── main.py                  ← FastAPI app + MCP server startup
│   ├── graph.py                 ← LangGraph StateGraph definition
│   ├── requirements.txt
│   ├── agents/
│   │   ├── base.py              ← BaseAgent class
│   │   ├── parser_agent.py      ← Ingredient extraction agent
│   │   ├── search_agent.py      ← Recipe search agent
│   │   └── scorer_agent.py      ← Match scoring and ranking agent
│   ├── mcp_servers/
│   │   ├── pantry_server.py     ← Session pantry storage MCP server
│   │   ├── tavily_server.py     ← Tavily web search MCP server
│   │   ├── spoonacular_server.py← Spoonacular API MCP server
│   │   └── langsmith_server.py  ← LangSmith observability MCP server
│   ├── prompts/
│   │   ├── parser_system.txt    ← Parser Agent system prompt
│   │   └── search_system.txt    ← Search Agent system prompt
│   ├── tools/
│   │   └── ingredient_matcher.py← Fuzzy ingredient matching utility
│   └── utils/
│       ├── logging.py
│       └── session.py
├── frontend/
│   └── index.html               ← Single-file browser UI
├── docs/
│   └── architecture.md          ← Detailed architecture notes
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── .github/
    └── workflows/
        └── ci.yml               ← GitHub Actions CI pipeline
```

---

## Running tests

```bash
# Unit tests
pytest tests/unit/ -v

# Integration tests (requires .env configured)
pytest tests/integration/ -v

# All tests with coverage
pytest --cov=backend --cov-report=html
```

---

## Viewing traces

After each search, the UI displays a "View agent trace" link that opens the LangSmith
run directly. You can also browse all runs at:
`https://smith.langchain.com/projects/pantry-to-plate`

---

## Contributing

1. Read [AGENTS.md](./AGENTS.md) before making any changes to agent logic.
2. Follow the coding conventions section in AGENTS.md.
3. All new agents must be documented in AGENTS.md.
4. Run the full test suite before opening a pull request.
5. Keep prompts in `backend/prompts/` — never hardcode system prompts in agent files.

---

## License

MIT
