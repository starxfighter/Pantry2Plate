# Bug Log — Pantry-to-Plate

Active and resolved bugs. Add new bugs at the top of the Open section.
Move resolved bugs to the Resolved section.

See `SKILL.md` for the bug log format template.

---

## Open

_No open bugs._

---

### BUG-007: GET/DELETE /pantry read MemorySaver instead of SQLite — 2026-04-07
- **Status:** Resolved
- **Component:** `backend/main.py`, `backend/mcp_servers/pantry_server.py`

**Symptom:** After making pantry storage persistent (SQLite), `GET /pantry/{session_id}`
still returned `[]` after a server restart. `DELETE /pantry/{session_id}` deleted from
MemorySaver but left the SQLite row intact (orphaned data).

**Root cause:** The two pantry REST endpoints read/wrote `parsed_ingredients` from the
LangGraph `MemorySaver` checkpoint (ADR-005), which is in-memory and lost on restart.
The `save_pantry` MCP tool (called by `ParserAgent`) wrote to SQLite, but the REST
endpoints never read from it. The persistence layer and the API were completely
disconnected.

**Fix:** Updated `get_pantry_route` and `delete_pantry_route` in `main.py` to call
`_db_get_pantry(session_id)` and `_db_clear_pantry(session_id)` directly (imported from
`pantry_server`). ADR-005 superseded by ADR-008.

**Watch out for:** Two `sqlite3.Connection` objects now connect to the same file (one
in the MCP subprocess, one in the main process). SQLite handles this safely via file
locking, but on Windows with WAL mode disabled (the default), concurrent writes
serialize. Not a concern for single-user local use.

---

### BUG-006 — LangSmith share call fails 404 due to eventual consistency

- **Date found:** 2026-03-27
- **Status:** Resolved
- **Resolved date:** 2026-03-27
- **Severity:** High
- **Component:** mcp_servers

**Description**
`get_run_url` called `PUT /runs/{run_id}/share` immediately after `log_search_run` posted the run.
LangSmith's `POST /runs` returns **202 Accepted** (async) — the run is not yet indexed, so the share
call returned 404 and was silently swallowed. The frontend received `langsmith_run_url: null` and
never displayed the trace link.

**Root cause**
`POST /runs` is fire-and-forget; the run is indexed asynchronously. Calling `PUT /share`
within milliseconds of the create consistently returns 404.

**Fix**
Consolidated the share call into `log_search_run`: after `POST /runs`, retry
`PUT /runs/{id}/share` up to 3 times with 2-second pauses. On 200, return the
`share_token` directly. `get_run_url` simplified to just construct the URL string
(no HTTP call).

---

### BUG-005 — LangSmith trace URL showed "no run found with share token"

- **Date found:** 2026-03-27
- **Status:** Resolved
- **Resolved date:** 2026-03-27
- **Severity:** Medium
- **Component:** mcp_servers

**Description**
The LangSmith "View agent trace" link opened successfully but showed
"No run found with this share token" in the LangSmith UI.

**Root cause**
`get_run_url` was using the **run ID** directly as the share token in the URL
`https://smith.langchain.com/public/{run_id}/r`. LangSmith requires a separate
share token obtained from `PUT /runs/{run_id}/share`.

**Fix**
Added `PUT /runs/{run_id}/share` call in `get_run_url` to obtain a proper share
token. Later consolidated into `log_search_run` (see BUG-006).

---

### BUG-004 — TextContent wrapping breaks Spoonacular and Tavily tool results

- **Date found:** 2026-03-27
- **Status:** Resolved
- **Resolved date:** 2026-03-27
- **Severity:** High
- **Component:** agents

**Description**
`langchain-mcp-adapters` wraps every MCP tool result — including `list[dict]` returns —
as a list of TextContent dicts: `[{"type": "text", "text": "<json-string>"}]`.
In `search_agent.py`, `for c in candidates: c.get("id")` returned None for TextContent
dicts, so **all Spoonacular candidates were silently skipped** (0 Spoonacular recipes).
Tavily results were also serialized incorrectly to the LLM as the TextContent wrapper,
degrading recipe extraction quality.

**Root cause**
Same `langchain-mcp-adapters` serialization issue as BUG-003, but affecting `list[dict]`
return types in search_agent (not just `str` in scorer_agent).

**Fix**
Added `_unwrap_tool_list(raw)` helper in `search_agent.py` that normalises any
TextContent-wrapped, string, or plain-list result into `list[dict]`. Applied to
all four tool call sites in `_search_tavily` and `_search_spoonacular`.

---

### BUG-003 — LangSmith MCP tool returns content object list, not plain string

- **Date found:** 2026-03-26
- **Status:** Resolved
- **Resolved date:** 2026-03-26
- **Severity:** High
- **Component:** mcp_servers, agents

**Description**
`langchain-mcp-adapters` 0.2.2 returns tool results as `[{'type': 'text', 'text': '...'}]`
(MCP TextContent list) instead of a plain `str`, even when the tool return type is `str`.
Passing this list to `get_run_url` as `run_id` failed Pydantic validation, raising a
`ToolException` that propagated as an ExceptionGroup.

**Root cause**
`langchain-mcp-adapters` does not automatically unwrap single-text MCP content responses
to the declared Python return type for all tool shapes.

**Fix**
Added `_extract_text(value)` helper in `scorer_agent.py` that handles both `str` and
`list[dict]` (TextContent) return shapes.

---

### BUG-002 — langsmith.Client background threads block FastMCP stdio response

- **Date found:** 2026-03-26
- **Status:** Resolved
- **Resolved date:** 2026-03-26
- **Severity:** High
- **Component:** mcp_servers

**Description**
Using `langsmith.Client().create_run()` inside a synchronous FastMCP tool caused the
subprocess to not flush its stdio response to the parent process in a timely manner.
The parent's `ainvoke` timed out waiting for the response.

**Root cause**
`langsmith.Client` starts background daemon threads for batch processing.  These threads
interact with the subprocess process state in a way that delays stdout flushing inside
the FastMCP stdio transport.

**Fix**
Replaced `langsmith.Client` with a direct `httpx.Client` POST to the LangSmith REST API
(`/runs` endpoint) in `langsmith_server.py`.  No background threads, clean synchronous
HTTP call.

---

## Resolved

### BUG-001 — fastmcp dev inspector fails to connect on default ports

- **Date found:** 2026-03-26
- **Status:** Resolved
- **Resolved date:** 2026-03-26
- **Severity:** Low
- **Component:** mcp_servers

**Description**
Running `fastmcp dev inspector <server.py>` opens the browser UI but clicking
Connect returns a connection error.  The root cause is a port conflict: FastMCP
tries to bind the inspector proxy on port 8000 (same as the FastAPI backend) and
the UI on another default port, both of which may already be occupied.

**Steps to reproduce**
1. Have any process bound to port 8000 (e.g. uvicorn running the FastAPI backend).
2. Run `fastmcp dev inspector backend/mcp_servers/pantry_server.py`.
3. Open the browser UI and click Connect.

**Root cause**
FastMCP's inspector starts two local HTTP listeners — a UI server and a proxy
server — on default ports that conflict with the FastAPI backend (8000) or other
local services.  The stdio MCP server itself starts fine; only the HTTP bridge
fails to bind.

**Fix**
Pass explicit ports that are known to be free:

```bash
fastmcp dev inspector backend/mcp_servers/<server>.py --ui-port 5173 --server-port 3000
```

Then open `http://localhost:5173` and click Connect.  Use one server at a time;
stop the inspector before launching the next one to free the ports.

**Watch out for**
Port 5173 is Vite's default — if a frontend dev server is running, use a
different `--ui-port` (e.g. 5174).  Port 3000 is also commonly used by Node
apps; substitute `--server-port 3001` if needed.

---

<!-- Bug template (copy and fill in):

### BUG-NNN — <short title>

- **Date found:** YYYY-MM-DD
- **Status:** Open | In Progress | Resolved | Won't Fix
- **Resolved date:** —
- **Severity:** Critical | High | Medium | Low
- **Component:** agents | mcp_servers | graph | api | frontend | tests

**Description**


**Steps to reproduce**
1.
2.

**Root cause**


**Fix**

-->
