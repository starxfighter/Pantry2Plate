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

### ADR-002: Single HTML file frontend with no build step — 2026-03-25
- **Decision**: Ship `frontend/index.html` as a self-contained file with inline
  CSS and vanilla JS. No npm, no bundler, no framework.
- **Why**: Minimises operational complexity for a local-only app; the file can be
  opened directly in a browser without a dev server.
- **Alternatives rejected**: React/Vue with a build step (adds toolchain overhead
  that isn't justified for a single-user local tool).
- **Consequences**: SSE must be consumed with the native `EventSource` API;
  scaling to a richer UI later would require introducing a build step.
