from __future__ import annotations

from src.planning.plan_validation import PlanValidationResult
from src.planning.repair_decision_service import RepairDecisionService
from src.planning.validation_error import ValidationError


def test_valid_plan_no_repair() -> None:
    service = RepairDecisionService()
    valid_result = PlanValidationResult(valid=True)

    result = service.decide(valid_result)

    assert result.should_repair is False
    assert result.reason == "Plan already valid"


def test_repairable_error() -> None:
    service = RepairDecisionService()
    repairable_result = PlanValidationResult(
        valid=False,
        errors=[
            ValidationError(
                code="UNKNOWN_AGENT",
                message="bad agent",
                repairable=True,
            )
        ],
    )

    result = service.decide(repairable_result)

    assert result.should_repair is True
    assert result.reason == "Validation errors are repairable"


def test_non_repairable_error() -> None:
    service = RepairDecisionService()
    fatal_result = PlanValidationResult(
        valid=False,
        errors=[
            ValidationError(
                code="EMPTY_TASK",
                message="Task has no description",
                repairable=False,
            )
        ],
    )

    result = service.decide(fatal_result)

    assert result.should_repair is False
    assert result.reason == "Validation errors are not repairable"


def test_mixed_errors_are_repairable_if_any_error_is() -> None:
    service = RepairDecisionService()
    mixed_result = PlanValidationResult(
        valid=False,
        errors=[
            ValidationError(
                code="EMPTY_TASK",
                message="Task has no description",
                repairable=False,
            ),
            ValidationError(
                code="UNKNOWN_AGENT",
                message="bad agent",
                repairable=True,
            ),
        ],
    )

    result = service.decide(mixed_result)

    assert result.should_repair is True
