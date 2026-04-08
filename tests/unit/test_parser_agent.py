"""Unit tests for backend/agents/parser_agent.py.

Tests the pure helpers (_try_parse, _strip_fences) and ParserAgent.run()
with all LLM and MCP calls mocked out.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# asyncio_mode = auto in pytest.ini makes @pytest.mark.asyncio optional, but
# we apply it explicitly here as required project spec for this test module.

from backend.agents.parser_agent import ParserAgent, _strip_fences, _try_parse
from backend.graph import AgentState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state() -> AgentState:
    return AgentState(
        session_id="test-session",
        raw_input="I have chicken, garlic, and lemon",
        filters={},
        parsed_ingredients=[],
        parse_error=None,
        search_results=[],
        search_error=None,
        tavily_recipe_count=0,
        spoonacular_recipe_count=0,
        scored_recipes=[],
        langsmith_run_url=None,
        current_step="parsing",
        start_time=0.0,
    )


def _make_mcp_patch(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch MultiServerMCPClient + load_mcp_tools so no subprocess is spawned.

    Returns:
        The mock ``save_pantry`` tool so callers can assert on its invocations.
    """
    mock_tool = MagicMock()
    mock_tool.name = "save_pantry"
    mock_tool.ainvoke = AsyncMock(return_value="ok")

    mock_session = MagicMock()

    async def fake_load_tools(session):  # noqa: ANN001
        return [mock_tool]

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.session.return_value = mock_cm

    monkeypatch.setattr(
        "backend.agents.parser_agent.MultiServerMCPClient",
        lambda *a, **kw: mock_client,
    )
    monkeypatch.setattr(
        "backend.agents.parser_agent.load_mcp_tools",
        fake_load_tools,
    )
    return mock_tool


# ---------------------------------------------------------------------------
# _try_parse
# ---------------------------------------------------------------------------


class TestTryParse:
    def test_valid_json_array(self) -> None:
        assert _try_parse('["chicken", "garlic"]') == ["chicken", "garlic"]

    def test_empty_array(self) -> None:
        assert _try_parse("[]") == []

    def test_invalid_json(self) -> None:
        assert _try_parse("not json") is None

    def test_json_object_not_list(self) -> None:
        assert _try_parse('{"key": "value"}') is None

    def test_list_with_non_string(self) -> None:
        # A list that contains non-strings should return None
        assert _try_parse('[1, 2, 3]') is None

    def test_whitespace_trimmed(self) -> None:
        assert _try_parse('  ["salt"]  ') == ["salt"]


# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------


class TestStripFences:
    def test_strips_json_fence(self) -> None:
        text = '```json\n["chicken"]\n```'
        assert _strip_fences(text) == '["chicken"]'

    def test_strips_plain_fence(self) -> None:
        text = '```\n["garlic"]\n```'
        assert _strip_fences(text) == '["garlic"]'

    def test_no_fence_unchanged(self) -> None:
        text = '["lemon"]'
        assert _strip_fences(text) == '["lemon"]'

    def test_only_closing_fence_stripped(self) -> None:
        # Only the closing fence present
        text = '["egg"]\n```'
        result = _strip_fences(text)
        assert "```" not in result

    def test_strips_whitespace(self) -> None:
        text = '  ```json\n  ["onion"]  \n```  '
        assert _strip_fences(text) == '["onion"]'


# ---------------------------------------------------------------------------
# ParserAgent.run()
# ---------------------------------------------------------------------------


class TestParserAgentRun:
    @pytest.mark.asyncio
    async def test_valid_llm_response_sets_ingredients(
        self, monkeypatch: pytest.MonkeyPatch, state: AgentState
    ) -> None:
        _make_mcp_patch(monkeypatch)
        agent = ParserAgent()

        mock_response = MagicMock()
        mock_response.content = '["chicken", "garlic", "lemon"]'
        agent.model = MagicMock()
        agent.model.ainvoke = AsyncMock(return_value=mock_response)

        result = await agent.run(state)

        assert result["parsed_ingredients"] == ["chicken", "garlic", "lemon"]
        assert result["parse_error"] is None
        assert result["current_step"] == "searching"

    @pytest.mark.asyncio
    async def test_markdown_fenced_response_is_parsed(
        self, monkeypatch: pytest.MonkeyPatch, state: AgentState
    ) -> None:
        """test_json_retry: fenced JSON is stripped and parsed on the retry path."""
        _make_mcp_patch(monkeypatch)
        agent = ParserAgent()

        mock_response = MagicMock()
        mock_response.content = '```json\n["egg", "butter"]\n```'
        agent.model = MagicMock()
        agent.model.ainvoke = AsyncMock(return_value=mock_response)

        result = await agent.run(state)

        assert result["parsed_ingredients"] == ["egg", "butter"]
        assert result["parse_error"] is None

    @pytest.mark.asyncio
    async def test_unparseable_response_sets_error(
        self, monkeypatch: pytest.MonkeyPatch, state: AgentState
    ) -> None:
        """test_bad_json_sets_error: both attempts fail → parse_error set, ingredients []."""
        _make_mcp_patch(monkeypatch)
        agent = ParserAgent()

        mock_response = MagicMock()
        mock_response.content = "Sorry, I cannot help with that."
        agent.model = MagicMock()
        agent.model.ainvoke = AsyncMock(return_value=mock_response)

        result = await agent.run(state)

        assert result["parsed_ingredients"] == []
        assert result["parse_error"] is not None
        assert "non-JSON" in result["parse_error"]

    @pytest.mark.asyncio
    async def test_llm_exception_sets_error(
        self, monkeypatch: pytest.MonkeyPatch, state: AgentState
    ) -> None:
        _make_mcp_patch(monkeypatch)
        agent = ParserAgent()

        agent.model = MagicMock()
        agent.model.ainvoke = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        result = await agent.run(state)

        assert result["parsed_ingredients"] == []
        assert result["parse_error"] is not None
        assert "RuntimeError" in result["parse_error"]

    @pytest.mark.asyncio
    async def test_empty_ingredient_list_allowed(
        self, monkeypatch: pytest.MonkeyPatch, state: AgentState
    ) -> None:
        _make_mcp_patch(monkeypatch)
        agent = ParserAgent()

        mock_response = MagicMock()
        mock_response.content = "[]"
        agent.model = MagicMock()
        agent.model.ainvoke = AsyncMock(return_value=mock_response)

        result = await agent.run(state)

        # An empty JSON array is valid — parse_error should be None
        assert result["parsed_ingredients"] == []
        assert result["parse_error"] is None

    @pytest.mark.asyncio
    async def test_empty_input_handled(
        self, monkeypatch: pytest.MonkeyPatch, state: AgentState
    ) -> None:
        """test_empty_input_handled: whitespace raw_input returns gracefully without exception."""
        state["raw_input"] = "   "
        _make_mcp_patch(monkeypatch)
        agent = ParserAgent()

        # LLM receives the whitespace string and returns an empty list.
        mock_response = MagicMock()
        mock_response.content = "[]"
        agent.model = MagicMock()
        agent.model.ainvoke = AsyncMock(return_value=mock_response)

        # Must not raise.
        result = await agent.run(state)

        assert isinstance(result, dict)
        assert result["parsed_ingredients"] == []
        assert result["parse_error"] is None

    @pytest.mark.asyncio
    async def test_pantry_save_called(
        self, monkeypatch: pytest.MonkeyPatch, state: AgentState
    ) -> None:
        """test_pantry_save_called: save_pantry MCP tool is invoked with correct args on success."""
        mock_save_tool = _make_mcp_patch(monkeypatch)
        agent = ParserAgent()

        mock_response = MagicMock()
        mock_response.content = '["chicken", "garlic"]'
        agent.model = MagicMock()
        agent.model.ainvoke = AsyncMock(return_value=mock_response)

        await agent.run(state)

        mock_save_tool.ainvoke.assert_called_once_with(
            {"session_id": "test-session", "ingredients": ["chicken", "garlic"]}
        )
