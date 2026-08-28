from __future__ import annotations

import dataclasses
from typing import Protocol

from src.failure_retry_classifier import FailureRetryClassifier
from src.retry_policy import RetryPolicy
from src.retry_result import RetryResult
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_plan import TaskStep


class RetryableExecutor(Protocol):
    """A single-attempt step runner RetryManager can call repeatedly.

    Deliberately a StepExecutionResult-returning contract (never
    raises) - this is a different, higher-level shape than
    TaskPlanExecutor.execute_step() (raw str, raises on failure).
    TaskScheduler is the one place that bridges the two, so
    TaskPlanExecutor itself stays untouched.
    """

    def execute_step(
        self, step: TaskStep, task_id: str
    ) -> StepExecutionResult:
        ...


class RetryManager:
    """Retries a single step per RetryPolicy - nothing else's job.

    Scheduler decides *when* a step is eligible to run (dependencies,
    wave ordering) and never loops itself; the executor it's handed
    only knows how to make *one* attempt. This class is the only
    place "try again" logic lives, so neither of those two has to.

    failure_retry_classifier is a required dependency, not an
    internally-created default (5E-5B-4) - "should this failure be
    retried at all" is a policy decision (FailureRetryClassifier's
    only job), and RetryManager stays deliberately ignorant of
    FailureCategory itself: it only ever reads
    RetryDecision.retryable, never a category, so classification
    logic lives in exactly one place. RetryPolicy.max_attempts and
    FailureRetryClassifier answer two different questions - "how many
    times is this worth trying" vs. "is this failure worth trying
    again at all" - and neither can override the other: a FATAL
    failure never retries no matter how high max_attempts is, and a
    retryable TEMPORARY_ERROR still stops once max_attempts is
    exhausted.

    A FAILED result with failure=None (nothing classified it) is
    treated as not retryable, the same as an explicitly non-retryable
    category - retrying an unclassified failure is exactly the blind
    retry this whole chain (5E-5A/5E-5B) exists to replace.
    """

    def __init__(
        self,
        policy: RetryPolicy,
        failure_retry_classifier: FailureRetryClassifier,
    ) -> None:
        self._policy = policy
        self._failure_retry_classifier = failure_retry_classifier

    def execute(
        self,
        step: TaskStep,
        executor: RetryableExecutor,
        task_id: str,
    ) -> RetryResult:
        attempt = 1

        while True:
            result = executor.execute_step(step, task_id)

            if not self._should_retry(result, attempt):
                final_result = dataclasses.replace(
                    result, attempt=attempt
                )

                return RetryResult(
                    attempts=attempt, final_result=final_result
                )

            attempt += 1

    def _should_retry(
        self, result: StepExecutionResult, attempt: int
    ) -> bool:
        if result.status == StepStatus.SUCCESS:
            return False

        if result.failure is None:
            return False

        if not self._failure_retry_classifier.should_retry(
            result.failure
        ).retryable:
            return False

        return attempt < self._policy.max_attempts
