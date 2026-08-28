from __future__ import annotations

from dataclasses import dataclass

from src.execution_failure import ExecutionFailure
from src.step_execution_result import StepExecutionResult, StepStatus


@dataclass(frozen=True)
class PlanExecutionResult:
    """Whether an entire Plan's execution succeeded, derived from its steps.

    succeeded is a property, not a constructor field (5E-4C-1) -
    step_results is the source of truth, so there's no way to
    construct a result whose step_results and succeeded flag
    contradict each other. Any non-SUCCESS status (FAILED or SKIPPED)
    fails the whole plan; SKIPPED counts as a failure here for the
    same reason TaskScheduler already treats it as "not SUCCESS" for
    dependency-skip propagation - a step that never ran because its
    dependency failed is not a completed plan.

    failures (5E-5A-3) is the same kind of derived property: it
    answers "why did this fail" by collecting every step's
    ExecutionFailure, in step_results order. A SKIPPED step has no
    ExecutionFailure of its own (it never ran) and so contributes
    nothing here even though it makes succeeded False - failures is
    about classified execution failures, not every reason succeeded
    can be False.
    """

    step_results: list[StepExecutionResult]

    @property
    def succeeded(self) -> bool:
        return all(
            result.status == StepStatus.SUCCESS
            for result in self.step_results
        )

    @property
    def failures(self) -> list[ExecutionFailure]:
        return [
            result.failure
            for result in self.step_results
            if result.failure is not None
        ]
