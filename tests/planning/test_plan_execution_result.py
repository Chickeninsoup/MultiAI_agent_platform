from __future__ import annotations

from src.execution_failure import ExecutionFailure, FailureCategory
from src.planning.plan_execution_result import PlanExecutionResult
from src.step_execution_result import StepExecutionResult, StepStatus


def test_succeeds_when_all_steps_succeed() -> None:
    result = PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="step-1",
                status=StepStatus.SUCCESS,
                output="done",
            ),
            StepExecutionResult(
                step_id="step-2",
                status=StepStatus.SUCCESS,
                output="done",
            ),
        ]
    )

    assert result.succeeded is True


def test_fails_when_any_step_fails() -> None:
    result = PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="step-1",
                status=StepStatus.SUCCESS,
            ),
            StepExecutionResult(
                step_id="step-2",
                status=StepStatus.FAILED,
                error="failed",
            ),
        ]
    )

    assert result.succeeded is False


def test_fails_when_a_step_is_skipped() -> None:
    result = PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="step-1",
                status=StepStatus.SUCCESS,
            ),
            StepExecutionResult(
                step_id="step-2",
                status=StepStatus.SKIPPED,
                error="dependency failed",
            ),
        ]
    )

    assert result.succeeded is False


def test_preserves_step_results() -> None:
    step_results = [
        StepExecutionResult(
            step_id="step-1",
            status=StepStatus.SUCCESS,
            output="done",
        )
    ]

    result = PlanExecutionResult(step_results=step_results)

    assert result.step_results == step_results


def test_successful_execution_has_no_failures() -> None:
    result = PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="step-1", status=StepStatus.SUCCESS, output="done"
            ),
            StepExecutionResult(
                step_id="step-2", status=StepStatus.SUCCESS, output="done"
            ),
        ]
    )

    assert result.succeeded is True
    assert result.failures == []


def test_failed_execution_exposes_its_failure() -> None:
    failure = ExecutionFailure(
        category=FailureCategory.TEMPORARY_ERROR,
        message="timeout",
        step_id="step-1",
    )

    result = PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="step-1", status=StepStatus.FAILED, failure=failure
            )
        ]
    )

    assert result.failures == [failure]


def test_multiple_failures_preserve_step_results_order() -> None:
    plan_failure = ExecutionFailure(
        category=FailureCategory.PLAN_ERROR,
        message="invalid arguments",
        step_id="step-1",
    )
    blocked_failure = ExecutionFailure(
        category=FailureCategory.BLOCKED,
        message="permission denied",
        step_id="step-2",
    )

    result = PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="step-1",
                status=StepStatus.FAILED,
                failure=plan_failure,
            ),
            StepExecutionResult(
                step_id="step-2",
                status=StepStatus.FAILED,
                failure=blocked_failure,
            ),
        ]
    )

    assert result.failures[0].category == FailureCategory.PLAN_ERROR
    assert result.failures[1].category == FailureCategory.BLOCKED
    assert result.failures == [plan_failure, blocked_failure]


def test_skipped_steps_fail_the_plan_but_contribute_no_failure() -> None:
    result = PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="step-1", status=StepStatus.SUCCESS
            ),
            StepExecutionResult(
                step_id="step-2",
                status=StepStatus.SKIPPED,
                error="dependency failed",
            ),
        ]
    )

    assert result.succeeded is False
    assert result.failures == []


def test_failures_is_derived_and_does_not_mutate_step_results() -> None:
    failure = ExecutionFailure(
        category=FailureCategory.FATAL, message="corrupted state"
    )
    step_results = [
        StepExecutionResult(
            step_id="step-1", status=StepStatus.FAILED, failure=failure
        )
    ]

    result = PlanExecutionResult(step_results=step_results)
    result.failures.append(
        ExecutionFailure(
            category=FailureCategory.BLOCKED, message="unrelated"
        )
    )

    assert result.step_results == step_results
    assert result.failures == [failure]
