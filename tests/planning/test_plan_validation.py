from __future__ import annotations

import dataclasses

import pytest

from src.planning.plan_validation import PlanValidationResult
from src.planning.validation_error import ValidationError


def test_valid_result_defaults_errors_and_warnings_to_empty() -> None:
    result = PlanValidationResult(valid=True)

    assert result.errors == []
    assert result.warnings == []


def test_invalid_result_can_carry_errors() -> None:
    error = ValidationError(
        code="UNKNOWN_AGENT",
        message="Unknown agent: agent-x",
        repairable=True,
    )

    result = PlanValidationResult(valid=False, errors=[error])

    assert result.valid is False
    assert result.errors == [error]


def test_plan_validation_result_is_frozen() -> None:
    result = PlanValidationResult(valid=True)

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.valid = False


def test_validation_detects_repairable() -> None:
    result = PlanValidationResult(
        valid=False,
        errors=[
            ValidationError(
                code="UNKNOWN_AGENT",
                message="bad agent",
                repairable=True,
            )
        ],
    )

    assert result.repairable is True


def test_validation_non_repairable() -> None:
    result = PlanValidationResult(
        valid=False,
        errors=[
            ValidationError(
                code="EMPTY", message="empty", repairable=False
            )
        ],
    )

    assert result.repairable is False


def test_repairable_is_false_when_there_are_no_errors() -> None:
    result = PlanValidationResult(valid=True)

    assert result.repairable is False


def test_repairable_is_true_if_any_error_is_repairable() -> None:
    result = PlanValidationResult(
        valid=False,
        errors=[
            ValidationError(
                code="EMPTY", message="empty", repairable=False
            ),
            ValidationError(
                code="UNKNOWN_AGENT",
                message="bad agent",
                repairable=True,
            ),
        ],
    )

    assert result.repairable is True


def test_error_messages() -> None:
    result = PlanValidationResult(
        valid=False,
        errors=[ValidationError("X", "bad", True)],
    )

    assert result.error_messages() == ["bad"]
