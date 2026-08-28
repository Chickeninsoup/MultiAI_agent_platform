from __future__ import annotations

from src.execution_failure import ExecutionFailure, FailureCategory
from src.failure_retry_classifier import FailureRetryClassifier
from src.retry_manager import RetryManager
from src.retry_policy import RetryPolicy
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_plan import TaskStep


class FakeExecutor:
    def __init__(self, results: list[StepExecutionResult]) -> None:
        self.results = results
        self.calls = 0

    def execute_step(
        self, step: TaskStep, task_id: str
    ) -> StepExecutionResult:
        result = self.results[self.calls]
        self.calls += 1

        return result


def _step(step_id: str = "a") -> TaskStep:
    return TaskStep(
        step_id=step_id, agent_id="agent-coder", description="do it"
    )


def _manager(max_attempts: int = 1) -> RetryManager:
    return RetryManager(
        RetryPolicy(max_attempts=max_attempts), FailureRetryClassifier()
    )


def _failed(
    category: FailureCategory, error: str = "boom"
) -> StepExecutionResult:
    return StepExecutionResult(
        step_id="a",
        status=StepStatus.FAILED,
        error=error,
        failure=ExecutionFailure(
            category=category, message=error, step_id="a"
        ),
    )


def test_success_first_attempt() -> None:
    executor = FakeExecutor(
        [
            StepExecutionResult(
                step_id="a", status=StepStatus.SUCCESS, output="ok"
            )
        ]
    )
    manager = _manager(max_attempts=3)

    result = manager.execute(_step(), executor, "task")

    assert result.attempts == 1
    assert result.final_result.status == StepStatus.SUCCESS
    assert executor.calls == 1


def test_retry_after_failure() -> None:
    executor = FakeExecutor(
        [
            _failed(FailureCategory.TEMPORARY_ERROR, error="network"),
            StepExecutionResult(
                step_id="a", status=StepStatus.SUCCESS, output="ok"
            ),
        ]
    )
    manager = _manager(max_attempts=3)

    result = manager.execute(_step(), executor, "task")

    assert result.attempts == 2
    assert result.final_result.status == StepStatus.SUCCESS
    assert executor.calls == 2


def test_failure_after_max_attempts() -> None:
    executor = FakeExecutor(
        [_failed(FailureCategory.TEMPORARY_ERROR)] * 3
    )
    manager = _manager(max_attempts=3)

    result = manager.execute(_step(), executor, "task")

    assert result.attempts == 3
    assert result.final_result.status == StepStatus.FAILED
    assert executor.calls == 3


def test_default_policy_runs_once() -> None:
    executor = FakeExecutor([_failed(FailureCategory.TEMPORARY_ERROR)])
    manager = RetryManager(RetryPolicy(), FailureRetryClassifier())

    result = manager.execute(_step(), executor, "task")

    assert result.attempts == 1
    assert executor.calls == 1


def test_final_result_attempt_field_matches_attempts_count() -> None:
    executor = FakeExecutor(
        [
            _failed(FailureCategory.TEMPORARY_ERROR, error="boom"),
            StepExecutionResult(
                step_id="a", status=StepStatus.SUCCESS, output="ok"
            ),
        ]
    )
    manager = _manager(max_attempts=3)

    result = manager.execute(_step(), executor, "task")

    assert result.final_result.attempt == 2
    assert result.final_result.attempt == result.attempts


def test_does_not_retry_past_max_attempts_even_if_more_results_exist() -> (
    None
):
    executor = FakeExecutor(
        [
            _failed(FailureCategory.TEMPORARY_ERROR),
            StepExecutionResult(
                step_id="a", status=StepStatus.SUCCESS, output="ok"
            ),
        ]
    )
    manager = _manager(max_attempts=1)

    result = manager.execute(_step(), executor, "task")

    assert result.attempts == 1
    assert result.final_result.status == StepStatus.FAILED
    assert executor.calls == 1


def test_temporary_error_is_retried_until_success() -> None:
    executor = FakeExecutor(
        [
            _failed(FailureCategory.TEMPORARY_ERROR),
            StepExecutionResult(
                step_id="a", status=StepStatus.SUCCESS, output="ok"
            ),
        ]
    )
    manager = _manager(max_attempts=3)

    result = manager.execute(_step(), executor, "task")

    assert result.attempts == 2
    assert result.final_result.status == StepStatus.SUCCESS


def test_plan_error_is_not_retried() -> None:
    executor = FakeExecutor(
        [
            _failed(FailureCategory.PLAN_ERROR),
            StepExecutionResult(
                step_id="a", status=StepStatus.SUCCESS, output="ok"
            ),
        ]
    )
    manager = _manager(max_attempts=3)

    result = manager.execute(_step(), executor, "task")

    assert result.attempts == 1
    assert result.final_result.status == StepStatus.FAILED
    assert executor.calls == 1


def test_blocked_is_not_retried() -> None:
    executor = FakeExecutor(
        [
            _failed(FailureCategory.BLOCKED),
            StepExecutionResult(
                step_id="a", status=StepStatus.SUCCESS, output="ok"
            ),
        ]
    )
    manager = _manager(max_attempts=3)

    result = manager.execute(_step(), executor, "task")

    assert result.attempts == 1
    assert result.final_result.status == StepStatus.FAILED
    assert executor.calls == 1


def test_fatal_is_not_retried() -> None:
    executor = FakeExecutor(
        [
            _failed(FailureCategory.FATAL),
            StepExecutionResult(
                step_id="a", status=StepStatus.SUCCESS, output="ok"
            ),
        ]
    )
    manager = _manager(max_attempts=3)

    result = manager.execute(_step(), executor, "task")

    assert result.attempts == 1
    assert result.final_result.status == StepStatus.FAILED
    assert executor.calls == 1


def test_unclassified_failure_is_not_retried() -> None:
    """failure=None must never fall back to blind retry - this is the
    invariant that stops the 5E-5A/5E-5B chain from being bypassed."""

    executor = FakeExecutor(
        [
            StepExecutionResult(
                step_id="a", status=StepStatus.FAILED, error="unknown"
            ),
            StepExecutionResult(
                step_id="a", status=StepStatus.SUCCESS, output="ok"
            ),
        ]
    )
    manager = _manager(max_attempts=3)

    result = manager.execute(_step(), executor, "task")

    assert result.attempts == 1
    assert result.final_result.status == StepStatus.FAILED
    assert executor.calls == 1


def test_max_attempts_still_bounds_a_retryable_failure() -> None:
    """Classification decides *whether* to retry; RetryPolicy still
    decides *how many times* - a retryable TEMPORARY_ERROR that never
    succeeds must still stop at max_attempts."""

    executor = FakeExecutor(
        [_failed(FailureCategory.TEMPORARY_ERROR)] * 3
    )
    manager = _manager(max_attempts=3)

    result = manager.execute(_step(), executor, "task")

    assert result.attempts == 3
    assert result.final_result.status == StepStatus.FAILED
    assert executor.calls == 3
