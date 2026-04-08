"""Unit tests for all four MCP server modules.

Each server module is imported directly so the tool functions can be called
as plain Python functions.  All external I/O (httpx, TavilyClient) is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Pantry Server
# ---------------------------------------------------------------------------

from backend.mcp_servers.pantry_server import (  # noqa: E402
    _conn,
    clear_pantry,
    get_pantry,
    save_pantry,
)


@pytest.fixture(autouse=False)
def clear_pantry_store() -> None:
    """Ensure the pantry table is empty before and after each test."""
    _conn.execute("DELETE FROM pantry")
    _conn.commit()
    yield
    _conn.execute("DELETE FROM pantry")
    _conn.commit()


class TestPantryServer:
    def test_save_returns_true(self, clear_pantry_store: None) -> None:
        assert save_pantry("s1", ["chicken", "garlic"]) is True

    def test_save_and_get(self, clear_pantry_store: None) -> None:
        save_pantry("s1", ["chicken", "garlic"])
        assert get_pantry("s1") == ["chicken", "garlic"]

    def test_get_missing_session_returns_empty(self, clear_pantry_store: None) -> None:
        assert get_pantry("unknown-session") == []

    def test_save_replaces_previous(self, clear_pantry_store: None) -> None:
        save_pantry("s1", ["chicken"])
        save_pantry("s1", ["eggs", "butter"])
        assert get_pantry("s1") == ["eggs", "butter"]

    def test_clear_returns_true(self, clear_pantry_store: None) -> None:
        save_pantry("s1", ["chicken"])
        assert clear_pantry("s1") is True

    def test_clear_removes_pantry(self, clear_pantry_store: None) -> None:
        save_pantry("s1", ["chicken"])
        clear_pantry("s1")
        assert get_pantry("s1") == []

    def test_clear_nonexistent_session_returns_true(self, clear_pantry_store: None) -> None:
        assert clear_pantry("nonexistent") is True

    def test_sessions_are_isolated(self, clear_pantry_store: None) -> None:
        save_pantry("s1", ["chicken"])
        save_pantry("s2", ["salmon"])
        assert get_pantry("s1") == ["chicken"]
        assert get_pantry("s2") == ["salmon"]


# ---------------------------------------------------------------------------
# Tavily Server
# ---------------------------------------------------------------------------

from backend.mcp_servers.tavily_server import (  # noqa: E402
    _get_client,
    fetch_recipe_page,
    web_search_recipes,
)


class TestTavilyServer:
    def test_web_search_returns_results(self) -> None:
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"url": "https://example.com/pasta", "title": "Pasta", "content": "Recipe..."}
            ]
        }
        with patch("backend.mcp_servers.tavily_server._get_client", return_value=mock_client):
            results = web_search_recipes("chicken pasta recipe", max_results=5)

        assert len(results) == 1
        assert results[0]["url"] == "https://example.com/pasta"
        assert results[0]["title"] == "Pasta"

    def test_web_search_empty_results(self) -> None:
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        with patch("backend.mcp_servers.tavily_server._get_client", return_value=mock_client):
            results = web_search_recipes("obscure dish")

        assert results == []

    def test_web_search_api_error_returns_empty(self) -> None:
        mock_client = MagicMock()
        mock_client.search.side_effect = RuntimeError("API error")
        with patch("backend.mcp_servers.tavily_server._get_client", return_value=mock_client):
            results = web_search_recipes("query")

        assert results == []

    def test_fetch_recipe_page_returns_content(self) -> None:
        mock_client = MagicMock()
        mock_client.extract.return_value = {
            "results": [{"raw_content": "Boil water. Add pasta. Cook 10 minutes."}]
        }
        with patch("backend.mcp_servers.tavily_server._get_client", return_value=mock_client):
            content = fetch_recipe_page("https://example.com/pasta")

        assert "Boil water" in content

    def test_fetch_recipe_page_empty_results(self) -> None:
        mock_client = MagicMock()
        mock_client.extract.return_value = {"results": []}
        with patch("backend.mcp_servers.tavily_server._get_client", return_value=mock_client):
            content = fetch_recipe_page("https://example.com/pasta")

        assert content == ""

    def test_fetch_recipe_page_error_returns_empty(self) -> None:
        mock_client = MagicMock()
        mock_client.extract.side_effect = RuntimeError("Extract failed")
        with patch("backend.mcp_servers.tavily_server._get_client", return_value=mock_client):
            content = fetch_recipe_page("https://example.com")

        assert content == ""

    def test_get_client_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        with pytest.raises(ValueError, match="TAVILY_API_KEY"):
            _get_client()


# ---------------------------------------------------------------------------
# Spoonacular Server
# ---------------------------------------------------------------------------

from backend.mcp_servers.spoonacular_server import (  # noqa: E402
    _api_key,
    get_recipe_detail,
    search_recipes_by_ingredients,
)


class TestSpoonacularServer:
    def test_search_returns_recipes(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"id": 1, "title": "Garlic Chicken", "usedIngredients": [], "missedIngredients": []}
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            results = search_recipes_by_ingredients(["chicken", "garlic"], number=5)

        assert len(results) == 1
        assert results[0]["title"] == "Garlic Chicken"

    def test_search_http_error_returns_empty(self) -> None:
        with patch("httpx.get", side_effect=RuntimeError("HTTP error")):
            results = search_recipes_by_ingredients(["chicken"])

        assert results == []

    def test_get_recipe_detail_returns_dict(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 42,
            "title": "Lemon Pasta",
            "sourceUrl": "https://example.com/lemon-pasta",
            "readyInMinutes": 20,
            "cuisines": ["Italian"],
            "diets": ["vegetarian"],
            "extendedIngredients": [{"name": "pasta", "amount": 200, "unit": "g"}],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            detail = get_recipe_detail(42)

        assert detail["id"] == 42
        assert detail["title"] == "Lemon Pasta"
        assert detail["cuisines"] == ["Italian"]
        assert len(detail["extendedIngredients"]) == 1

    def test_get_recipe_detail_http_error_returns_empty(self) -> None:
        with patch("httpx.get", side_effect=RuntimeError("HTTP error")):
            detail = get_recipe_detail(99)

        assert detail == {}

    def test_api_key_missing_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SPOONACULAR_API_KEY", raising=False)
        with pytest.raises(ValueError, match="SPOONACULAR_API_KEY"):
            _api_key()


# ---------------------------------------------------------------------------
# LangSmith Server
# ---------------------------------------------------------------------------

from backend.mcp_servers.langsmith_server import (  # noqa: E402
    _PUBLIC_UI_BASE,
    get_run_url,
    log_search_run,
)


class TestLangSmithServer:
    def test_get_run_url_default_endpoint(self) -> None:
        url = get_run_url("abc-token")
        assert url == f"{_PUBLIC_UI_BASE}/abc-token/r"

    def test_get_run_url_empty_token(self) -> None:
        assert get_run_url("") == ""

    def test_get_run_url_custom_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://my-langsmith.example.com")
        url = get_run_url("tok-123")
        assert url == "https://my-langsmith.example.com/public/tok-123/r"

    def test_log_search_run_returns_token_on_success(self) -> None:
        mock_post_response = MagicMock()
        mock_post_response.raise_for_status = MagicMock()
        mock_post_response.status_code = 200

        mock_share_response = MagicMock()
        mock_share_response.status_code = 200
        mock_share_response.json.return_value = {"share_token": "share-tok-xyz"}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client.post.return_value = mock_post_response
        mock_client.put.return_value = mock_share_response

        with patch("httpx.Client", return_value=mock_client):
            token = log_search_run(
                session_id="s1",
                inputs={"query": "chicken"},
                outputs={"count": 5},
                latency_ms=1200.0,
            )

        assert token == "share-tok-xyz"

    def test_log_search_run_http_error_returns_empty(self) -> None:
        with patch("httpx.Client", side_effect=RuntimeError("Connection refused")):
            token = log_search_run(
                session_id="s1",
                inputs={},
                outputs={},
                latency_ms=0.0,
            )

        assert token == ""

    def test_log_search_run_missing_api_key_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
        token = log_search_run("s1", {}, {}, 0.0)
        assert token == ""

    def test_log_search_run_share_404_retries_and_returns_empty(self) -> None:
        """When all share attempts return 404, the function returns empty string."""
        mock_post_response = MagicMock()
        mock_post_response.raise_for_status = MagicMock()

        mock_share_response = MagicMock()
        mock_share_response.status_code = 404

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client.post.return_value = mock_post_response
        mock_client.put.return_value = mock_share_response

        with patch("httpx.Client", return_value=mock_client):
            # Patch time.sleep to avoid a 4-second pause in the test
            with patch("backend.mcp_servers.langsmith_server.time.sleep"):
                token = log_search_run("s1", {}, {}, 0.0)

        assert token == ""
