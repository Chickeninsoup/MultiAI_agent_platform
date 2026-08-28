from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.execution_failure import ExecutionFailure


class StepStatus(Enum):
    """Outcome states TaskScheduler can assign to one TaskStep.

    SKIPPED is distinct from FAILED: the step itself never ran because
    a dependency didn't succeed, versus the step ran and raised. Both
    are "not SUCCESS" for downstream dependency checks, but conflating
    them would lose why a step never produced output.
    """

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class StepExecutionResult:
    """Outcome of one TaskStep as dispatched by TaskScheduler.

    A workflow-level concept, not a dispatch-level one: TaskPlanExecutor
    still returns raw str / raises on failure, since it only knows how
    to send one step. Scheduler wraps each step's outcome in this so a
    failure in one wave member doesn't take down the ones that
    succeeded alongside it, and so a step skipped due to a failed
    dependency is distinguishable from one that actually ran.

    attempt distinguishes a first-try outcome from a retried one - a
    SUCCESS at attempt=2 means it failed once before working, which
    matters for later stages (5D-4E-4) even though nothing retries a
    step yet, so nothing ever produces an attempt other than 1 today.

    failure carries the classified reason behind a FAILED status
    (5E-5A-2) - error stays as the plain-string message Scheduler has
    always produced from `str(exc)`; failure is additive, not a
    replacement, so existing FAILED results (error set, failure None)
    remain valid. Nothing yet enforces status/failure agreeing with
    each other - that's deliberately left to a later validation step
    (5E-5A) once something downstream actually reads failure.
    """

    step_id: str
    status: StepStatus
    output: str | None = None
    error: str | None = None
    attempt: int = 1
    failure: ExecutionFailure | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "attempt": self.attempt,
            "failure": (
                self.failure.to_dict()
                if self.failure is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StepExecutionResult":
        failure_data = data.get("failure")

        return cls(
            step_id=data["step_id"],
            status=StepStatus(data["status"]),
            output=data.get("output"),
            error=data.get("error"),
            attempt=data.get("attempt", 1),
            failure=(
                ExecutionFailure.from_dict(failure_data)
                if failure_data is not None
                else None
            ),
        )
