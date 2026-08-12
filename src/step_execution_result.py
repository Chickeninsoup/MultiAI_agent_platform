from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
    """

    step_id: str
    status: StepStatus
    output: str | None = None
    error: str | None = None
    attempt: int = 1
