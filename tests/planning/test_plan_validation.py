from __future__ import annotations

import dataclasses

import pytest

from src.planning.plan_validation import PlanValidationResult


def test_valid_result_defaults_errors_and_warnings_to_empty() -> None:
    result = PlanValidationResult(valid=True)

    assert result.errors == []
    assert result.warnings == []


def test_invalid_result_can_carry_errors() -> None:
    result = PlanValidationResult(
        valid=False, errors=["Unknown agent: agent-x"]
    )

    assert result.valid is False
    assert result.errors == ["Unknown agent: agent-x"]


def test_plan_validation_result_is_frozen() -> None:
    result = PlanValidationResult(valid=True)

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.valid = False
