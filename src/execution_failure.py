from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FailureCategory(Enum):
    """How a StepExecutionResult's failure should eventually be
    handled - the classification RecoveryManager (5E-5B+) will read to
    decide retry/repair/replan/human-approval. Defined now, ahead of
    that decision logic, so ExecutionFailure has a fixed vocabulary
    instead of a free-text reason from the start.

    TEMPORARY_ERROR - transient, likely to succeed if retried as-is:
    network timeout, API unavailable, rate limit, transient tool
    failure.

    PLAN_ERROR - the step itself was wrong, not just unlucky: invalid
    arguments, wrong agent assignment, missing dependency. Retrying
    the same step won't help; the Plan needs to change.

    BLOCKED - execution cannot proceed without a decision only a human
    can make: permission denied, ambiguous requirement.

    FATAL - unrecoverable; execution must stop rather than attempt any
    automated recovery: corrupted state.
    """

    TEMPORARY_ERROR = "temporary_error"
    PLAN_ERROR = "plan_error"
    BLOCKED = "blocked"
    FATAL = "fatal"


@dataclass(frozen=True)
class ExecutionFailure:
    """What went wrong during one step's execution, and how it's
    classified.

    Deliberately narrow (5E-5A-1): describes the failure, nothing
    else. It does not decide what happens next - that's
    RecoveryManager's job (5E-5B+), kept separate so this model stays
    reusable regardless of which recovery strategy ends up reading it.
    step_id is optional because not every failure this will eventually
    describe is step-scoped (a Plan- or Run-level failure has no
    single originating step).
    """

    category: FailureCategory
    message: str
    step_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "message": self.message,
            "step_id": self.step_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionFailure":
        return cls(
            category=FailureCategory(data["category"]),
            message=data["message"],
            step_id=data.get("step_id"),
        )
