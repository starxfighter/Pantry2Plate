---
name: project-memory
description: >
  Manages persistent memory across sessions for the Pantry-to-Recipe web app.
  Use at the start of every session to recover project state and at the end of
  every session to save progress. Invoke with /project-memory, or automatically
  when the user says "resume", "let's continue", "pick up where we left off",
  "what's next", "what have we done", "what's the status", or opens a new session
  on this project.
allowed-tools: Bash(cat *), Bash(echo *), Bash(mkdir *), Bash(touch *)
---

# Project memory — Pantry-to-Recipe app

## On session start (always do this first)
1. Read `references/progress.md` — recover current state and resume point
2. Read `references/context.md` — reload stable project facts and config
3. Read `references/todo.md` — confirm what's prioritized for this session
4. Read `AGENTS.md` (project root) — reload agent contracts and schemas
5. Read `docs/architecture.md` (project root) — reload current architecture overview
6. Briefly summarize to the user:
   - What was completed last session
   - What the resume point is
   - What's on the todo list for today
7. Ask: "Ready to continue, or do you want to adjust priorities?"

## During a session
- When a significant architecture or design decision is made, append it to
  `references/decisions.md` using the ADR format defined below
- When a bug is found and fixed, log it in `references/bugs.md`
- When a config value, port, env variable, or tool version is confirmed,
  update `references/context.md` immediately — do not wait until session end
- When a todo item is completed, mark it done in `references/todo.md`
- When an agent's state fields, tools, schemas, or rules change, update `AGENTS.md`
- When overall system structure or data flow changes, update `docs/architecture.md`
- When implementation patterns or class structure changes, update `backend/agents/agents.md`

## On session end (always do this before closing)
1. Update `references/progress.md`:
   - Write a clear "Resume here" block at the top with last action and next action
   - Append a session log entry with completed work, decisions, and blockers
2. Update `references/todo.md` — mark completed tasks, reprioritize if needed
3. Update `references/decisions.md` — add any ADRs made this session
4. Update `references/bugs.md` — log any bugs found and fixed
5. Update `docs/architecture.md` — reflect any structural changes made this session
6. Note any unresolved blockers or open questions
7. Confirm with the user: "Memory updated. Safe to close."

## ADR format (for references/decisions.md)
### ADR-[NNN]: [short title] — [YYYY-MM-DD]
- **Decision**: What was chosen
- **Why**: The reasoning
- **Alternatives rejected**: What else was considered
- **Consequences**: What this means going forward

## Bug log format (for references/bugs.md)
### BUG-[NNN]: [short title] — [YYYY-MM-DD]
- **Symptom**: What went wrong
- **Root cause**: Why it happened
- **Fix**: What was done to resolve it
- **Watch out for**: Any related risk to keep in mind
