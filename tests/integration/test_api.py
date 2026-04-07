"""Integration tests for the FastAPI gateway (backend/main.py).

Uses httpx.AsyncClient with the FastAPI app directly (no live uvicorn process).
ASGITransport does NOT send ASGI lifespan events, so app.state.mcp_manager is
set directly on the fixture to avoid AttributeError in the /health endpoint.

Marked with ``pytest.mark.integration`` — run with:
    pytest tests/integration/ -v -m integration
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.mcp_servers.pantry_server import (
    _conn as _pantry_conn,
    save_pantry as _db_save_pantry,
)

# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mcp_manager():
    """Function-scoped MCPServerManager stub that never spawns subprocesses."""
    manager = MagicMock()
    manager.start_all = AsyncMock(return_value=None)
    manager.stop_all = AsyncMock(return_value=None)
    manager.is_running = True
    return manager


@pytest.fixture(autouse=True)
def clear_pantry_db() -> None:
    """Wipe the in-memory pantry table before and after each integration test."""
    _pantry_conn.execute("DELETE FROM pantry")
    _pantry_conn.commit()
    yield
    _pantry_conn.execute("DELETE FROM pantry")
    _pantry_conn.commit()


@pytest_asyncio.fixture
async def client(mock_mcp_manager):
    """Yield an httpx AsyncClient wired to the FastAPI app.

    ASGITransport does not send lifespan events, so we set app.state.mcp_manager
    directly so the /health endpoint can access it.
    """
    from backend.main import app

    # Inject the mock manager into app.state so /health works without lifespan.
    app.state.mcp_manager = mock_mcp_manager

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    # Clean up after each test so the next fixture gets a fresh state.
    try:
        del app.state._state["mcp_manager"]
    except (KeyError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestHealthEndpoint:
    async def test_health_ok(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["mcp_servers_running"] is True

    async def test_health_degraded_when_mcp_not_running(
        self, client: AsyncClient, mock_mcp_manager: MagicMock
    ) -> None:
        mock_mcp_manager.is_running = False
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "degraded"


# ---------------------------------------------------------------------------
# GET /pantry/{session_id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPantryGetEndpoint:
    async def test_get_pantry_no_checkpoint(self, client: AsyncClient) -> None:
        """A session with no prior run should return an empty list."""
        response = await client.get("/pantry/no-such-session-xyz")
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_pantry_with_saved_data(self, client: AsyncClient) -> None:
        """Data written to the SQLite pantry store is returned by GET /pantry."""
        _db_save_pantry("session-abc", ["chicken", "garlic"])
        response = await client.get("/pantry/session-abc")
        assert response.status_code == 200
        assert response.json() == ["chicken", "garlic"]


# ---------------------------------------------------------------------------
# DELETE /pantry/{session_id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPantryDeleteEndpoint:
    async def test_delete_pantry_returns_cleared(self, client: AsyncClient) -> None:
        _db_save_pantry("session-abc", ["chicken"])
        response = await client.delete("/pantry/session-abc")
        assert response.status_code == 200
        assert response.json() == {"cleared": True}

    async def test_delete_pantry_removes_data(self, client: AsyncClient) -> None:
        """After DELETE, a subsequent GET should return an empty list."""
        _db_save_pantry("session-del", ["eggs", "butter"])
        await client.delete("/pantry/session-del")
        response = await client.get("/pantry/session-del")
        assert response.json() == []

    async def test_delete_pantry_graceful_on_error(self, client: AsyncClient) -> None:
        """Even if the DB raises, endpoint returns cleared=True."""
        with patch("backend.main._db_clear_pantry", side_effect=RuntimeError("DB error")):
            response = await client.delete("/pantry/bad-session")

        assert response.status_code == 200
        assert response.json()["cleared"] is True


# ---------------------------------------------------------------------------
# POST /search
# ---------------------------------------------------------------------------


def _make_scored_recipe(name: str, score: float) -> dict:
    return {
        "name": name,
        "url": f"https://example.com/{name.lower().replace(' ', '-')}",
        "source": "Test",
        "ingredient_list": ["chicken", "garlic"],
        "steps_summary": "Cook it.",
        "cook_time_minutes": 30,
        "cuisine": "Italian",
        "dietary_tags": [],
        "match_score": score,
        "ingredients_have": ["chicken"],
        "ingredients_missing": [],
        "ingredients_staple": ["garlic"],
    }


def _parse_sse_done_event(body: str) -> dict | None:
    """Extract the data payload from the 'done' SSE event in a response body."""
    lines = body.splitlines()
    in_done_event = False
    for line in lines:
        if line == "event: done":
            in_done_event = True
        elif in_done_event and line.startswith("data:"):
            return json.loads(line[5:].strip())
    return None


@pytest.mark.integration
class TestSearchEndpoint:
    async def test_search_missing_fields_returns_422(self, client: AsyncClient) -> None:
        response = await client.post("/search", json={})
        assert response.status_code == 422

    async def test_search_raw_input_too_long_returns_422(self, client: AsyncClient) -> None:
        """raw_input longer than 2000 chars should be rejected before hitting the graph."""
        response = await client.post(
            "/search",
            json={"raw_input": "x" * 2001, "session_id": "s1", "filters": {}},
        )
        assert response.status_code == 422

    async def test_search_streams_sse_events(self, client: AsyncClient) -> None:
        """POST /search should return a text/event-stream response."""
        scored = [_make_scored_recipe("Garlic Chicken", 85.0)]

        mock_state = MagicMock()
        mock_state.values = {
            "scored_recipes": scored,
            "langsmith_run_url": "https://smith.langchain.com/public/tok/r",
        }

        async def fake_astream(*args, **kwargs):
            yield {
                "score_node": {
                    "current_step": "scoring",
                    "scored_recipes": scored,
                    "search_results": [],
                    "tavily_recipe_count": 1,
                    "spoonacular_recipe_count": 0,
                }
            }

        with patch("backend.main.graph.astream", side_effect=fake_astream):
            with patch("backend.main.graph.aget_state", AsyncMock(return_value=mock_state)):
                response = await client.post(
                    "/search",
                    json={
                        "raw_input": "I have chicken and garlic",
                        "session_id": "test-search-session",
                        "filters": {},
                    },
                )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        assert "event: done" in response.text

    async def test_search_done_event_contains_recipes(self, client: AsyncClient) -> None:
        scored = [_make_scored_recipe("Lemon Pasta", 75.0)]

        mock_state = MagicMock()
        mock_state.values = {
            "scored_recipes": scored,
            "langsmith_run_url": None,
        }

        async def fake_astream(*args, **kwargs):
            yield {
                "score_node": {
                    "current_step": "scoring",
                    "scored_recipes": scored,
                    "search_results": [],
                    "tavily_recipe_count": 1,
                    "spoonacular_recipe_count": 0,
                }
            }

        with patch("backend.main.graph.astream", side_effect=fake_astream):
            with patch("backend.main.graph.aget_state", AsyncMock(return_value=mock_state)):
                response = await client.post(
                    "/search",
                    json={
                        "raw_input": "pasta lemon",
                        "session_id": "test-done-session",
                        "filters": {},
                    },
                )

        done_data = _parse_sse_done_event(response.text)
        assert done_data is not None
        assert len(done_data["scored_recipes"]) == 1
        assert done_data["scored_recipes"][0]["name"] == "Lemon Pasta"

    async def test_search_error_event_on_graph_failure(self, client: AsyncClient) -> None:
        """When astream raises, an error SSE event should be emitted."""

        async def failing_astream(*args, **kwargs):
            raise RuntimeError("Graph exploded")
            yield  # make it a generator

        with patch("backend.main.graph.astream", side_effect=failing_astream):
            response = await client.post(
                "/search",
                json={
                    "raw_input": "bad input",
                    "session_id": "error-session",
                    "filters": {},
                },
            )

        assert response.status_code == 200
        assert "event: error" in response.text
