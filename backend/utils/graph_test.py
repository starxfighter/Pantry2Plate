"""End-to-end smoke test for the compiled LangGraph pipeline.

Starts all MCP servers, invokes the full graph with a realistic ingredient
input, prints the final state, and asserts the key output invariants.

Run with:
    python backend/utils/graph_test.py
"""

from __future__ import annotations

import asyncio
import json
import time


async def main() -> None:
    # Import here so dotenv is loaded before any module-level client init.
    from backend.graph import CONFIG_TEMPLATE, graph
    from backend.utils.mcp_manager import MCPServerManager

    manager = MCPServerManager()

    print("Starting MCP servers...")
    await manager.start_all()
    print(f"MCP servers running: {manager.is_running}\n")

    initial_state = {
        "session_id": "test-001",
        "raw_input": (
            "I have eggs, cheddar cheese, leftover rotisserie chicken, "
            "cream cheese, and pasta"
        ),
        "filters": {},
        "parsed_ingredients": [],
        "parse_error": None,
        "search_results": [],
        "search_error": None,
        "scored_recipes": [],
        "langsmith_run_url": None,
        "current_step": "start",
        "start_time": time.time(),
    }

    config = {**CONFIG_TEMPLATE, "configurable": {"thread_id": "test-001"}}

    print("Invoking graph...")
    print(f"Input: {initial_state['raw_input']!r}\n")

    final_state = await graph.ainvoke(initial_state, config=config)

    # --- Pretty-print final state ---
    printable = {
        k: v for k, v in final_state.items()
        if k not in ("search_results",)  # omit verbose intermediate results
    }
    print("=" * 60)
    print("FINAL STATE")
    print("=" * 60)
    print(json.dumps(printable, indent=2, default=str))
    print()

    # --- Assertions ---
    failures: list[str] = []

    parsed = final_state.get("parsed_ingredients") or []
    if not isinstance(parsed, list) or len(parsed) == 0:
        failures.append(
            f"parsed_ingredients should be a non-empty list, got: {parsed!r}"
        )

    scored = final_state.get("scored_recipes") or []
    if len(scored) < 1:
        failures.append(
            f"scored_recipes should have >= 1 item, got {len(scored)}"
        )

    for i, recipe in enumerate(scored):
        score = recipe.get("match_score")
        if score is None or score < 0:
            failures.append(
                f"scored_recipes[{i}].match_score should be >= 0, got: {score!r}"
            )

    run_url = final_state.get("langsmith_run_url") or ""
    if not isinstance(run_url, str) or not run_url:
        failures.append(
            f"langsmith_run_url should be a non-empty string, got: {run_url!r}"
        )

    step = final_state.get("current_step")
    if step != "done":
        failures.append(
            f"current_step should be 'done', got: {step!r}"
        )

    print("=" * 60)
    print("ASSERTIONS")
    print("=" * 60)
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        print()
    else:
        print(f"  parsed_ingredients : {len(parsed)} ingredient(s) — PASS")
        print(f"  scored_recipes     : {len(scored)} recipe(s) — PASS")
        top = scored[0] if scored else {}
        print(f"  top match_score    : {top.get('match_score', 'n/a')} — PASS")
        print(f"  langsmith_run_url  : {run_url[:60]}... — PASS")
        print(f"  current_step       : {step!r} — PASS")
        print()
        print("All assertions passed.")

    await manager.stop_all()
    print("MCP servers stopped.")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
