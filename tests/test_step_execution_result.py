from __future__ import annotations

import dataclasses

import pytest

from src.execution_failure import ExecutionFailure, FailureCategory
from src.step_execution_result import StepExecutionResult, StepStatus


def test_success_result_holds_step_id_and_output() -> None:
    result = StepExecutionResult(
        step_id="step-1", status=StepStatus.SUCCESS, output="done"
    )

    assert result.step_id == "step-1"
    assert result.status == StepStatus.SUCCESS
    assert result.output == "done"
    assert result.error is None


def test_failed_result_holds_step_id_and_error() -> None:
    result = StepExecutionResult(
        step_id="step-1", status=StepStatus.FAILED, error="LLM timeout"
    )

    assert result.status == StepStatus.FAILED
    assert result.error == "LLM timeout"
    assert result.output is None


def test_skipped_result_is_distinct_from_failed() -> None:
    result = StepExecutionResult(
        step_id="step-2",
        status=StepStatus.SKIPPED,
        error="dependency 'step-1' did not succeed",
    )

    assert result.status == StepStatus.SKIPPED
    assert result.status != StepStatus.FAILED


def test_attempt_defaults_to_one() -> None:
    result = StepExecutionResult(
        step_id="step-1", status=StepStatus.SUCCESS
    )

    assert result.attempt == 1


def test_attempt_can_be_set_for_a_retried_step() -> None:
    result = StepExecutionResult(
        step_id="step-1",
        status=StepStatus.SUCCESS,
        output="done",
        attempt=2,
    )

    assert result.attempt == 2


def test_step_execution_result_is_frozen() -> None:
    result = StepExecutionResult(
        step_id="step-1", status=StepStatus.SUCCESS
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.status = StepStatus.FAILED


def test_success_result_defaults_failure_to_none() -> None:
    result = StepExecutionResult(
        step_id="step-1", status=StepStatus.SUCCESS
    )

    assert result.failure is None


def test_failed_result_holds_its_execution_failure() -> None:
    failure = ExecutionFailure(
        category=FailureCategory.TEMPORARY_ERROR,
        message="timeout",
        step_id="step-1",
    )

    result = StepExecutionResult(
        step_id="step-1", status=StepStatus.FAILED, failure=failure
    )

    assert result.failure == failure


def test_step_execution_result_and_its_failure_are_both_immutable() -> (
    None
):
    failure = ExecutionFailure(
        category=FailureCategory.FATAL, message="corrupted state"
    )
    result = StepExecutionResult(
        step_id="step-1", status=StepStatus.FAILED, failure=failure
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.failure = None

    with pytest.raises(dataclasses.FrozenInstanceError):
        failure.message = "changed"


@pytest.mark.parametrize(
    "category",
    [
        FailureCategory.TEMPORARY_ERROR,
        FailureCategory.PLAN_ERROR,
        FailureCategory.BLOCKED,
        FailureCategory.FATAL,
    ],
)
def test_any_failure_category_can_be_attached(
    category: FailureCategory,
) -> None:
    result = StepExecutionResult(
        step_id="step-1",
        status=StepStatus.FAILED,
        failure=ExecutionFailure(category=category, message="reason"),
    )

    assert result.failure is not None
    assert result.failure.category is category


def test_to_dict_and_from_dict_roundtrip_on_success() -> None:
    result = StepExecutionResult(
        step_id="step-1",
        status=StepStatus.SUCCESS,
        output="done",
        attempt=2,
    )

    assert StepExecutionResult.from_dict(result.to_dict()) == result


def test_to_dict_and_from_dict_roundtrip_with_failure() -> None:
    result = StepExecutionResult(
        step_id="step-1",
        status=StepStatus.FAILED,
        error="permission denied",
        failure=ExecutionFailure(
            category=FailureCategory.BLOCKED,
            message="permission denied",
            step_id="step-1",
        ),
    )

    assert StepExecutionResult.from_dict(result.to_dict()) == result
