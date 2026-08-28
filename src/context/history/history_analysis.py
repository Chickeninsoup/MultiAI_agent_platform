from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HistoryAnalysis:
    """A read-only measurement of one round's message history.

    Observe-first (5D-6B-4A): just counts and a size estimate, no
    compressible_messages/importance/summary fields yet. Compacting
    history risks silently dropping a tool result, a system
    instruction, or the current task's own context - that decision
    needs its own stage (5D-6B-4B) once this analyzer has proven it
    can see the history accurately, not before.
    """

    total_messages: int
    estimated_tokens: int
    tool_messages: int
