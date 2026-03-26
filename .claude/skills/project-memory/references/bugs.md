# Bug Log — Pantry-to-Plate

Active and resolved bugs. Add new bugs at the top of the Open section.
Move resolved bugs to the Resolved section.

See `SKILL.md` for the bug log format template.

---

## Open

_No open bugs._

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
