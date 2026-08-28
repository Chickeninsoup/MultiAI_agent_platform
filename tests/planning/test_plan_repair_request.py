from __future__ import annotations

import dataclasses

import pytest

from src.agents.task_agent_info import TaskAgentInfo
from src.planning.plan_repair_request import PlanRepairRequest
from src.planning.repair_request_source import RepairRequestSource
from src.planning.task_planning_context import TaskPlanningContext
from src.planning.validation_error import ValidationError
from src.task_plan import TaskPlan


def test_create_request() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])
    error = ValidationError(
        code="UNKNOWN_AGENT", message="missing", repairable=True
    )

    request = PlanRepairRequest(original_plan=plan, errors=[error])

    assert request.original_plan is plan
    assert request.errors[0] is error


def test_default_errors() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])

    request = PlanRepairRequest(original_plan=plan)

    assert request.errors == []


def test_frozen() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])
    request = PlanRepairRequest(original_plan=plan)

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.instructions = "x"


def test_request_keeps_context() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])
    context = TaskPlanningContext(
        task_id="task-1",
        available_agents=[
            TaskAgentInfo(agent_id="agent-coder", role="Coder")
        ],
    )

    request = PlanRepairRequest(original_plan=plan, context=context)

    assert request.context is context


def test_context_defaults_to_none() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])

    request = PlanRepairRequest(original_plan=plan)

    assert request.context is None


def test_source_defaults_to_validation() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])

    request = PlanRepairRequest(original_plan=plan)

    assert request.source == RepairRequestSource.VALIDATION


def test_summary_contains_errors() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])
    request = PlanRepairRequest(
        original_plan=plan,
        errors=[
            ValidationError(
                code="UNKNOWN_AGENT",
                message="missing coder",
                repairable=True,
            )
        ],
    )

    summary = request.summarize()

    assert "UNKNOWN_AGENT" in summary
    assert "missing coder" in summary


def test_summary_includes_instructions() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])
    request = PlanRepairRequest(
        original_plan=plan,
        instructions="Fix the validation errors and generate a new valid plan.",
    )

    summary = request.summarize()

    assert (
        "Fix the validation errors and generate a new valid plan."
        in summary
    )
