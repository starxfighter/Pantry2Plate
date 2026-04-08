"""Abstract base class for all Pantry-to-Plate pipeline agents.

Every agent in the pipeline inherits from ``BaseAgent`` and must implement:

* ``name`` — a human-readable identifier used in logs and traces.
* ``run(state)`` — the async entry point called by the LangGraph node function.

Contract enforced by this base:

* Subclasses must **never** let exceptions propagate out of ``run()``.  All
  errors must be caught and written to the appropriate ``AgentState`` error
  field (e.g. ``parse_error``, ``search_error``).
* ``_log_start`` / ``_log_end`` must be called at the top and bottom of every
  ``run()`` implementation to ensure consistent structured logging.

Environment variables:
    ANTHROPIC_MODEL: Model ID passed to ``ChatAnthropic``.
        Defaults to ``"claude-sonnet-4-20250514"``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

from backend.graph import AgentState

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-sonnet-4-20250514"


class BaseAgent(ABC):
    """Abstract base for all pipeline agents.

    Subclasses pass ``temperature`` to ``__init__`` and implement the
    ``name`` property and ``run()`` method.  The ``model`` attribute is
    configured once during construction from environment variables and is
    ready to use in ``run()`` without further setup.

    Args:
        temperature: Sampling temperature forwarded to ``ChatAnthropic``.
            Use ``0.0`` for deterministic agents (parser, scorer) and a small
            positive value for agents that benefit from slight variation
            (search).
    """

    def __init__(self, temperature: float = 0.0) -> None:
        model_id = os.getenv("ANTHROPIC_MODEL", _DEFAULT_MODEL)
        self.model: ChatAnthropic = ChatAnthropic(
            model=model_id,
            temperature=temperature,
        )

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable agent identifier used in logs and LangSmith traces.

        Returns:
            A short snake_case string, e.g. ``"parser_agent"``.
        """

    @abstractmethod
    async def run(self, state: AgentState) -> AgentState:
        """Execute the agent's logic against the current pipeline state.

        Implementations must:

        1. Call ``_log_start(state)`` before any processing.
        2. Wrap all logic in a ``try/except`` block.
        3. On success, write outputs to the appropriate state fields.
        4. On failure, write a descriptive message to the appropriate error
           field and leave output fields at their default values.
        5. Call ``_log_end(state, duration_ms)`` before returning in both
           the success and failure paths.
        6. **Never raise** — exceptions must not propagate to the graph.

        Args:
            state: The shared ``AgentState`` dict for the current pipeline run.

        Returns:
            The updated ``AgentState`` dict.
        """

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log_start(self, state: AgentState) -> None:
        """Emit a structured JSON log record at the start of a run.

        Args:
            state: Current pipeline state; ``session_id`` and ``current_step``
                are extracted for the log record.
        """
        logger.info(
            json.dumps(
                {
                    "event": "agent_start",
                    "agent": self.name,
                    "session_id": state.get("session_id"),
                    "current_step": state.get("current_step"),
                    "timestamp": time.time(),
                }
            )
        )

    def _log_end(self, state: AgentState, duration_ms: float) -> None:
        """Emit a structured JSON log record at the end of a run.

        Args:
            state: Current pipeline state after the agent has written its
                outputs; used to capture ``current_step`` in the final record.
            duration_ms: Wall-clock time the agent took to complete, in
                milliseconds.
        """
        logger.info(
            json.dumps(
                {
                    "event": "agent_end",
                    "agent": self.name,
                    "session_id": state.get("session_id"),
                    "current_step": state.get("current_step"),
                    "duration_ms": round(duration_ms, 2),
                    "timestamp": time.time(),
                }
            )
        )

    # ------------------------------------------------------------------
    # Timing helper
    # ------------------------------------------------------------------

    @staticmethod
    def _now_ms() -> float:
        """Return the current time as a Unix timestamp in milliseconds.

        Returns:
            Current ``time.time()`` multiplied by 1000.
        """
        return time.time() * 1000
