from __future__ import annotations

from src.agents.task_agent_info import TaskAgentInfo
from src.execution_failure import ExecutionFailure, FailureCategory
from src.planning.failure_repair_request_builder import (
    FailureRepairRequestBuilder,
)
from src.planning.repair_request_source import RepairRequestSource
from src.planning.task_planning_context import TaskPlanningContext
from src.task_plan import TaskPlan


def _plan() -> TaskPlan:
    return TaskPlan(task_id="task-1", steps=[])


def _context() -> TaskPlanningContext:
    return TaskPlanningContext(
        task_id="task-1",
        available_agents=[
            TaskAgentInfo(agent_id="agent-coder", role="Coder")
        ],
    )


def _failure(step_id: str | None = "step-1") -> ExecutionFailure:
    return ExecutionFailure(
        category=FailureCategory.PLAN_ERROR,
        message="tool rejected invalid argument",
        step_id=step_id,
    )


def test_request_source_is_execution_failure() -> None:
    request = FailureRepairRequestBuilder().build(
        "task-1", _plan(), _failure(), _context()
    )

    assert request.source == RepairRequestSource.EXECUTION_FAILURE


def test_synthesizes_an_execution_failure_validation_error() -> None:
    request = FailureRepairRequestBuilder().build(
        "task-1", _plan(), _failure(), _context()
    )

    assert len(request.errors) == 1
    assert request.errors[0].code == "EXECUTION_FAILURE"
    assert request.errors[0].repairable is True


def test_step_id_is_preserved_in_the_message() -> None:
    request = FailureRepairRequestBuilder().build(
        "task-1", _plan(), _failure(step_id="step-1"), _context()
    )

    assert "step-1" in request.errors[0].message


def test_context_identity_is_preserved() -> None:
    context = _context()

    request = FailureRepairRequestBuilder().build(
        "task-1", _plan(), _failure(), context
    )

    assert request.context is context


def test_plan_identity_is_preserved() -> None:
    plan = _plan()

    request = FailureRepairRequestBuilder().build(
        "task-1", plan, _failure(), _context()
    )

    assert request.original_plan is plan


def test_builder_has_no_validation_pipeline_dependencies() -> None:
    """FailureRepairRequestBuilder must not wire PlanValidator or
    RepairDecisionService - it never re-checks whether the plan is
    valid or whether repair is warranted, both already decided by the
    time RecoveryAction.REPAIR_PLAN exists. Constructible with zero
    arguments proves it holds no such collaborator."""

    builder = FailureRepairRequestBuilder()

    assert vars(builder) == {}
