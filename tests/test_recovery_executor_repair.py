from __future__ import annotations

import pytest

from src.agents.task_agent_info import TaskAgentInfo
from src.execution_failure import ExecutionFailure, FailureCategory
from src.planning.failure_repair_request_builder import (
    FailureRepairRequestBuilder,
)
from src.planning.plan_repair_request import PlanRepairRequest
from src.planning.planner_output import PlannerOutput
from src.planning.repair_request_source import RepairRequestSource
from src.planning.task_planning_context import TaskPlanningContext
from src.recovery_action import RecoveryAction
from src.recovery_execution_context import RecoveryExecutionContext
from src.recovery_executor import RecoveryExecutor
from src.recovery_plan import RecoveryPlan, RecoveryStepAction
from src.runtime_approval_request import RuntimeApprovalRequest
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_plan import TaskPlan, TaskStep


class FakeRetryManager:
    def __init__(self) -> None:
        self.calls: list[tuple[TaskStep, object, str]] = []

    def execute(
        self, step: TaskStep, executor: object, task_id: str
    ) -> StepExecutionResult:
        self.calls.append((step, executor, task_id))
        return StepExecutionResult(
            step_id=step.step_id, status=StepStatus.SUCCESS
        )


class FakeRuntimePlanRepairService:
    """Deliberately has only .repair() - if RecoveryExecutor tried to
    bypass it and reach RepairPlanner directly, this fake couldn't
    satisfy that call and the test would fail loudly."""

    def __init__(self) -> None:
        self.calls: list[PlanRepairRequest] = []

    def repair(self, request: PlanRepairRequest) -> PlannerOutput:
        self.calls.append(request)
        return PlannerOutput()


class FakeRuntimeApprovalService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, ExecutionFailure]] = []

    def create(
        self, task_id: str, plan_id: str, failure: ExecutionFailure
    ) -> RuntimeApprovalRequest:
        self.calls.append((task_id, plan_id, failure))
        return RuntimeApprovalRequest(
            approval_id="approval-1",
            task_id=task_id,
            plan_id=plan_id,
            failure=failure,
        )


class FakeExecutor:
    def execute_step(
        self, step: TaskStep, task_id: str
    ) -> StepExecutionResult:
        return StepExecutionResult(
            step_id=step.step_id, status=StepStatus.SUCCESS
        )


def _step(step_id: str) -> TaskStep:
    return TaskStep(
        step_id=step_id, agent_id="agent-coder", description="do it"
    )


def _planning_context(task_id: str = "task-1") -> TaskPlanningContext:
    return TaskPlanningContext(
        task_id=task_id,
        available_agents=[
            TaskAgentInfo(agent_id="agent-coder", role="Coder")
        ],
    )


def _repair_step_action(step_id: str, message: str) -> RecoveryStepAction:
    return RecoveryStepAction(
        failure=ExecutionFailure(
            category=FailureCategory.PLAN_ERROR,
            message=message,
            step_id=step_id,
        ),
        action=RecoveryAction.REPAIR_PLAN,
    )


def test_repair_plan_calls_runtime_plan_repair_service() -> None:
    retry_manager = FakeRetryManager()
    repair_service = FakeRuntimePlanRepairService()
    executor = FakeExecutor()
    step_a = _step("a")
    plan = TaskPlan(task_id="task-1", steps=[step_a])
    recovery_plan = RecoveryPlan(
        steps=[_repair_step_action("a", "tool rejected invalid argument")]
    )
    context = RecoveryExecutionContext(
        task_id="task-1",
        plan=plan,
        executor=executor,
        planning_context=_planning_context(),
    )

    RecoveryExecutor(
        retry_manager,
        repair_service,
        FailureRepairRequestBuilder(),
        FakeRuntimeApprovalService(),
    ).execute(recovery_plan, context)

    assert len(repair_service.calls) == 1


def test_repair_request_carries_task_plan_failure_and_context() -> None:
    retry_manager = FakeRetryManager()
    repair_service = FakeRuntimePlanRepairService()
    executor = FakeExecutor()
    step_a = _step("a")
    plan = TaskPlan(task_id="task-1", steps=[step_a])
    planning_context = _planning_context()
    step_action = _repair_step_action(
        "a", "tool rejected invalid argument"
    )
    recovery_plan = RecoveryPlan(steps=[step_action])
    context = RecoveryExecutionContext(
        task_id="task-1",
        plan=plan,
        executor=executor,
        planning_context=planning_context,
    )

    RecoveryExecutor(
        retry_manager,
        repair_service,
        FailureRepairRequestBuilder(),
        FakeRuntimeApprovalService(),
    ).execute(recovery_plan, context)

    request = repair_service.calls[0]
    assert request.original_plan is plan
    assert request.context is planning_context
    assert request.source == RepairRequestSource.EXECUTION_FAILURE
    assert request.errors[0].code == "EXECUTION_FAILURE"
    assert "a" in request.errors[0].message


def test_mixed_plan_routes_each_action_to_its_own_collaborator() -> None:
    retry_manager = FakeRetryManager()
    repair_service = FakeRuntimePlanRepairService()
    executor = FakeExecutor()
    step_a = _step("a")
    step_b = _step("b")
    plan = TaskPlan(task_id="task-1", steps=[step_a, step_b])
    recovery_plan = RecoveryPlan(
        steps=[
            RecoveryStepAction(
                failure=ExecutionFailure(
                    category=FailureCategory.TEMPORARY_ERROR,
                    message="timeout",
                    step_id="a",
                ),
                action=RecoveryAction.RETRY,
            ),
            _repair_step_action("b", "invalid arguments"),
        ]
    )
    context = RecoveryExecutionContext(
        task_id="task-1",
        plan=plan,
        executor=executor,
        planning_context=_planning_context(),
    )

    RecoveryExecutor(
        retry_manager,
        repair_service,
        FailureRepairRequestBuilder(),
        FakeRuntimeApprovalService(),
    ).execute(recovery_plan, context)

    assert retry_manager.calls == [(step_a, executor, "task-1")]
    assert len(repair_service.calls) == 1
    assert repair_service.calls[0].errors[0].message.find("'b'") != -1


def test_recovery_executor_requires_runtime_plan_repair_service() -> None:
    with pytest.raises(TypeError):
        RecoveryExecutor(  # type: ignore[call-arg]
            FakeRetryManager(),
            failure_repair_request_builder=FailureRepairRequestBuilder(),
        )


def test_recovery_executor_requires_failure_repair_request_builder() -> (
    None
):
    with pytest.raises(TypeError):
        RecoveryExecutor(  # type: ignore[call-arg]
            FakeRetryManager(),
            runtime_plan_repair_service=FakeRuntimePlanRepairService(),
        )


def test_recovery_executor_requires_runtime_approval_service() -> None:
    with pytest.raises(TypeError):
        RecoveryExecutor(  # type: ignore[call-arg]
            FakeRetryManager(),
            runtime_plan_repair_service=FakeRuntimePlanRepairService(),
            failure_repair_request_builder=FailureRepairRequestBuilder(),
        )
