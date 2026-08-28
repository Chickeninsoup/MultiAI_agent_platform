from __future__ import annotations

from src.execution_failure import ExecutionFailure, FailureCategory
from src.planning.failure_repair_request_builder import (
    FailureRepairRequestBuilder,
)
from src.planning.plan_repair_request import PlanRepairRequest
from src.planning.planner_output import PlannerOutput
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


def _step_action(
    step_id: str, category: FailureCategory, action: RecoveryAction
) -> RecoveryStepAction:
    return RecoveryStepAction(
        failure=ExecutionFailure(
            category=category, message="reason", step_id=step_id
        ),
        action=action,
    )


def _context(
    steps: list[TaskStep], executor: object, task_id: str = "task-1"
) -> RecoveryExecutionContext:
    return RecoveryExecutionContext(
        task_id=task_id,
        plan=TaskPlan(task_id=task_id, steps=steps),
        executor=executor,
        planning_context=TaskPlanningContext(
            task_id=task_id, available_agents=[]
        ),
    )


def _executor(
    retry_manager: object | None = None,
    repair_service: object | None = None,
    approval_service: object | None = None,
) -> RecoveryExecutor:
    return RecoveryExecutor(
        retry_manager or FakeRetryManager(),
        repair_service or FakeRuntimePlanRepairService(),
        FailureRepairRequestBuilder(),
        approval_service or FakeRuntimeApprovalService(),
    )


def test_retry_action_calls_the_real_retry_manager() -> None:
    retry_manager = FakeRetryManager()
    executor = FakeExecutor()
    step_a = _step("a")
    plan = RecoveryPlan(
        steps=[
            _step_action(
                "a", FailureCategory.TEMPORARY_ERROR, RecoveryAction.RETRY
            )
        ]
    )

    _executor(retry_manager=retry_manager).execute(
        plan, _context([step_a], executor)
    )

    assert retry_manager.calls == [(step_a, executor, "task-1")]


def test_repair_plan_action_does_not_call_retry_manager() -> None:
    retry_manager = FakeRetryManager()
    executor = FakeExecutor()
    plan = RecoveryPlan(
        steps=[
            _step_action(
                "a",
                FailureCategory.PLAN_ERROR,
                RecoveryAction.REPAIR_PLAN,
            )
        ]
    )

    _executor(retry_manager=retry_manager).execute(
        plan, _context([_step("a")], executor)
    )

    assert retry_manager.calls == []


def test_mixed_plan_only_routes_the_retry_step() -> None:
    retry_manager = FakeRetryManager()
    executor = FakeExecutor()
    step_a = _step("a")
    plan = RecoveryPlan(
        steps=[
            _step_action(
                "a", FailureCategory.TEMPORARY_ERROR, RecoveryAction.RETRY
            ),
            _step_action(
                "b",
                FailureCategory.PLAN_ERROR,
                RecoveryAction.REPAIR_PLAN,
            ),
        ]
    )

    _executor(retry_manager=retry_manager).execute(
        plan, _context([step_a, _step("b")], executor)
    )

    assert retry_manager.calls == [(step_a, executor, "task-1")]


def test_empty_plan_calls_nothing() -> None:
    retry_manager = FakeRetryManager()
    executor = FakeExecutor()

    _executor(retry_manager=retry_manager).execute(
        RecoveryPlan(steps=[]), _context([], executor)
    )

    assert retry_manager.calls == []


def test_request_approval_calls_runtime_approval_service() -> None:
    approval_service = FakeRuntimeApprovalService()
    executor = FakeExecutor()
    plan = RecoveryPlan(
        steps=[
            _step_action(
                "a", FailureCategory.BLOCKED, RecoveryAction.REQUEST_APPROVAL
            )
        ]
    )

    _executor(approval_service=approval_service).execute(
        plan, _context([_step("a")], executor)
    )

    assert len(approval_service.calls) == 1
    task_id, plan_id, failure = approval_service.calls[0]
    assert task_id == "task-1"
    assert plan_id == "task-1"
    assert failure.category == FailureCategory.BLOCKED
    assert failure.step_id == "a"


def test_request_approval_does_not_call_retry_manager() -> None:
    retry_manager = FakeRetryManager()
    executor = FakeExecutor()
    plan = RecoveryPlan(
        steps=[
            _step_action(
                "a", FailureCategory.BLOCKED, RecoveryAction.REQUEST_APPROVAL
            )
        ]
    )

    _executor(retry_manager=retry_manager).execute(
        plan, _context([_step("a")], executor)
    )

    assert retry_manager.calls == []


def test_mixed_plan_routes_every_action_independently() -> None:
    retry_manager = FakeRetryManager()
    approval_service = FakeRuntimeApprovalService()
    executor = FakeExecutor()
    step_a = _step("a")
    plan = RecoveryPlan(
        steps=[
            _step_action(
                "a", FailureCategory.TEMPORARY_ERROR, RecoveryAction.RETRY
            ),
            _step_action(
                "b",
                FailureCategory.PLAN_ERROR,
                RecoveryAction.REPAIR_PLAN,
            ),
            _step_action(
                "c",
                FailureCategory.BLOCKED,
                RecoveryAction.REQUEST_APPROVAL,
            ),
        ]
    )

    _executor(
        retry_manager=retry_manager, approval_service=approval_service
    ).execute(
        plan, _context([step_a, _step("b"), _step("c")], executor)
    )

    assert retry_manager.calls == [(step_a, executor, "task-1")]
    assert len(approval_service.calls) == 1
    assert approval_service.calls[0][2].step_id == "c"
