from __future__ import annotations

import dataclasses

import pytest

from src.execution_failure import FailureCategory
from src.failure_classifier import FailureClassifier


class CustomError(Exception):
    pass


def test_timeout_error_is_temporary() -> None:
    classifier = FailureClassifier()

    failure = classifier.classify(TimeoutError("timeout"), "step-1")

    assert failure.category == FailureCategory.TEMPORARY_ERROR
    assert failure.step_id == "step-1"


def test_connection_error_is_temporary() -> None:
    classifier = FailureClassifier()

    failure = classifier.classify(ConnectionError("connection reset"))

    assert failure.category == FailureCategory.TEMPORARY_ERROR


def test_permission_error_is_blocked() -> None:
    classifier = FailureClassifier()

    failure = classifier.classify(PermissionError("access denied"))

    assert failure.category == FailureCategory.BLOCKED


def test_runtime_error_is_fatal() -> None:
    classifier = FailureClassifier()

    failure = classifier.classify(RuntimeError("invariant broken"))

    assert failure.category == FailureCategory.FATAL


def test_unknown_exception_defaults_to_fatal() -> None:
    classifier = FailureClassifier()

    failure = classifier.classify(CustomError("something unexpected"))

    assert failure.category == FailureCategory.FATAL


def test_message_is_preserved_from_the_exception() -> None:
    classifier = FailureClassifier()

    failure = classifier.classify(TimeoutError("provider unavailable"))

    assert failure.message == "provider unavailable"


def test_classified_failure_is_frozen() -> None:
    classifier = FailureClassifier()

    failure = classifier.classify(RuntimeError("boom"))

    with pytest.raises(dataclasses.FrozenInstanceError):
        failure.category = FailureCategory.TEMPORARY_ERROR


def test_step_id_defaults_to_none() -> None:
    classifier = FailureClassifier()

    failure = classifier.classify(TimeoutError("timeout"))

    assert failure.step_id is None
