from __future__ import annotations

import dataclasses

import pytest

from src.planning.validation_error import ValidationError


def test_validation_error_fields() -> None:
    error = ValidationError(
        code="UNKNOWN_AGENT", message="Unknown agent: xyz", repairable=True
    )

    assert error.code == "UNKNOWN_AGENT"
    assert error.message == "Unknown agent: xyz"
    assert error.repairable is True


def test_non_repairable_error() -> None:
    error = ValidationError(
        code="EMPTY_TASK",
        message="Task has no description",
        repairable=False,
    )

    assert error.repairable is False


def test_validation_error_is_frozen() -> None:
    error = ValidationError(
        code="X", message="bad", repairable=True
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        error.code = "Y"
