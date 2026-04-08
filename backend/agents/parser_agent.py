"""Parser Agent — extracts and normalises ingredients from freeform user input.

Calls the LLM with a strict system prompt that instructs it to return a JSON
array of normalised ingredient strings.  The raw LLM response is parsed with
``json.loads()``; a single retry is attempted after stripping markdown fences
before the run is declared a failure.

On success the normalised list is written to ``state["parsed_ingredients"]``
and persisted to the Pantry MCP server so later agents can retrieve it by
session ID without re-parsing.

MCP tools used:
    pantry://save_pantry  — persist the parsed ingredient list for the session.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from backend.agents.base import BaseAgent
from backend.graph import AgentState

# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _load_prompt(filename: str) -> str:
    """Read a prompt file from the prompts directory.

    Args:
        filename: Filename relative to ``backend/prompts/``.

    Returns:
        File contents as a stripped string.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    path = _PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# MCP client configuration
# ---------------------------------------------------------------------------

_PANTRY_SERVER_SCRIPT = str(
    Path(__file__).resolve().parents[1] / "mcp_servers" / "pantry_server.py"
)

_MCP_CONFIG: dict = {
    "pantry": {
        "command": sys.executable,
        "args": [_PANTRY_SERVER_SCRIPT],
        "transport": "stdio",
    }
}


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ParserAgent(BaseAgent):
    """Extracts a normalised ingredient list from the user's freeform input.

    Uses the LLM with ``temperature=0.0`` for deterministic, reproducible
    extraction.  The system prompt enforces a strict JSON-array-only output
    contract; this class handles the two-stage parse/retry logic and pantry
    persistence.

    Attributes:
        _system_prompt: Contents of ``backend/prompts/parser_system.txt``.
    """

    def __init__(self) -> None:
        super().__init__(temperature=0.0)
        self._system_prompt: str = _load_prompt("parser_system.txt")

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Return the agent identifier.

        Returns:
            ``"parser_agent"``
        """
        return "parser_agent"

    async def run(self, state: AgentState) -> AgentState:
        """Extract ingredients from ``state["raw_input"]`` and persist them.

        Steps:

        1. Emit a start log with session context.
        2. Invoke the LLM with the parser system prompt and raw user input.
        3. Attempt ``json.loads()`` on the raw response content.
        4. On ``JSONDecodeError``: strip markdown fences and retry once.
        5. On second failure: set ``state["parse_error"]`` and
           ``state["parsed_ingredients"] = []``; skip pantry save.
        6. On success: write ``state["parsed_ingredients"]``, call
           ``pantry://save_pantry``, set ``state["current_step"] = "searching"``.
        7. Emit an end log with duration.

        Args:
            state: Shared pipeline state.  Reads ``raw_input`` and
                ``session_id``; writes ``parsed_ingredients``, ``parse_error``,
                and ``current_step``.

        Returns:
            Updated ``AgentState``.
        """
        start = self._now_ms()
        self._log_start(state)

        try:
            # --- LLM call ---
            messages = [
                SystemMessage(content=self._system_prompt),
                HumanMessage(content=state["raw_input"]),
            ]
            response = await self.model.ainvoke(messages)
            raw: str = response.content if hasattr(response, "content") else str(response)

            # --- Parse: first attempt ---
            parsed: list[str] = _try_parse(raw)

            if parsed is None:
                # --- Parse: retry after stripping markdown fences ---
                cleaned = _strip_fences(raw)
                parsed = _try_parse(cleaned)

            if parsed is None:
                state["parse_error"] = (
                    f"LLM returned non-JSON response after retry: {raw[:200]!r}"
                )
                state["parsed_ingredients"] = []
                return state

            # --- Persist to pantry MCP server ---
            session_id: str = state["session_id"]
            mcp_client = MultiServerMCPClient(_MCP_CONFIG)
            async with mcp_client.session("pantry") as session:
                tools = await load_mcp_tools(session)
                save_tool = next((t for t in tools if t.name == "save_pantry"), None)
                if save_tool:
                    await save_tool.ainvoke(
                        {"session_id": session_id, "ingredients": parsed}
                    )

            # --- Write success fields ---
            state["parsed_ingredients"] = parsed
            state["parse_error"] = None
            state["current_step"] = "searching"

        except Exception as exc:
            state["parse_error"] = f"{type(exc).__name__}: {exc}"
            state["parsed_ingredients"] = []

        finally:
            self._log_end(state, self._now_ms() - start)

        return state


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------


def _try_parse(text: str) -> list[str] | None:
    """Attempt to parse ``text`` as a JSON array of strings.

    Args:
        text: String to parse.

    Returns:
        The parsed list if ``text`` is a valid JSON array of strings,
        otherwise ``None``.
    """
    try:
        value = json.loads(text.strip())
        if isinstance(value, list) and all(isinstance(i, str) for i in value):
            return value
    except json.JSONDecodeError:
        pass
    return None


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from an LLM response.

    Handles both ` ```json ... ``` ` and bare ` ``` ... ``` ` patterns.

    Args:
        text: Raw LLM response that may contain markdown fences.

    Returns:
        The inner content with fences removed, stripped of leading/trailing
        whitespace.
    """
    stripped = text.strip()
    for prefix in ("```json", "```"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
            break
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    return stripped.strip()
