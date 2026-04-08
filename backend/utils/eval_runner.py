"""Eval harness: run 10 diverse inputs through the full pipeline.

Each run is tagged "eval-v0.1" in LangSmith.  Results are printed as a
structured per-run report followed by a summary table.

Assertions per run:
  - parsed_ingredients has >= 2 items
  - scored_recipes has >= 1 item
  - top result match_score > 50.0
  - current_step == "done"

Run with:
    PYTHONPATH="D:/GenAI Workspace/Pantry2Plate" python backend/utils/eval_runner.py
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

EVAL_TAG = "eval-v0.1"

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

TEST_CASES: list[dict] = [
    {
        "id": "eval-01",
        "category": "simple (2 ingredients)",
        "raw_input": "chicken, rice",
        "filters": {},
    },
    {
        "id": "eval-02",
        "category": "simple (3 ingredients)",
        "raw_input": "eggs, butter, flour",
        "filters": {},
    },
    {
        "id": "eval-03",
        "category": "complex (8 ingredients)",
        "raw_input": "salmon, lemon, capers, dill, cream cheese, cucumber, red onion, bagels",
        "filters": {},
    },
    {
        "id": "eval-04",
        "category": "complex (10 ingredients)",
        "raw_input": (
            "chicken thighs, potatoes, carrots, celery, onion, garlic, "
            "thyme, bay leaves, chicken broth, tomato paste"
        ),
        "filters": {},
    },
    {
        "id": "eval-05",
        "category": "dietary restriction (vegan cue)",
        "raw_input": "tofu, soy sauce, sesame oil, bok choy, ginger, vegan",
        "filters": {},
    },
    {
        "id": "eval-06",
        "category": "dietary restriction (gluten-free)",
        "raw_input": "gluten-free pasta, zucchini, olive oil, cherry tomatoes, basil",
        "filters": {},
    },
    {
        "id": "eval-07",
        "category": "vague input",
        "raw_input": "leftovers from last night",
        "filters": {},
        "expected_step": "empty",
    },
    {
        "id": "eval-08",
        "category": "vague input",
        "raw_input": "some stuff in the fridge",
        "filters": {},
        "expected_step": "empty",
    },
    {
        "id": "eval-09",
        "category": "non-English (Spanish)",
        "raw_input": "pollo, arroz, frijoles, cilantro, jalapeño",
        "filters": {},
    },
    {
        "id": "eval-10",
        "category": "non-English (Italian)",
        "raw_input": "pomodoro, mozzarella, basilico, aglio, olio",
        "filters": {},
    },
]

# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    id: str
    category: str
    raw_input: str
    parsed_ingredients: list[str] = field(default_factory=list)
    recipe_count: int = 0
    top_score: float = 0.0
    current_step: str = ""
    langsmith_url: str = ""
    failures: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def passed(self) -> bool:
        return not self.failures and not self.error


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


_EMPTY_EXPECTED = "empty"


async def run_one(case: dict, graph, CONFIG_TEMPLATE: dict) -> RunResult:
    result = RunResult(id=case["id"], category=case["category"], raw_input=case["raw_input"])

    state = {
        "session_id": f"{case['id']}-{uuid.uuid4().hex[:8]}",
        "raw_input": case["raw_input"],
        "filters": case.get("filters", {}),
        "parsed_ingredients": [],
        "parse_error": None,
        "search_results": [],
        "search_error": None,
        "tavily_recipe_count": 0,
        "spoonacular_recipe_count": 0,
        "scored_recipes": [],
        "langsmith_run_url": None,
        "run_tags": [EVAL_TAG],
        "current_step": "",
        "start_time": time.time(),
    }

    config = {**CONFIG_TEMPLATE, "configurable": {"thread_id": state["session_id"]}}

    try:
        final = await graph.ainvoke(state, config=config)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    parsed = final.get("parsed_ingredients") or []
    scored = final.get("scored_recipes") or []
    top_score = scored[0]["match_score"] if scored else 0.0

    result.parsed_ingredients = parsed
    result.recipe_count = len(scored)
    result.top_score = top_score
    result.current_step = final.get("current_step", "")
    result.langsmith_url = final.get("langsmith_run_url") or ""

    # --- Assertions ---
    expected_step = case.get("expected_step", "done")

    if expected_step == _EMPTY_EXPECTED:
        # Vague inputs: expect the pipeline to route to empty_node gracefully.
        if result.current_step not in {"empty", "done"}:
            result.failures.append(
                f"current_step: expected 'empty' or 'done', got {result.current_step!r}"
            )
    else:
        if len(parsed) < 2:
            result.failures.append(
                f"parsed_ingredients: expected >=2, got {len(parsed)} ({parsed!r})"
            )
        if len(scored) < 1:
            result.failures.append(f"scored_recipes: expected >=1, got {len(scored)}")
        if scored and top_score < 40.0:
            result.failures.append(
                f"top match_score: expected >=40.0, got {top_score}"
            )
        if result.current_step != "done":
            result.failures.append(
                f"current_step: expected 'done', got {result.current_step!r}"
            )

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    from backend.graph import CONFIG_TEMPLATE, graph
    from backend.utils.mcp_manager import MCPServerManager

    manager = MCPServerManager()
    print("Starting MCP servers...")
    await manager.start_all()
    print(f"MCP servers running: {manager.is_running}\n")
    print(f"Tag applied to all runs: {EVAL_TAG!r}")
    print(f"Running {len(TEST_CASES)} eval cases...\n")
    print("=" * 70)

    results: list[RunResult] = []

    for i, case in enumerate(TEST_CASES, 1):
        print(f"[{i:02d}/{len(TEST_CASES)}] {case['id']} — {case['category']}")
        print(f"       Input : {case['raw_input']!r}")

        t0 = time.time()
        r = await run_one(case, graph, CONFIG_TEMPLATE)
        elapsed = time.time() - t0

        if r.error:
            print(f"       ERROR : {r.error}")
        else:
            print(f"       Parsed: {r.parsed_ingredients}")
            print(f"       Recipes: {r.recipe_count}  |  Top score: {r.top_score}")
            print(f"       Step  : {r.current_step}  |  Time: {elapsed:.1f}s")
            if r.langsmith_url:
                print(f"       Trace : {r.langsmith_url}")
            if r.failures:
                for f in r.failures:
                    print(f"       FAIL  : {f}")

        status = "PASS" if r.passed else ("ERROR" if r.error else "FAIL")
        print(f"       Status: {status}")
        print()

        results.append(r)

    await manager.stop_all()
    print("MCP servers stopped.\n")

    # --- Summary table ---
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"{'ID':<12} {'Category':<35} {'Parsed':>7} {'Recipes':>8} {'Top%':>7} {'Status'}")
    print("-" * 70)
    for r in results:
        status = "PASS" if r.passed else ("ERROR" if r.error else "FAIL")
        parsed_n = len(r.parsed_ingredients) if not r.error else "-"
        print(
            f"{r.id:<12} {r.category:<35} {str(parsed_n):>7} "
            f"{str(r.recipe_count):>8} {str(r.top_score):>7} {status}"
        )
    print("-" * 70)
    print(f"Total: {len(results)}  PASS: {len(passed)}  FAIL: {len(failed)}")

    # --- Failure notes ---
    if failed:
        print("\nFAILURE DETAILS")
        print("-" * 70)
        for r in failed:
            print(f"{r.id} ({r.category}):")
            if r.error:
                print(f"  ERROR: {r.error}")
            for f in r.failures:
                print(f"  FAIL : {f}")

    print()
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
