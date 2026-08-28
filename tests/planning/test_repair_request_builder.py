from __future__ import annotations

import pytest

from src.planning.plan_validation import PlanValidationResult
from src.planning.repair_request_builder import RepairRequestBuilder
from src.planning.repair_request_source import RepairRequestSource
from src.planning.task_planning_context import TaskPlanningContext
from src.planning.validation_error import ValidationError
from src.task_plan import TaskPlan


def test_build_request_from_invalid_plan() -> None:
    builder = RepairRequestBuilder()
    plan = TaskPlan(task_id="task-1", steps=[])
    invalid_validation = PlanValidationResult(
        valid=False,
        errors=[
            ValidationError(
                code="UNKNOWN_AGENT",
                message="Unknown agent: agent-x",
                repairable=True,
            )
        ],
    )

    result = builder.build(plan=plan, validation=invalid_validation)

    assert result.original_plan is plan
    assert len(result.errors) > 0


def test_build_request_carries_instructions() -> None:
    builder = RepairRequestBuilder()
    plan = TaskPlan(task_id="task-1", steps=[])
    invalid_validation = PlanValidationResult(
        valid=False,
        errors=[
            ValidationError(
                code="UNKNOWN_AGENT",
                message="Unknown agent: agent-x",
                repairable=True,
            )
        ],
    )

    result = builder.build(plan=plan, validation=invalid_validation)

    assert result.instructions != ""


def test_build_request_forwards_the_given_context() -> None:
    builder = RepairRequestBuilder()
    plan = TaskPlan(task_id="task-1", steps=[])
    invalid_validation = PlanValidationResult(
        valid=False,
        errors=[
            ValidationError(
                code="UNKNOWN_AGENT",
                message="Unknown agent: agent-x",
                repairable=True,
            )
        ],
    )
    context = TaskPlanningContext(task_id="task-1", available_agents=[])

    result = builder.build(
        plan=plan, validation=invalid_validation, context=context
    )

    assert result.context is context


def test_valid_plan_cannot_repair() -> None:
    builder = RepairRequestBuilder()
    plan = TaskPlan(task_id="task-1", steps=[])
    valid_validation = PlanValidationResult(valid=True)

    with pytest.raises(ValueError):
        builder.build(plan=plan, validation=valid_validation)


def test_build_request_source_is_validation() -> None:
    builder = RepairRequestBuilder()
    plan = TaskPlan(task_id="task-1", steps=[])
    invalid_validation = PlanValidationResult(
        valid=False,
        errors=[
            ValidationError(
                code="UNKNOWN_AGENT",
                message="Unknown agent: agent-x",
                repairable=True,
            )
        ],
    )

    result = builder.build(plan=plan, validation=invalid_validation)

    assert result.source == RepairRequestSource.VALIDATION
