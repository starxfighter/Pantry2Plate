"""
Smoke test — verifies all four external API connections are working.
Run from repo root: python backend/utils/smoke_test.py
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []  # (name, status, detail)


def check(name: str, fn) -> None:
    try:
        detail = fn()
        results.append((name, PASS, detail))
    except Exception as exc:
        results.append((name, FAIL, str(exc)))


# ── 1. Anthropic ──────────────────────────────────────────────────────────────
def _anthropic() -> str:
    import anthropic

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model=model,
        max_tokens=1,
        messages=[{"role": "user", "content": "ping"}],
    )
    return f"model={msg.model}  stop_reason={msg.stop_reason}"


check("Anthropic", _anthropic)


# ── 2. Tavily ─────────────────────────────────────────────────────────────────
def _tavily() -> str:
    from tavily import TavilyClient

    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        raise ValueError("TAVILY_API_KEY not set")
    client = TavilyClient(api_key=key)
    resp = client.search("quick egg recipe", max_results=1)
    n = len(resp.get("results", []))
    return f"results_returned={n}"


check("Tavily", _tavily)


# ── 3. Spoonacular ────────────────────────────────────────────────────────────
def _spoonacular() -> str:
    import httpx

    key = os.environ.get("SPOONACULAR_API_KEY", "")
    if not key:
        raise ValueError("SPOONACULAR_API_KEY not set")
    resp = httpx.get(
        "https://api.spoonacular.com/recipes/findByIngredients",
        params={"ingredients": "egg", "number": 1, "apiKey": key},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"unexpected response: {data}")
    title = data[0].get("title", "?") if data else "(no results)"
    return f"first_result='{title}'"


check("Spoonacular", _spoonacular)


# ── 4. LangSmith ──────────────────────────────────────────────────────────────
def _langsmith() -> str:
    from langsmith import Client

    key = os.environ.get("LANGSMITH_API_KEY", "")
    project = os.environ.get("LANGSMITH_PROJECT", "pantry-to-plate")
    if not key:
        raise ValueError("LANGSMITH_API_KEY not set")
    client = Client(api_key=key)
    # list_projects returns a generator; just pull the first page
    projects = list(client.list_projects())
    names = [p.name for p in projects]
    exists = project in names
    return f"project='{project}'  found={exists}  total_projects={len(names)}"


check("LangSmith", _langsmith)


# ── Results ───────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("  Smoke Test Results")
print("=" * 60)
width = max(len(n) for n, _, _ in results)
for name, status, detail in results:
    marker = "[ok]" if status == PASS else "[!!]"
    print(f"  {marker}  {name:<{width}}  {status}  {detail}")
print("=" * 60)

failed = [n for n, s, _ in results if s == FAIL]
if failed:
    print(f"\n  {len(failed)} check(s) failed: {', '.join(failed)}")
    sys.exit(1)
else:
    print(f"\n  All {len(results)} checks passed.")
print()
