"""MCP server lifecycle manager for the Pantry-to-Plate pipeline.

Launches each FastMCP server script as a stdio subprocess, monitors their
health, and optionally restarts any that die unexpectedly.

Typical usage (inside a FastAPI lifespan)::

    manager = MCPServerManager()
    await manager.start_all()
    # ... serve requests ...
    await manager.stop_all()

Environment variables:
    MCP_SERVER_STARTUP_TIMEOUT: Seconds to wait after launching all servers
        before checking that they are still alive.  Defaults to ``5``.
    MCP_AUTO_RESTART: Set to ``"true"`` to automatically restart any server
        process that exits unexpectedly.  Defaults to ``"false"``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SERVERS: dict[str, str] = {
    "pantry": "backend/mcp_servers/pantry_server.py",
    "tavily": "backend/mcp_servers/tavily_server.py",
    "spoonacular": "backend/mcp_servers/spoonacular_server.py",
    "langsmith": "backend/mcp_servers/langsmith_server.py",
}

_SIGKILL_WAIT: float = 3.0   # seconds between SIGTERM and SIGKILL
_MONITOR_INTERVAL: float = 2.0  # seconds between health-check polls


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _log(level: str, event: str, **context: object) -> None:
    """Emit a structured JSON log record."""
    record = json.dumps({"event": event, **context})
    getattr(logger, level)(record)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class MCPServerManager:
    """Manages the lifecycle of all FastMCP stdio server subprocesses.

    Attributes:
        _processes: Mapping of server name to live ``asyncio.subprocess.Process``.
        _restart_task: Background asyncio Task running the health-monitor loop,
            or ``None`` when auto-restart is disabled or ``stop_all`` has been
            called.
    """

    def __init__(self) -> None:
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._restart_task: asyncio.Task | None = None
        self._project_root: Path = Path(__file__).resolve().parents[2]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_all(self) -> None:
        """Launch all MCP server subprocesses and wait for them to stabilise.

        Each server is started with the same Python interpreter that is
        running this process (``sys.executable``) so virtual-environment
        packages are always available.

        Raises:
            RuntimeError: If any server process exits before the startup
                timeout elapses, indicating a misconfiguration or missing
                environment variable.
        """
        timeout = float(os.getenv("MCP_SERVER_STARTUP_TIMEOUT", "5"))

        for name, rel_path in _SERVERS.items():
            script = str(self._project_root / rel_path)
            _log("info", "mcp_server_starting", server=name, script=script)
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                script,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._project_root),
            )
            self._processes[name] = process
            _log("info", "mcp_server_launched", server=name, pid=process.pid)

        # Allow servers time to initialise before checking health.
        await asyncio.sleep(timeout)
        self._assert_all_running()

        auto_restart = os.getenv("MCP_AUTO_RESTART", "false").lower() == "true"
        if auto_restart:
            self._restart_task = asyncio.create_task(
                self._monitor_and_restart(),
                name="mcp-monitor",
            )
            _log("info", "mcp_auto_restart_enabled")

    async def stop_all(self) -> None:
        """Gracefully terminate all MCP server subprocesses.

        Sends SIGTERM (``process.terminate()``) to each process and waits up
        to ``_SIGKILL_WAIT`` seconds for a clean exit before escalating to
        SIGKILL (``process.kill()``).  The auto-restart monitor is cancelled
        before termination begins so it cannot race to restart a process that
        is intentionally being shut down.
        """
        if self._restart_task and not self._restart_task.done():
            self._restart_task.cancel()
            try:
                await self._restart_task
            except asyncio.CancelledError:
                pass
            self._restart_task = None

        for name, process in list(self._processes.items()):
            await self._terminate(name, process)

        self._processes.clear()
        _log("info", "mcp_all_servers_stopped")

    @property
    def is_running(self) -> bool:
        """Return ``True`` if all server processes are currently alive.

        A process is considered alive when ``process.returncode`` is ``None``
        (i.e. it has not yet exited).
        """
        if not self._processes:
            return False
        return all(p.returncode is None for p in self._processes.values())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assert_all_running(self) -> None:
        """Raise ``RuntimeError`` if any process has already exited.

        Args: none (reads ``self._processes``).

        Raises:
            RuntimeError: With the name and return code of the first failed
                server found.
        """
        for name, process in self._processes.items():
            if process.returncode is not None:
                raise RuntimeError(
                    f"MCP server '{name}' exited unexpectedly during startup "
                    f"(return code {process.returncode}). "
                    "Check that all required environment variables are set."
                )

    async def _launch_one(self, name: str) -> None:
        """(Re-)launch a single MCP server subprocess.

        Args:
            name: Key from ``_SERVERS`` identifying which server to start.
        """
        rel_path = _SERVERS[name]
        script = str(self._project_root / rel_path)
        _log("info", "mcp_server_starting", server=name, script=script)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_root),
        )
        self._processes[name] = process
        _log("info", "mcp_server_launched", server=name, pid=process.pid)

    async def _terminate(self, name: str, process: asyncio.subprocess.Process) -> None:
        """Terminate a single subprocess, escalating to SIGKILL if needed.

        Args:
            name: Human-readable server name for logging.
            process: The subprocess handle to terminate.
        """
        if process.returncode is not None:
            return  # already exited

        _log("info", "mcp_server_terminating", server=name, pid=process.pid)
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=_SIGKILL_WAIT)
            _log("info", "mcp_server_stopped", server=name, pid=process.pid)
        except asyncio.TimeoutError:
            _log("warning", "mcp_server_sigkill", server=name, pid=process.pid)
            try:
                process.kill()
                await process.wait()
            except Exception as exc:
                _log("error", "mcp_server_kill_failed", server=name, error=str(exc))

    async def _monitor_and_restart(self) -> None:
        """Background task: poll all processes and restart any that have died.

        Runs indefinitely until cancelled (by ``stop_all``).  Each dead
        process is restarted once immediately; if it exits again on the next
        poll it will be restarted again.  No back-off is applied — if a server
        is consistently crashing, structured error logs will accumulate and
        make the pattern visible.
        """
        while True:
            await asyncio.sleep(_MONITOR_INTERVAL)
            for name, process in list(self._processes.items()):
                if process.returncode is not None:
                    _log(
                        "warning",
                        "mcp_server_died_restarting",
                        server=name,
                        return_code=process.returncode,
                    )
                    try:
                        await self._launch_one(name)
                    except Exception as exc:
                        _log(
                            "error",
                            "mcp_server_restart_failed",
                            server=name,
                            error=str(exc),
                        )
