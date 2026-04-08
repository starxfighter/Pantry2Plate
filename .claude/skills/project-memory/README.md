# Project Memory Skill — Setup & Usage
**Pantry-to-Recipe App**

---

## What this skill does

The `project-memory` skill gives Claude Code persistent memory across sessions. At the start of each session Claude reads your state files and briefs you on where things stand. At the end of each session it updates those files before you close. No more re-explaining context every time.

---

## Installation

Drop the `.claude/` folder into your project root:

```
pantry-recipe/
└── .claude/
    └── skills/
        └── project-memory/
            ├── SKILL.md
            ├── references/
            │   ├── progress.md   ← session state & resume point
            │   ├── context.md    ← stack, ports, conventions
            │   ├── todo.md       ← prioritized task list
            │   ├── decisions.md  ← architecture decision records
            │   └── bugs.md       ← bug log
            └── scripts/
                └── init_memory.sh
```

---

## First session

**1. Run the bootstrap check** to confirm all memory files are in place:

```bash
bash .claude/skills/project-memory/scripts/init_memory.sh
```

**2. Open Claude Code** in your project root and type:

```
/project-memory
```

Claude will read the state files, summarize the project, and ask if you're ready to begin.

**3. Answer the three open questions** already seeded in `references/progress.md` — your answers will drive your first architecture decisions:

- Which recipe data source will you use? (local static JSON, an open API like Spoonacular, or scraped data?)
- Will ingredient matching be fuzzy (e.g. "tomatoes" matches "cherry tomatoes") or exact?
- Is authentication required, or is this a single-user local-only app?

---

## Every session after that

Just type `/project-memory` when you open Claude Code. Claude will automatically:

1. Read `progress.md`, `context.md`, and `todo.md`
2. Summarize what was completed last session and where you left off
3. Confirm the priorities for today
4. Ask if you're ready to continue

---

## During a session

Claude will update memory files as work happens — you don't need to manage this manually. Specifically:

| Event | File updated |
|---|---|
| Architecture or design decision made | `references/decisions.md` |
| Bug found and fixed | `references/bugs.md` |
| Port, env variable, or config confirmed | `references/context.md` |
| Todo item completed | `references/todo.md` |

---

## End of session

Before closing, Claude will:

1. Update `references/progress.md` with a clear **Resume here** line at the top
2. Move completed items to the done section with today's date
3. Reprioritize `references/todo.md` if needed
4. Note any open blockers or questions
5. Confirm: *"Memory updated. Safe to close."*

---

## Reference file guide

### `references/progress.md`
The living session log. The **Resume here** line at the top is the most important thing in the whole skill — it's what gets Claude oriented in under 30 seconds at the start of every session.

### `references/context.md`
Stable facts that don't change often: tech stack, ports, installed package versions, environment variables, and coding conventions. Update it the moment something is confirmed, not at session end.

### `references/todo.md`
Three tiers: **Now** (this session's focus), **Up next** (coming sessions), and **Backlog** (future ideas). Reprioritize at the start of each session.

### `references/decisions.md`
Architecture Decision Records (ADRs). Log any choice that would be hard or costly to reverse — framework selection, data source, matching strategy, state management approach. Small implementation details don't need an ADR.

### `references/bugs.md`
Bug log with root cause and fix. Patterns here prevent recurrence and give future sessions useful diagnostic context.

---

## Tips

- **Keep `context.md` current** — stale port numbers or package versions will waste time at session start.
- **The "Resume here" line is everything** — if Claude writes a vague one at session end, ask it to be more specific before closing.
- **Commit `.claude/skills/` to git** — this keeps memory in sync if you work across machines or want a history of decisions.
- **Don't put secrets in `context.md`** — reference `.env` variable names only, never values.
