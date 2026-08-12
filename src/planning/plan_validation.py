from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlanValidationResult:
    """Outcome of checking a TaskPlan against what can actually run.

    errors and warnings are separate from a plain valid bool because
    Human Review (5D-5D) needs to show *why* a plan failed, not just
    that it did. warnings are non-blocking - valid can be True while
    warnings is non-empty; nothing produces a warning yet, but the
    field exists so a future rule (e.g. "this agent is expensive")
    doesn't need a result-shape change to add one.
    """

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
