from __future__ import annotations

import dataclasses

import pytest

from src.execution_failure import ExecutionFailure, FailureCategory
from src.failure_retry_classifier import FailureRetryClassifier
from src.retry_decision import RetryDecision


def test_temporary_error_is_retryable() -> None:
    classifier = FailureRetryClassifier()
    failure = ExecutionFailure(
        category=FailureCategory.TEMPORARY_ERROR, message="API timeout"
    )

    decision = classifier.should_retry(failure)

    assert decision.retryable is True


def test_plan_error_is_not_retryable() -> None:
    classifier = FailureRetryClassifier()
    failure = ExecutionFailure(
        category=FailureCategory.PLAN_ERROR, message="invalid arguments"
    )

    decision = classifier.should_retry(failure)

    assert decision.retryable is False


def test_blocked_is_not_retryable() -> None:
    classifier = FailureRetryClassifier()
    failure = ExecutionFailure(
        category=FailureCategory.BLOCKED, message="permission denied"
    )

    decision = classifier.should_retry(failure)

    assert decision.retryable is False


def test_fatal_is_not_retryable() -> None:
    classifier = FailureRetryClassifier()
    failure = ExecutionFailure(
        category=FailureCategory.FATAL, message="corrupted state"
    )

    decision = classifier.should_retry(failure)

    assert decision.retryable is False


@pytest.mark.parametrize("category", list(FailureCategory))
def test_reason_is_always_populated(category: FailureCategory) -> None:
    classifier = FailureRetryClassifier()
    failure = ExecutionFailure(category=category, message="reason")

    decision = classifier.should_retry(failure)

    assert decision.reason != ""


def test_retry_decision_is_frozen() -> None:
    decision = RetryDecision(retryable=True, reason="transient")

    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.retryable = False
