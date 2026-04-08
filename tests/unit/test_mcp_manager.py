"""Unit tests for backend/utils/mcp_manager.py.

subprocess.Popen and asyncio.sleep are patched so no real subprocesses are
spawned.  Tests exercise the manager's lifecycle and error paths.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.utils.mcp_manager import MCPServerManager, _log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_process(alive: bool = True) -> MagicMock:
    """Return a fake subprocess.Popen object."""
    proc = MagicMock()
    proc.pid = 12345
    proc.returncode = None if alive else 1
    proc.poll.return_value = None if alive else 1
    proc.wait.return_value = 0
    return proc


# ---------------------------------------------------------------------------
# _log helper
# ---------------------------------------------------------------------------


class TestLog:
    def test_log_does_not_raise(self) -> None:
        # Just verify no exception
        _log("info", "test_event", key="value")

    def test_log_error_level(self) -> None:
        _log("error", "test_error", detail="oops")


# ---------------------------------------------------------------------------
# MCPServerManager.is_running
# ---------------------------------------------------------------------------


class TestIsRunning:
    def test_false_when_no_processes(self) -> None:
        manager = MCPServerManager()
        assert manager.is_running is False

    def test_true_when_all_processes_alive(self) -> None:
        manager = MCPServerManager()
        manager._processes = {"a": _mock_process(alive=True)}
        assert manager.is_running is True

    def test_false_when_one_process_dead(self) -> None:
        manager = MCPServerManager()
        manager._processes = {
            "a": _mock_process(alive=True),
            "b": _mock_process(alive=False),
        }
        assert manager.is_running is False


# ---------------------------------------------------------------------------
# MCPServerManager._assert_all_running
# ---------------------------------------------------------------------------


class TestAssertAllRunning:
    def test_no_exception_when_all_alive(self) -> None:
        manager = MCPServerManager()
        manager._processes = {"pantry": _mock_process(alive=True)}
        manager._assert_all_running()  # should not raise

    def test_raises_when_process_exited(self) -> None:
        manager = MCPServerManager()
        manager._processes = {"tavily": _mock_process(alive=False)}
        with pytest.raises(RuntimeError, match="tavily"):
            manager._assert_all_running()


# ---------------------------------------------------------------------------
# MCPServerManager._launch_one
# ---------------------------------------------------------------------------


class TestLaunchOne:
    async def test_launch_creates_process(self) -> None:
        manager = MCPServerManager()
        fake_proc = _mock_process(alive=True)

        with patch("subprocess.Popen", return_value=fake_proc):
            await manager._launch_one("pantry")

        assert "pantry" in manager._processes
        assert manager._processes["pantry"] is fake_proc

    async def test_launch_replaces_existing_entry(self) -> None:
        manager = MCPServerManager()
        old_proc = _mock_process(alive=False)
        manager._processes["pantry"] = old_proc

        new_proc = _mock_process(alive=True)
        with patch("subprocess.Popen", return_value=new_proc):
            await manager._launch_one("pantry")

        assert manager._processes["pantry"] is new_proc


# ---------------------------------------------------------------------------
# MCPServerManager.start_all
# ---------------------------------------------------------------------------


class TestStartAll:
    async def test_start_all_launches_all_servers(self) -> None:
        manager = MCPServerManager()
        fake_proc = _mock_process(alive=True)

        with patch("subprocess.Popen", return_value=fake_proc):
            with patch("asyncio.sleep", AsyncMock(return_value=None)):
                await manager.start_all()

        # All 4 servers should be in _processes
        assert len(manager._processes) == 4

    async def test_start_all_raises_when_server_exits_on_startup(self) -> None:
        manager = MCPServerManager()
        fake_proc = _mock_process(alive=False)

        with patch("subprocess.Popen", return_value=fake_proc):
            with patch("asyncio.sleep", AsyncMock(return_value=None)):
                with pytest.raises(RuntimeError, match="exited unexpectedly"):
                    await manager.start_all()

    async def test_start_all_enables_monitor_when_auto_restart_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MCP_AUTO_RESTART", "true")
        manager = MCPServerManager()
        fake_proc = _mock_process(alive=True)

        with patch("subprocess.Popen", return_value=fake_proc):
            with patch("asyncio.sleep", AsyncMock(return_value=None)):
                await manager.start_all()

        assert manager._restart_task is not None
        # Cancel the background task to avoid test teardown issues
        manager._restart_task.cancel()
        try:
            await manager._restart_task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# MCPServerManager.stop_all
# ---------------------------------------------------------------------------


class TestStopAll:
    async def test_stop_all_terminates_processes(self) -> None:
        manager = MCPServerManager()
        proc = _mock_process(alive=True)
        # Make proc.wait return quickly via executor
        proc.wait.return_value = 0
        manager._processes = {"pantry": proc}

        # _terminate uses run_in_executor(None, process.wait) — mock that call
        with patch.object(
            manager, "_terminate", AsyncMock(return_value=None)
        ) as mock_term:
            await manager.stop_all()

        mock_term.assert_called_once()
        assert manager._processes == {}

    async def test_stop_all_cancels_restart_task(self) -> None:
        manager = MCPServerManager()

        async def dummy_monitor() -> None:
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                raise

        manager._restart_task = asyncio.create_task(dummy_monitor())
        manager._processes = {}

        await manager.stop_all()

        assert manager._restart_task is None


# ---------------------------------------------------------------------------
# MCPServerManager._terminate
# ---------------------------------------------------------------------------


class TestTerminate:
    async def test_terminate_skips_already_dead_process(self) -> None:
        manager = MCPServerManager()
        dead_proc = _mock_process(alive=False)

        # Should not call terminate() on an already-dead process
        await manager._terminate("pantry", dead_proc)
        dead_proc.terminate.assert_not_called()

    async def test_terminate_sends_sigterm(self) -> None:
        manager = MCPServerManager()
        alive_proc = _mock_process(alive=True)

        # Simulate process exiting cleanly after terminate()
        with patch(
            "asyncio.wait_for",
            AsyncMock(return_value=None),
        ):
            await manager._terminate("pantry", alive_proc)

        alive_proc.terminate.assert_called_once()

    async def test_terminate_kills_on_timeout(self) -> None:
        manager = MCPServerManager()
        alive_proc = _mock_process(alive=True)

        with patch("asyncio.wait_for", AsyncMock(side_effect=asyncio.TimeoutError)):
            await manager._terminate("pantry", alive_proc)

        alive_proc.kill.assert_called_once()
