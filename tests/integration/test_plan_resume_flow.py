from __future__ import annotations

from pathlib import Path

from src.agent_message import AgentMessage
from src.agents.task_agent import TaskAgent
from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.planning.approval_repository import ApprovalRepository
from src.planning.persistent_approval_service import (
    PersistentApprovalService,
)
from src.planning.plan_execution_service import PlanExecutionService
from src.planning.plan_repository import PlanRepository
from src.planning.plan_review_service import PlanReviewService
from src.planning.plan_service import PlanService
from src.planning.plan_validator import PlanValidator
from src.step_execution_result import StepStatus
from src.task_dependency_resolver import TaskDependencyResolver
from src.task_plan import TaskPlan, TaskStep
from src.task_plan_converter import TaskPlanConverter


class FakeAgent:
    def __init__(self, agent_id: str, response: str) -> None:
        self._agent_id = agent_id
        self._response = response
        self.received_messages: list[AgentMessage] = []

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def handle(self, message: AgentMessage) -> str:
        self.received_messages.append(message)
        return self._response


class FakeTaskAgent:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id


class FakeTaskAgentRegistry:
    def __init__(self, agent_ids: list[str]) -> None:
        self._agents = [FakeTaskAgent(agent_id) for agent_id in agent_ids]

    def list_agents(self, task_id: str) -> list[FakeTaskAgent]:
        return self._agents


class FakeAgentRegistry:
    """Just enough of AgentRegistry for PlanValidator: a fixed set of
    known agent ids, no real filesystem/AgentDefinition involved."""

    class _Agent:
        def __init__(self, agent_id: str) -> None:
            self.id = agent_id

    def __init__(self, agent_ids: list[str]) -> None:
        self._agents = [self._Agent(agent_id) for agent_id in agent_ids]

    def list_agents(self):
        return self._agents


class FakeAgentRuntimeFactory:
    def __init__(self, handlers: list) -> None:
        self._handlers = handlers

    def create_handlers(self, task_id: str) -> list:
        return self._handlers


class _UnusedManagerAgent:
    """PlanService requires a manager_agent (Phase 1C-4); this test
    never calls PlanService.create_plan(), only save_plan()/
    create_review() directly on an already-built TaskPlan, so this
    is never actually invoked."""

    def plan(self, request, task_id, context=None):
        raise NotImplementedError


class _UnusedContextFactory:
    """Same reasoning as _UnusedManagerAgent - required by PlanService,
    never exercised by this test."""

    def create(self, task_id):
        raise NotImplementedError


def _build_services(tasks_dir: Path, agent: FakeAgent):
    """Builds a completely fresh set of service instances, all
    pointed at the same tasks_dir - this is what happens across a
    real process restart: nothing in memory survives, only what was
    written to disk does."""

    plan_repository = PlanRepository(tasks_dir)
    approval_repository = ApprovalRepository(tasks_dir)
    review_service = PlanReviewService(
        PlanValidator(
            FakeAgentRegistry(["agent-coder"]),
            FakeTaskAgentRegistry(["agent-coder"]),
        )
    )
    plan_service = PlanService(
        review_service,
        plan_repository,
        _UnusedManagerAgent(),
        _UnusedContextFactory(),
        TaskAgentTeamLifecycle(TaskAgentRegistry()),
    )
    persistent_approval_service = PersistentApprovalService(
        approval_repository
    )
    # Both task-001 and task-002 (used across the two tests below) are
    # assigned agent-coder, so MessageRouter's dispatch-authorization
    # check (5E-4D-3) passes regardless of which test calls this.
    execution_task_agent_registry = TaskAgentRegistry()
    for task_id in ("task-001", "task-002"):
        execution_task_agent_registry.assign_agent(
            TaskAgent(
                agent_id="agent-coder",
                task_id=task_id,
                template_id="coder",
            )
        )
    plan_execution_service = PlanExecutionService(
        plan_repository,
        approval_repository,
        review_service,
        FakeAgentRuntimeFactory([agent]),
        execution_task_agent_registry,
        TaskDependencyResolver(),
        TaskPlanConverter(),
    )

    return plan_service, persistent_approval_service, plan_execution_service


def test_approved_plan_can_resume_after_restart(
    tmp_path: Path,
) -> None:
    agent = FakeAgent("agent-coder", "done")

    # --- Phase 1: create and save a plan (e.g. yesterday's session) ---
    plan_service_1, _, _ = _build_services(tmp_path, agent)

    plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="coding",
                agent_id="agent-coder",
                description="implement the feature",
            )
        ],
    )
    saved_record = plan_service_1.save_plan(plan)
    assert saved_record.status == "pending"

    # --- Simulated restart: brand new service instances, nothing in
    # memory carries over except tmp_path (the "disk"). ---
    (
        plan_service_2,
        approval_service_2,
        execution_service_2,
    ) = _build_services(tmp_path, agent)

    # --- Phase 2: approve and execute, in the "new process" ---
    loaded_record = plan_service_2.get_plan("task-001")
    assert loaded_record is not None
    assert loaded_record.plan == plan

    review = plan_service_2.create_review(loaded_record.plan)
    approval_service_2.approve_and_save(review)
    plan_service_2.update_status("task-001", "approved")

    result = execution_service_2.execute("task-001")
    plan_service_2.update_status("task-001", "executed")

    assert len(result.step_results) == 1
    assert result.step_results[0].status == StepStatus.SUCCESS
    assert result.step_results[0].output == "done"
    assert result.succeeded is True
    assert len(agent.received_messages) == 1
    assert agent.received_messages[0].content == "implement the feature"

    final_record = plan_service_2.get_plan("task-001")
    assert final_record.status == "executed"


def test_rejected_plan_is_never_executed_after_restart(
    tmp_path: Path,
) -> None:
    agent = FakeAgent("agent-coder", "done")
    plan_service_1, _, _ = _build_services(tmp_path, agent)

    plan = TaskPlan(
        task_id="task-002",
        steps=[
            TaskStep(
                step_id="coding",
                agent_id="agent-coder",
                description="implement the feature",
            )
        ],
    )
    plan_service_1.save_plan(plan)

    plan_service_2, approval_service_2, execution_service_2 = (
        _build_services(tmp_path, agent)
    )

    loaded_record = plan_service_2.get_plan("task-002")
    review = plan_service_2.create_review(loaded_record.plan)
    approval_service_2.reject_and_save(review)
    plan_service_2.update_status("task-002", "rejected")

    assert agent.received_messages == []

    # Executing after a rejection must still refuse - the approval
    # record on disk says "rejected", not "approved".
    try:
        execution_service_2.execute("task-002")
        raised = False
    except ValueError:
        raised = True

    assert raised is True
    assert agent.received_messages == []
