from __future__ import annotations

from src.execution_failure import ExecutionFailure, FailureCategory


class FailureClassifier:
    """Turns a caught Exception into a classified ExecutionFailure
    (5E-5B-3A) - the entry point real execution failures take into the
    Failure domain, previously nonexistent (the only ExecutionFailures
    in the system were hand-built by tests).

    A fixed, deliberately small type->category mapping rather than an
    exhaustive one: TimeoutError/ConnectionError (transient, safe to
    retry as-is) and PermissionError (needs external resolution, not a
    retry) are the two cases worth distinguishing today.
    RuntimeError, and anything else this doesn't recognize, defaults
    to FATAL - not PLAN_ERROR - because an unclassified exception
    means this classifier doesn't yet understand what went wrong, and
    assuming "safe to keep going, just needs a repaired plan" about an
    unknown failure is a worse default than stopping. Widen this
    mapping deliberately as new failure types are understood, not by
    guessing.

    Never touches TaskScheduler/RetryManager/StepExecutionResult
    (5E-5B-3A scope) - this only knows Exception in, ExecutionFailure
    out.
    """

    def classify(
        self, exc: Exception, step_id: str | None = None
    ) -> ExecutionFailure:
        return ExecutionFailure(
            category=self._category_for(exc),
            message=str(exc),
            step_id=step_id,
        )

    def _category_for(self, exc: Exception) -> FailureCategory:
        if isinstance(exc, (TimeoutError, ConnectionError)):
            return FailureCategory.TEMPORARY_ERROR

        if isinstance(exc, PermissionError):
            return FailureCategory.BLOCKED

        if isinstance(exc, RuntimeError):
            return FailureCategory.FATAL

        return FailureCategory.FATAL
