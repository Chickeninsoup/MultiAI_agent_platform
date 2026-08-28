from __future__ import annotations

from src.execution_failure import ExecutionFailure, FailureCategory
from src.retry_decision import RetryDecision

_REASONS: dict[FailureCategory, str] = {
    FailureCategory.TEMPORARY_ERROR: (
        "transient failure - safe to retry as-is"
    ),
    FailureCategory.PLAN_ERROR: (
        "the step itself was wrong - retry skipped, needs repair/replan"
    ),
    FailureCategory.BLOCKED: (
        "retry skipped - requires external/human resolution"
    ),
    FailureCategory.FATAL: (
        "retry skipped - failure is unrecoverable"
    ),
}


class FailureRetryClassifier:
    """Answers "is this failure worth retrying at all," from its
    FailureCategory alone (5E-5B-1).

    Classification only - never loops, never calls an executor, never
    counts attempts. That is RetryManager's job, driven by
    RetryPolicy.max_attempts (src/retry_policy.py); this class doesn't
    know either of those exist. Kept separate on purpose: whether a
    failure category is worth another attempt is a fixed fact about
    the failure, not a runtime execution policy.
    """

    def should_retry(self, failure: ExecutionFailure) -> RetryDecision:
        retryable = failure.category is FailureCategory.TEMPORARY_ERROR

        return RetryDecision(
            retryable=retryable, reason=_REASONS[failure.category]
        )
