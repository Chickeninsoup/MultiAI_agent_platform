from __future__ import annotations

import dataclasses

import pytest

from src.retry_result import RetryResult
from src.step_execution_result import StepExecutionResult, StepStatus


def test_creation() -> None:
    result = StepExecutionResult(
        step_id="step-1", status=StepStatus.SUCCESS, output="done"
    )

    retry = RetryResult(attempts=1, final_result=result)

    assert retry.attempts == 1
    assert retry.final_result is result


def test_frozen() -> None:
    retry = RetryResult(attempts=1, final_result=None)

    with pytest.raises(dataclasses.FrozenInstanceError):
        retry.attempts = 2


def test_attempts_reflects_a_retry() -> None:
    result = StepExecutionResult(
        step_id="step-1", status=StepStatus.SUCCESS, output="done"
    )

    retry = RetryResult(attempts=2, final_result=result)

    assert retry.attempts == 2
