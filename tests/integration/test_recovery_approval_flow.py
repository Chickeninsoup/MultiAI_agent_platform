"""5E-5C-8D-7: End-to-end Recovery Approval Flow.

Not a design stage - every component here (FailureClassifier,
RecoveryPlanner, RecoveryOrchestrator, RecoveryExecutor,
RuntimeApprovalService, ExecutionCheckpoint/Repository,
ResumePlanBuilder, TaskPlanResumeService, RecoveryContinuationService)
was built and unit-tested in its own stage across 5E-5A/5E-5B/5E-5C.
This file proves they compose into one real flow: a step fails
BLOCKED mid-plan, a pending approval is created, execution cannot
resume until a human decides, and only "approved" actually continues
execution - through the real TaskScheduler, not a stand-in.

No CheckpointWriter exists yet (confirmed absent in the 5E-5C-8C-1
audit) - nothing today automatically turns a PlanExecutionResult into
an ExecutionCheckpoint. This test constructs one directly, the same
way a future CheckpointWriter would, to exercise the resume path that
already exists and is already real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agent_message import AgentMessage
from src.agents.task_agent import TaskAgent
from src.agents.task_agent_registry import TaskAgentRegistry
from src.execution_checkpoint import ExecutionCheckpoint
from src.execution_checkpoint_repository import (
    ExecutionCheckpointRepository,
)
from src.execution_failure import ExecutionFailure, FailureCategory
from src.failure_classifier import FailureClassifier
from src.failure_retry_classifier import FailureRetryClassifier
from src.message_router import MessageRouter
from src.planning.failure_repair_request_builder import (
    FailureRepairRequestBuilder,
)
from src.planning.plan_execution_result import PlanExecutionResult
from src.planning.plan_repair_request import PlanRepairRequest
from src.planning.planner_output import PlannerOutput
from src.planning.resume_plan_builder import ResumePlanBuilder
from src.planning.task_plan_resume_service import TaskPlanResumeService
from src.planning.task_planning_context import TaskPlanningContext
from src.recovery_action import RecoveryAction
from src.recovery_continuation_errors import RecoveryContinuationError
from src.recovery_continuation_service import RecoveryContinuationService
from src.recovery_execution_context import RecoveryExecutionContext
from src.recovery_executor import RecoveryExecutor
from src.recovery_orchestrator import RecoveryOrchestrator
from src.recovery_plan import RecoveryPlan, RecoveryStepAction
from src.recovery_planner import RecoveryPlanner
from src.retry_manager import RetryManager
from src.retry_policy import RetryPolicy
from src.runtime_approval_repository import RuntimeApprovalRepository
from src.runtime_approval_service import RuntimeApprovalService
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_dependency_resolver import TaskDependencyResolver
from src.task_plan import TaskPlan, TaskStep
from src.task_plan_converter import TaskPlanConverter
from src.task_plan_executor import TaskPlanExecutor
from src.task_scheduler import TaskScheduler


class AlwaysSucceedsAgent:
    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        self.call_count = 0

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def handle(self, message: AgentMessage) -> str:
        self.call_count += 1
        return "done"


class BlockedUntilApprovedAgent:
    """Fails once with PermissionError - simulates a real BLOCKED
    failure (permission denied) that only clears once whatever granted
    the human's approval also unblocked the underlying resource. The
    second call (only reachable via resume) succeeds."""

    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        self.call_count = 0

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def handle(self, message: AgentMessage) -> str:
        self.call_count += 1

        if self.call_count == 1:
            raise PermissionError("credential not yet granted")

        return "recovered"


class FakeRuntimePlanRepairService:
    def __init__(self) -> None:
        self.calls: list[PlanRepairRequest] = []

    def repair(self, request: PlanRepairRequest) -> PlannerOutput:
        self.calls.append(request)
        return PlannerOutput()


class _Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.checkpoint_repository = ExecutionCheckpointRepository(
            tmp_path
        )
        self.approval_repository = RuntimeApprovalRepository(tmp_path)
        self.approval_service = RuntimeApprovalService(
            self.approval_repository
        )
        self.resume_plan_builder = ResumePlanBuilder()
        self.recovery_orchestrator = RecoveryOrchestrator(
            RecoveryPlanner()
        )
        self.failure_repair_request_builder = (
            FailureRepairRequestBuilder()
        )

    def build_scheduler(
        self, agents: list[object], task_id: str
    ) -> TaskScheduler:
        registry = TaskAgentRegistry()
        for agent in agents:
            registry.assign_agent(
                TaskAgent(
                    agent_id=agent.agent_id,  # type: ignore[attr-defined]
                    task_id=task_id,
                    template_id="t",
                )
            )
        router = MessageRouter(agents, registry)
        executor = TaskPlanExecutor(TaskPlanConverter(), router)

        return TaskScheduler(
            TaskDependencyResolver(), executor, FailureClassifier()
        )

    def build_resume_service(
        self, scheduler: TaskScheduler
    ) -> TaskPlanResumeService:
        return TaskPlanResumeService(
            self.checkpoint_repository,
            self.resume_plan_builder,
            scheduler,
        )

    def build_continuation_service(
        self, resume_service: TaskPlanResumeService
    ) -> RecoveryContinuationService:
        return RecoveryContinuationService(
            self.approval_repository, resume_service
        )

    def build_recovery_executor(
        self, repair_service: object
    ) -> RecoveryExecutor:
        return RecoveryExecutor(
            RetryManager(RetryPolicy(), FailureRetryClassifier()),
            repair_service,
            self.failure_repair_request_builder,
            self.approval_service,
        )


def _plan(task_id: str) -> TaskPlan:
    return TaskPlan(
        task_id=task_id,
        steps=[
            TaskStep(
                step_id="A", agent_id="agent-a", description="do a"
            ),
            TaskStep(
                step_id="B",
                agent_id="agent-b",
                description="do b",
                depends_on=["A"],
            ),
        ],
    )


def _run_initial_plan_and_request_approval(
    rig: _Rig,
    task_id: str,
    agent_a: AlwaysSucceedsAgent,
    agent_b: BlockedUntilApprovedAgent,
) -> tuple[TaskPlan, PlanExecutionResult]:
    """Runs the plan for real (through TaskScheduler), gets a real
    BLOCKED failure on step B, and drives it all the way through
    RecoveryOrchestrator -> RecoveryExecutor -> a pending
    RuntimeApprovalRequest - the part of the chain that already
    happens automatically today."""

    plan = _plan(task_id)
    scheduler = rig.build_scheduler([agent_a, agent_b], task_id)

    step_results = scheduler.run(plan)
    initial_result = PlanExecutionResult(step_results=step_results)

    recovery_plan = rig.recovery_orchestrator.plan(initial_result)
    recovery_executor = rig.build_recovery_executor(
        FakeRuntimePlanRepairService()
    )
    context = RecoveryExecutionContext(
        task_id=task_id,
        plan=plan,
        executor=object(),
        planning_context=TaskPlanningContext(
            task_id=task_id, available_agents=[]
        ),
    )
    recovery_executor.execute(recovery_plan, context)

    checkpoint = ExecutionCheckpoint(
        task_id=task_id,
        plan_id=task_id,
        completed_step_ids=("A",),
        step_results=tuple(initial_result.step_results),
        blocked_step_id="B",
    )
    rig.checkpoint_repository.save(checkpoint)

    return plan, initial_result


def test_full_successful_recovery_flow(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    task_id = "task-a"
    agent_a = AlwaysSucceedsAgent("agent-a")
    agent_b = BlockedUntilApprovedAgent("agent-b")

    plan, initial_result = _run_initial_plan_and_request_approval(
        rig, task_id, agent_a, agent_b
    )

    assert initial_result.step_results[0].status == StepStatus.SUCCESS
    assert initial_result.step_results[1].status == StepStatus.FAILED
    assert (
        initial_result.step_results[1].failure.category
        == FailureCategory.BLOCKED
    )
    assert agent_b.call_count == 1

    pending = rig.approval_repository.load(task_id)
    assert pending.status == "pending"

    rig.approval_service.approve(task_id)

    resume_scheduler = rig.build_scheduler([agent_a, agent_b], task_id)
    resume_service = rig.build_resume_service(resume_scheduler)
    continuation_service = rig.build_continuation_service(
        resume_service
    )

    final_result = continuation_service.resume_after_approval(
        task_id, plan
    )

    assert [r.status for r in final_result.step_results] == [
        StepStatus.SUCCESS
    ]
    assert final_result.step_results[0].step_id == "B"
    assert agent_b.call_count == 2
    assert agent_a.call_count == 1


def test_pending_approval_blocks_resume(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    task_id = "task-a"
    agent_a = AlwaysSucceedsAgent("agent-a")
    agent_b = BlockedUntilApprovedAgent("agent-b")

    plan, _ = _run_initial_plan_and_request_approval(
        rig, task_id, agent_a, agent_b
    )

    resume_scheduler = rig.build_scheduler([agent_a, agent_b], task_id)
    resume_service = rig.build_resume_service(resume_scheduler)
    continuation_service = rig.build_continuation_service(
        resume_service
    )

    with pytest.raises(RecoveryContinuationError):
        continuation_service.resume_after_approval(task_id, plan)

    assert agent_b.call_count == 1


def test_rejected_approval_blocks_resume(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    task_id = "task-a"
    agent_a = AlwaysSucceedsAgent("agent-a")
    agent_b = BlockedUntilApprovedAgent("agent-b")

    plan, _ = _run_initial_plan_and_request_approval(
        rig, task_id, agent_a, agent_b
    )

    rig.approval_service.reject(task_id)

    resume_scheduler = rig.build_scheduler([agent_a, agent_b], task_id)
    resume_service = rig.build_resume_service(resume_scheduler)
    continuation_service = rig.build_continuation_service(
        resume_service
    )

    with pytest.raises(RecoveryContinuationError):
        continuation_service.resume_after_approval(task_id, plan)

    assert agent_b.call_count == 1


def test_task_isolation_across_recovery_approval(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    agent_a1 = AlwaysSucceedsAgent("agent-a")
    agent_b1 = BlockedUntilApprovedAgent("agent-b")
    plan_a, _ = _run_initial_plan_and_request_approval(
        rig, "task-a", agent_a1, agent_b1
    )

    agent_a2 = AlwaysSucceedsAgent("agent-a")
    agent_b2 = BlockedUntilApprovedAgent("agent-b")
    plan_b, _ = _run_initial_plan_and_request_approval(
        rig, "task-b", agent_a2, agent_b2
    )

    rig.approval_service.approve("task-a")
    # task-b's approval stays pending

    resume_scheduler_a = rig.build_scheduler(
        [agent_a1, agent_b1], "task-a"
    )
    continuation_a = rig.build_continuation_service(
        rig.build_resume_service(resume_scheduler_a)
    )
    result_a = continuation_a.resume_after_approval("task-a", plan_a)

    assert result_a.step_results[0].status == StepStatus.SUCCESS

    resume_scheduler_b = rig.build_scheduler(
        [agent_a2, agent_b2], "task-b"
    )
    continuation_b = rig.build_continuation_service(
        rig.build_resume_service(resume_scheduler_b)
    )

    with pytest.raises(RecoveryContinuationError):
        continuation_b.resume_after_approval("task-b", plan_b)

    assert agent_b2.call_count == 1


def test_mixed_recovery_actions_use_independent_collaborators(
    tmp_path: Path,
) -> None:
    """RETRY, REPAIR_PLAN, and REQUEST_APPROVAL in the same
    RecoveryPlan must not interfere with each other - the same
    dispatcher property already proven at unit level, exercised here
    against the real RetryManager and RuntimeApprovalService."""

    rig = _Rig(tmp_path)
    task_id = "task-c"
    repair_service = FakeRuntimePlanRepairService()
    recovery_executor = rig.build_recovery_executor(repair_service)

    plan = TaskPlan(
        task_id=task_id,
        steps=[
            TaskStep(
                step_id="A", agent_id="agent-a", description="do a"
            ),
            TaskStep(
                step_id="B", agent_id="agent-b", description="do b"
            ),
            TaskStep(
                step_id="C", agent_id="agent-c", description="do c"
            ),
        ],
    )

    class RecoversOnRetry:
        def __init__(self) -> None:
            self.call_count = 0

        def execute_step(
            self, step: TaskStep, task_id: str
        ) -> StepExecutionResult:
            self.call_count += 1
            return StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.SUCCESS,
                output=f"{step.step_id}-done",
            )

    recovery_plan = RecoveryPlan(
        steps=[
            RecoveryStepAction(
                failure=ExecutionFailure(
                    category=FailureCategory.TEMPORARY_ERROR,
                    message="timeout",
                    step_id="A",
                ),
                action=RecoveryAction.RETRY,
            ),
            RecoveryStepAction(
                failure=ExecutionFailure(
                    category=FailureCategory.PLAN_ERROR,
                    message="invalid arguments",
                    step_id="B",
                ),
                action=RecoveryAction.REPAIR_PLAN,
            ),
            RecoveryStepAction(
                failure=ExecutionFailure(
                    category=FailureCategory.BLOCKED,
                    message="permission denied",
                    step_id="C",
                ),
                action=RecoveryAction.REQUEST_APPROVAL,
            ),
        ]
    )
    context = RecoveryExecutionContext(
        task_id=task_id,
        plan=plan,
        executor=RecoversOnRetry(),
        planning_context=TaskPlanningContext(
            task_id=task_id, available_agents=[]
        ),
    )

    recovery_executor.execute(recovery_plan, context)

    assert len(repair_service.calls) == 1
    assert repair_service.calls[0].errors[0].message.find("'B'") != -1
    pending = rig.approval_repository.load(task_id)
    assert pending.status == "pending"
    assert pending.failure.step_id == "C"
