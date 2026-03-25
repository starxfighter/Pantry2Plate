# agents.md — Backend Agent Implementation Guide

> This document supplements the root [AGENTS.md](../AGENTS.md) with Python-specific
> implementation details, class interfaces, prompt contracts, and testing guidance
> for each agent. Read AGENTS.md first for the full system overview.

---

## BaseAgent interface

**File:** `backend/agents/base.py`

All agents must inherit from `BaseAgent` and implement `async def run(state)`.

```python
from abc import ABC, abstractmethod
from backend.graph import AgentState

class BaseAgent(ABC):
    """
    Base class for all Pantry-to-Plate agents.

    Subclasses must:
    - Set self.name to a unique string identifier
    - Set self.model to the ChatAnthropic instance
    - Implement async def run(self, state: AgentState) -> AgentState
    - Never raise exceptions — catch all errors and write to state error fields
    """
    name: str
    model: object  # ChatAnthropic

    @abstractmethod
    async def run(self, state: AgentState) -> AgentState:
        """Execute the agent's logic and return the updated state."""
        ...

    def _log_start(self, state: AgentState) -> None:
        """Emit a structured log entry when the agent begins."""
        ...

    def _log_end(self, state: AgentState, duration_ms: float) -> None:
        """Emit a structured log entry when the agent completes."""
        ...
```

---

## Parser Agent implementation notes

**File:** `backend/agents/parser_agent.py`

The Parser Agent is the simplest agent in the graph. It makes a single LLM call
with a tightly constrained system prompt, then validates the output is a JSON array
before writing to state.

Key implementation decisions:
- Uses `temperature=0.0` to ensure reproducible ingredient extraction.
- The system prompt in `backend/prompts/parser_system.txt` must instruct the model
  to return only a JSON array — no prose, no markdown fences.
- After the LLM call, parse the JSON response using `json.loads()`. If parsing fails,
  attempt to strip common prefixes (` ```json `, ` ``` `) and retry once.
- If the second parse attempt also fails, set `parse_error` and return an empty list.
- Call `pantry://save_pantry` only after a successful parse.

MCP tool binding pattern:
```python
from langchain_mcp_adapters.client import MultiServerMCPClient

async with MultiServerMCPClient(mcp_config) as client:
    tools = await client.get_tools()
    pantry_tools = [t for t in tools if t.name.startswith("pantry_")]
    agent = model.bind_tools(pantry_tools)
    response = await agent.ainvoke([SystemMessage(...), HumanMessage(...)])
```

---

## Search Agent implementation notes

**File:** `backend/agents/search_agent.py`

The Search Agent is the most complex. It must run two external searches concurrently
and merge the results.

Concurrency pattern:
```python
import asyncio

tavily_task = asyncio.create_task(self._search_tavily(state))
spoonacular_task = asyncio.create_task(self._search_spoonacular(state))
tavily_results, spoonacular_results = await asyncio.gather(
    tavily_task, spoonacular_task, return_exceptions=True
)
```

If either task raises an exception (returned as the result due to `return_exceptions=True`),
log the error and continue with whatever results the other source returned. Only set
`search_error` if both sources fail.

Deduplication: use the `rapidfuzz` library for fuzzy URL and name matching.
```python
from rapidfuzz import fuzz
def is_duplicate(a: str, b: str, threshold: int = 85) -> bool:
    return fuzz.ratio(a.lower(), b.lower()) >= threshold
```

Recipe page fetch: the Search Agent calls `tavily://fetch_recipe_page(url)` for each
Tavily hit to extract the full ingredient list. This can be done concurrently too:
```python
pages = await asyncio.gather(*[
    client.call_tool("fetch_recipe_page", {"url": r["url"]})
    for r in tavily_hits
], return_exceptions=True)
```

Filter application: apply `state["filters"]` after merging, not before.
This maximizes the number of candidates before the scorer ranks them.

---

## Scorer Agent implementation notes

**File:** `backend/agents/scorer_agent.py`

The Scorer Agent is intentionally mostly non-LLM. The match scoring is pure Python.
The LLM is invoked only if a recipe's `dietary_tags` list is empty and inference is needed.

Ingredient normalization before matching:
```python
import re

def normalize(ingredient: str) -> str:
    ingredient = ingredient.lower().strip()
    ingredient = re.sub(r'\b(fresh|dried|chopped|minced|sliced|diced)\b', '', ingredient)
    ingredient = re.sub(r'\s+', ' ', ingredient).strip()
    return ingredient
```

Scoring loop (deterministic, no LLM):
```python
from rapidfuzz import process, fuzz

def score_recipe(recipe: RecipeCandidate, pantry: list[str]) -> ScoredRecipe:
    norm_pantry = [normalize(i) for i in pantry]
    have, missing = [], []
    for ingredient in recipe["ingredient_list"]:
        norm_ing = normalize(ingredient)
        match = process.extractOne(norm_ing, norm_pantry, scorer=fuzz.ratio)
        if match and match[1] >= INGREDIENT_MATCH_THRESHOLD:
            have.append(ingredient)
        else:
            missing.append(ingredient)
    score = len(have) / len(recipe["ingredient_list"]) * 100 if recipe["ingredient_list"] else 0.0
    return ScoredRecipe(match_score=score, ingredients_have=have, ingredients_missing=missing, ...)
```

LangSmith logging: always call `langsmith://log_search_run` in a `try/except`.
If the log call fails, continue — do not let observability failure break the user experience.

---

## Prompt files

**`backend/prompts/parser_system.txt`** — Parser Agent system prompt.
Contains: role definition, output format rules, normalization rules, edge case handling.
Must end with an explicit instruction like:
> "Return only a JSON array of strings. No other text. No markdown. No explanation."

**`backend/prompts/search_system.txt`** — Search Agent system prompt.
Contains: role definition, search strategy, how to construct effective queries from
ingredient lists, how to handle ambiguous results, output format for recipe candidates.

Prompts are loaded at agent instantiation time:
```python
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

class ParserAgent(BaseAgent):
    def __init__(self):
        self.system_prompt = (PROMPTS_DIR / "parser_system.txt").read_text()
```

Never hardcode prompt text in agent Python files.

---

## State field ownership quick reference

| Field | Written by | Read by |
|---|---|---|
| `session_id` | Gateway (main.py) | All agents |
| `raw_input` | Gateway | Parser |
| `filters` | Gateway | Search, Scorer |
| `parsed_ingredients` | Parser | Search, Scorer |
| `parse_error` | Parser | Graph router |
| `search_results` | Search | Scorer |
| `search_error` | Search | Graph router |
| `scored_recipes` | Scorer | Gateway (returned to UI) |
| `langsmith_run_url` | Scorer | Gateway (returned to UI) |
| `current_step` | Each agent (on entry) | SSE emitter in Gateway |
| `start_time` | Graph (on start) | Scorer (for latency calc) |

---

## Testing each agent

Unit tests live in `tests/unit/`. Each agent should have its own test file.

Pattern for testing an agent in isolation:
```python
import pytest
from unittest.mock import AsyncMock, patch
from backend.agents.parser_agent import ParserAgent
from backend.graph import AgentState

@pytest.fixture
def base_state() -> AgentState:
    return AgentState(
        session_id="test-session",
        raw_input="I have eggs, cheddar, and leftover chicken",
        filters={},
        parsed_ingredients=[],
        parse_error=None,
        search_results=[],
        search_error=None,
        scored_recipes=[],
        langsmith_run_url=None,
        current_step="parsing",
        start_time=0.0,
    )

@pytest.mark.asyncio
async def test_parser_extracts_ingredients(base_state):
    agent = ParserAgent()
    with patch.object(agent, "_call_llm", return_value='["eggs", "cheddar", "chicken"]'):
        result = await agent.run(base_state)
    assert result["parsed_ingredients"] == ["eggs", "cheddar", "chicken"]
    assert result["parse_error"] is None

@pytest.mark.asyncio
async def test_parser_sets_error_on_bad_input(base_state):
    base_state["raw_input"] = "asdf"
    agent = ParserAgent()
    with patch.object(agent, "_call_llm", return_value="not json"):
        result = await agent.run(base_state)
    assert result["parse_error"] is not None
    assert result["parsed_ingredients"] == []
```

---

## Environment variables consumed by agents

| Variable | Agent | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | All | LLM authentication |
| `ANTHROPIC_MODEL` | All | Model name |
| `TAVILY_API_KEY` | Search | Tavily API auth |
| `TAVILY_MAX_RESULTS` | Search | Caps Tavily result count |
| `SPOONACULAR_API_KEY` | Search | Spoonacular API auth |
| `SPOONACULAR_MAX_RESULTS` | Search | Caps Spoonacular result count |
| `LANGSMITH_API_KEY` | Scorer | LangSmith auth |
| `LANGSMITH_PROJECT` | All (auto) | LangSmith project |
| `LANGCHAIN_TRACING_V2` | All (auto) | Enable/disable tracing |
| `INGREDIENT_MATCH_THRESHOLD` | Scorer | Fuzzy match threshold |
| `RECIPE_DEDUP_THRESHOLD` | Search | Dedup fuzzy threshold |
| `MAX_RECIPE_RESULTS` | Search | Max candidates to return |
| `TOP_RECIPE_COUNT` | Scorer | Top N results to surface |
