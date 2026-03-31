"""Shared pytest fixtures and environment setup for all test suites.

Sets required env vars *before* any backend module is imported so that
``ChatAnthropic`` and other API clients initialise without failing.
``load_dotenv()`` in the agents does NOT override vars already set here
(python-dotenv's default behaviour).
"""

from __future__ import annotations

import os

# Provide fallback values so tests work without a real .env file present.
# When .env IS present (developer machine) the real keys are loaded instead
# via load_dotenv() — that's fine since all external calls are mocked anyway.
_DEFAULTS = {
    "ANTHROPIC_API_KEY": "test-anthropic-key",
    "ANTHROPIC_MODEL": "claude-sonnet-4-20250514",
    "LANGSMITH_API_KEY": "test-langsmith-key",
    "TAVILY_API_KEY": "test-tavily-key",
    "SPOONACULAR_API_KEY": "test-spoonacular-key",
    "LANGSMITH_PROJECT": "pantry-to-plate-test",
    "LANGCHAIN_TRACING_V2": "false",
}

for _key, _val in _DEFAULTS.items():
    os.environ.setdefault(_key, _val)

# Import the full graph module here so Python's module cache is fully populated
# before any individual agent module is imported by a test file.  Without this,
# importing e.g. ``backend.agents.parser_agent`` directly triggers a circular
# import (parser_agent → base → graph → parser_agent is still being initialised).
import backend.graph  # noqa: F401, E402
