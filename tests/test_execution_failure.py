from __future__ import annotations

import dataclasses

import pytest

from src.execution_failure import ExecutionFailure, FailureCategory


def test_execution_failure_stores_category_and_message() -> None:
    failure = ExecutionFailure(
        category=FailureCategory.TEMPORARY_ERROR,
        message="database timeout",
        step_id="step-3",
    )

    assert failure.category is FailureCategory.TEMPORARY_ERROR
    assert failure.message == "database timeout"
    assert failure.step_id == "step-3"


def test_execution_failure_is_frozen() -> None:
    failure = ExecutionFailure(
        category=FailureCategory.FATAL, message="corrupted state"
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        failure.message = "changed"


def test_execution_failure_step_id_is_optional_and_defaults_to_none() -> (
    None
):
    failure = ExecutionFailure(
        category=FailureCategory.BLOCKED, message="ambiguous requirement"
    )

    assert failure.step_id is None


def test_failure_category_has_four_distinct_values() -> None:
    assert {category.value for category in FailureCategory} == {
        "temporary_error",
        "plan_error",
        "blocked",
        "fatal",
    }
    assert len(set(FailureCategory)) == 4


def test_to_dict_and_from_dict_roundtrip() -> None:
    failure = ExecutionFailure(
        category=FailureCategory.BLOCKED,
        message="permission denied",
        step_id="step-3",
    )

    assert ExecutionFailure.from_dict(failure.to_dict()) == failure


def test_to_dict_and_from_dict_roundtrip_without_step_id() -> None:
    failure = ExecutionFailure(
        category=FailureCategory.FATAL, message="corrupted state"
    )

    assert ExecutionFailure.from_dict(failure.to_dict()) == failure
