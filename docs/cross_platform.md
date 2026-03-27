# Cross-Platform Notes — Pantry-to-Plate

_Last updated: 2026-03-26_

This document lists the changes required to run Pantry-to-Plate on
**Linux** or **macOS** (or any Unix system).  The app was developed and
tested on Windows 11 with Anaconda Python 3.11.

---

## Why some code is Windows-specific

Python's `asyncio` uses different event loop implementations per OS:

| OS | Event loop | I/O model |
|---|---|---|
| Windows | `ProactorEventLoop` | IOCP (I/O Completion Ports) |
| Linux / macOS | `SelectorEventLoop` | `select` / `epoll` / `kqueue` |

Several workarounds exist in this codebase solely because of Windows
`ProactorEventLoop` behaviour.  On a `SelectorEventLoop` these workarounds
are harmless but unnecessary.

---

## Changes to make for Linux / macOS

### 1. Remove `await asyncio.sleep(0)` event-loop yield hacks

**Files affected:**
- `backend/agents/search_agent.py` — between Tavily and Spoonacular sessions
- `backend/agents/scorer_agent.py` — before the LangSmith session

**Why they exist (Windows only):**
After many sequential subprocess stdio reads, the Windows ProactorEventLoop
accumulates stale IOCP completion notifications.  A single `await asyncio.sleep(0)`
yields the event loop so those notifications can be drained before the next
subprocess session starts.  Without this, the next subprocess read hangs
indefinitely.

**On Linux/macOS:** `SelectorEventLoop` does not use IOCP.  The sleeps are
safe to remove.  Removing them makes the code slightly cleaner and faster.

---

### 2. Enable concurrent Spoonacular detail fetches

**File:** `backend/agents/search_agent.py`, method `_search_spoonacular`

**Current (Windows):** Sequential fetches inside a single MCP session:
```python
# Sequential — avoids Windows IOCP hang after many reads
for c in candidates:
    detail = await detail_tool.ainvoke({"recipe_id": c["id"]})
    details.append(detail)
```

**Linux/macOS:** Replace with concurrent fetches using `asyncio.gather`:
```python
import asyncio

async def _fetch(c: dict) -> dict | Exception:
    try:
        return await detail_tool.ainvoke({"recipe_id": c["id"]})
    except Exception as exc:
        return exc

details = await asyncio.gather(*[_fetch(c) for c in candidates if c.get("id")])
```

**Why:** On `SelectorEventLoop`, multiple concurrent reads from a single
subprocess pipe work correctly without IOCP notification backlog.  This
reduces the Spoonacular phase from ~5–10 s (sequential) to ~1–2 s (parallel).

**Caution:** Do **not** open multiple `MultiServerMCPClient` sessions
concurrently (they each spawn a subprocess).  The concurrent fetches above
share a single session — that is safe on all platforms.

---

### 3. Python executable path

**Current (Windows):**
All references to `sys.executable` in agent/server code automatically
use the current Python interpreter.  No change needed.

**Shell scripts / CI (if any):**
Replace `/d/anaconda3/python.exe` with the system `python3` or the path
inside your virtual environment.  The `backend/utils/mcp_manager.py` uses
`sys.executable` so it works correctly on all platforms without changes.

---

### 4. Process termination in `MCPServerManager`

**File:** `backend/utils/mcp_manager.py`, method `_terminate`

**Current:** `process.terminate()` sends `SIGTERM` on Unix and calls
`TerminateProcess()` on Windows — both are handled by `asyncio.subprocess`.

**No change needed** — `asyncio.subprocess.Process.terminate()` is
cross-platform.

---

### 5. `.env` loading path

**Current:** Each MCP server resolves its `.env` file relative to its own
`__file__` path (e.g. `Path(__file__).resolve().parents[2] / ".env"`).
This works on all platforms.

**No change needed.**

---

## Summary table

| Change | Required on Linux/macOS | Impact |
|---|---|---|
| Remove `asyncio.sleep(0)` yields | Optional (harmless to keep) | Code cleanliness |
| Concurrent Spoonacular fetches | Recommended | ~5x faster search phase |
| Python executable path | Only if using shell scripts | Dev workflow |
| Process termination | Not needed | Already cross-platform |
| `.env` loading | Not needed | Already cross-platform |

---

## Recommended: detect platform and branch

If you want a single codebase that runs optimally on both Windows and Unix,
detect the platform in `search_agent.py`:

```python
import sys

# Use concurrent Spoonacular fetches on Unix; sequential on Windows to avoid
# ProactorEventLoop IOCP backlog.
_SEQUENTIAL_DETAIL_FETCH = sys.platform == "win32"
```

Then branch in `_search_spoonacular`:
```python
if _SEQUENTIAL_DETAIL_FETCH:
    for c in candidates:
        ...  # current sequential code
else:
    details = await asyncio.gather(*[_fetch(c) for c in candidates])
```
