from __future__ import annotations

from src.planning.plan_validation import PlanValidationResult
from src.planning.repair_decision_service import RepairDecisionService
from src.planning.repair_preparation_service import (
    RepairPreparationService,
)
from src.planning.repair_request_builder import RepairRequestBuilder
from src.planning.task_planning_context import TaskPlanningContext
from src.planning.validation_error import ValidationError
from src.task_plan import TaskPlan


def _service() -> RepairPreparationService:
    return RepairPreparationService(
        decision_service=RepairDecisionService(),
        builder=RepairRequestBuilder(),
    )


def test_prepare_returns_request_when_repairable() -> None:
    service = _service()
    plan = TaskPlan(task_id="task-1", steps=[])
    repairable_validation = PlanValidationResult(
        valid=False,
        errors=[
            ValidationError(
                code="UNKNOWN_AGENT",
                message="Unknown agent: agent-x",
                repairable=True,
            )
        ],
    )

    result = service.prepare(plan, repairable_validation)

    assert result is not None
    assert result.original_plan is plan


def test_prepare_returns_none_when_not_repairable() -> None:
    service = _service()
    plan = TaskPlan(task_id="task-1", steps=[])
    fatal_validation = PlanValidationResult(
        valid=False,
        errors=[
            ValidationError(
                code="EMPTY_TASK",
                message="Task has no description",
                repairable=False,
            )
        ],
    )

    result = service.prepare(plan, fatal_validation)

    assert result is None


def test_prepare_forwards_the_given_context() -> None:
    service = _service()
    plan = TaskPlan(task_id="task-1", steps=[])
    repairable_validation = PlanValidationResult(
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

    result = service.prepare(plan, repairable_validation, context)

    assert result is not None
    assert result.context is context


def test_prepare_returns_none_when_already_valid() -> None:
    service = _service()
    plan = TaskPlan(task_id="task-1", steps=[])
    valid_validation = PlanValidationResult(valid=True)

    result = service.prepare(plan, valid_validation)

    assert result is None
