# Architecture decisions — Pantry-to-Plate

_Log every significant design or technology choice here using the ADR format.
Small implementation details don't need an ADR — use this for choices that would
be hard or costly to reverse._

---

## Template
### ADR-000: [short title] — [YYYY-MM-DD]
- **Decision**: What was chosen
- **Why**: The reasoning
- **Alternatives rejected**: What else was considered
- **Consequences**: What this means going forward

---

## Decisions

### ADR-001: Use FastMCP with stdio transport for MCP servers — 2026-03-25
- **Decision**: All four MCP servers use stdio transport, running as subprocesses
  managed by the FastAPI lifespan handler.
- **Why**: Simpler deployment — no extra ports or network config required for MCP
  servers. The parent process communicates over stdin/stdout.
- **Alternatives rejected**: HTTP/SSE transport (adds port management and networking
  complexity for a local-only app).
- **Consequences**: MCP server lifecycle must be managed carefully in `main.py`
  lifespan hooks; servers cannot be called independently without the parent running.

### ADR-004: Sequential Spoonacular detail fetches — 2026-03-26
- **Decision**: `get_recipe_detail` calls inside `_search_spoonacular` run sequentially
  (one at a time), not concurrently.
- **Why**: Concurrent subprocess stdio reads on Windows ProactorEventLoop cause IOCP
  completion notifications to pile up, hanging subsequent subprocess sessions.
- **Alternatives rejected**: `asyncio.gather` for concurrent detail fetches (hangs on
  Windows after ~11 concurrent reads).
- **Consequences**: Spoonacular phase is slower (10 sequential HTTP calls ≈ 5–10 s).
  On Linux/macOS (where `asyncio.run()` uses `SelectorEventLoop`), concurrent fetches
  would be safe — see `docs/cross_platform.md`.

### ADR-003: Direct httpx over langsmith.Client in LangSmith MCP server — 2026-03-26
- **Decision**: `langsmith_server.py` uses `httpx.Client` to POST directly to the
  LangSmith REST API instead of using the `langsmith.Client` SDK.
- **Why**: `langsmith.Client` spawns background daemon threads for batch processing.
  Inside a FastMCP stdio subprocess, these threads interfere with stdout flushing,
  causing the parent process's MCP `ainvoke` to never receive the tool response.
- **Alternatives rejected**: `langsmith.Client` with `timeout_ms` (still hangs),
  async `httpx.AsyncClient` in an `async def` tool (anyio task group issues in
  subprocess context on Windows).
- **Consequences**: We lose the SDK's retry logic and structured run metadata.
  All metadata is encoded manually in the payload.  Acceptable for best-effort logging.

### ADR-005: Pantry REST endpoints read from LangGraph checkpoint — 2026-03-27
- **Decision**: `GET /pantry/{session_id}` and `DELETE /pantry/{session_id}` access
  `parsed_ingredients` via `graph.aget_state` / `graph.aupdate_state`, not via MCP.
- **Why**: The pantry MCP subprocess is ephemeral — it is spawned inside `ParserAgent`'s
  `async with mcp_client.session("pantry")` block and terminates when the block exits.
  Any new MCP session in a route handler would get a fresh empty `_store`. The only
  durable copy of `parsed_ingredients` is the LangGraph `MemorySaver` checkpoint.
- **Alternatives rejected**: Opening a new MCP session to pantry_server in the route
  handler (gets a separate process with empty state); maintaining a parallel in-process
  dict on `app.state` (gets out of sync with agent-written data).
- **Consequences**: Pantry endpoints are only meaningful after a pipeline run has
  completed for that session_id. Callers querying a session that has no checkpoint
  receive `[]` gracefully.

### ADR-006: Consolidate LangSmith run creation and share into one tool call — 2026-03-27
- **Decision**: `log_search_run` in `langsmith_server.py` calls both `POST /runs` (create) and
  `PUT /runs/{id}/share` (obtain share token) within the same `httpx.Client` session, retrying
  the share call up to 3× with 2s delay. Returns the share token directly. `get_run_url`
  only constructs the URL string — no HTTP call.
- **Why**: `POST /runs` returns 202 Accepted (asynchronous). Calling `PUT /share` immediately
  in a separate tool invocation consistently gets a 404 because the run isn't indexed yet.
  Retry loop in the same synchronous call handles eventual consistency.
- **Alternatives rejected**: Separate `get_run_url` HTTP call (race condition); `asyncio.sleep`
  in async context (anyio task-group issues in subprocess context).
- **Consequences**: `log_search_run` takes up to 4s extra when retries are needed. LangSmith
  errors still degrade gracefully (empty string → no trace link shown).

### ADR-002: Single HTML file frontend with no build step — 2026-03-25
- **Decision**: Ship `frontend/index.html` as a self-contained file with inline
  CSS and vanilla JS. No npm, no bundler, no framework.
- **Why**: Minimises operational complexity for a local-only app; the file can be
  opened directly in a browser without a dev server.
- **Alternatives rejected**: React/Vue with a build step (adds toolchain overhead
  that isn't justified for a single-user local tool).
- **Consequences**: SSE must be consumed with the native `EventSource` API;
  scaling to a richer UI later would require introducing a build step.
