from __future__ import annotations

import dataclasses

import pytest

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
