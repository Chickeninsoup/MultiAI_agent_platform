from __future__ import annotations

from dataclasses import dataclass, field

from src.planning.validation_error import ValidationError


@dataclass(frozen=True)
class PlanValidationResult:
    """Outcome of checking a TaskPlan against what can actually run.

    errors and warnings are separate from a plain valid bool because
    Human Review (5D-5D) needs to show *why* a plan failed, not just
    that it did. warnings are non-blocking - valid can be True while
    warnings is non-empty; nothing produces a warning yet, but the
    field exists so a future rule (e.g. "this agent is expensive")
    doesn't need a result-shape change to add one.

    errors is list[ValidationError] (5E-3A), not list[str] - each
    error now carries a code and whether it's repairable, so a
    downstream RepairDecisionService can tell "wrong agent name,
    worth asking the Planner to retry" from "no plan could ever fix
    this." error_messages() exists purely so callers that only ever
    wanted the human-readable text (PlanReviewService's summary) don't
    need to know ValidationError exists.
    """

    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def repairable(self) -> bool:
        return any(error.repairable for error in self.errors)

    def error_messages(self) -> list[str]:
        return [error.message for error in self.errors]
