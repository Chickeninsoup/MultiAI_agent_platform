from __future__ import annotations

from src.agent_message import AgentMessage
from src.agent_runtime_factory import AgentRuntimeFactory
from src.agents.task_agent import TaskAgent
from src.agents.task_agent_cleanup_service import TaskAgentCleanupService
from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.failure_classifier import FailureClassifier
from src.message_router import MessageRouter
from src.step_execution_result import StepStatus
from src.task_dependency_resolver import TaskDependencyResolver
from src.task_plan import TaskPlan, TaskStep
from src.task_plan_converter import TaskPlanConverter
from src.task_plan_executor import TaskPlanExecutor
from src.task_scheduler import TaskScheduler

# --- Fakes for the two things this boundary doesn't own: what an
# AgentDefinition looks like, and what actually happens once a
# message reaches a real Agent (Task/Run creation). Everything else
# in these tests - TaskAgentRegistry, MessageRouter, TaskPlanExecutor,
# TaskScheduler, AgentRuntimeFactory - is the real production class. -


class _FakeTask:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class _FakeResult:
    def __init__(self) -> None:
        self.run_id = "run-001"
        self.status = "completed"
        self.output_path = "output.md"


class FakeTaskService:
    def create_task_and_run(self, **kwargs):
        return _FakeTask(kwargs["task_id"]), None


class FakeRunService:
    def execute(self, task_id: str):
        return _FakeResult()


class FakeAgentDefinition:
    def __init__(self, agent_id: str) -> None:
        self.id = agent_id


class FakeAgentRegistry:
    def __init__(self, agent_ids: list[str]) -> None:
        self._ids = set(agent_ids)

    def get_agent(self, agent_id: str) -> FakeAgentDefinition:
        if agent_id not in self._ids:
            raise FileNotFoundError(agent_id)

        return FakeAgentDefinition(agent_id)


class FakeAgentHandler:
    """A minimal AgentHandler with call tracking - used where a test
    deliberately bypasses AgentRuntimeFactory to hand-construct an
    over-broad/stale router (Layer 2 must stand on its own)."""

    def __init__(self, agent_id: str, response: str = "done") -> None:
        self._agent_id = agent_id
        self._response = response
        self.calls: list[AgentMessage] = []

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def handle(self, message: AgentMessage) -> str:
        self.calls.append(message)
        return self._response


class FakeTaskRepository:
    def __init__(self, statuses: dict[str, str]) -> None:
        self._statuses = dict(statuses)

    def load(self, task_id: str):
        return _Task(self._statuses[task_id])


class _Task:
    def __init__(self, status: str) -> None:
        self.status = status


def _plan(task_id: str, agent_id: str) -> TaskPlan:
    return TaskPlan(
        task_id=task_id,
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id=agent_id,
                description="do work",
            )
        ],
    )


def _scheduler(router: MessageRouter) -> TaskScheduler:
    return TaskScheduler(
        TaskDependencyResolver(),
        TaskPlanExecutor(TaskPlanConverter(), router),
        FailureClassifier(),
    )


def test_same_task_execution_succeeds() -> None:
    registry = TaskAgentRegistry()
    registry.assign_agent(
        TaskAgent(agent_id="agent-a", task_id="task-a", template_id="t")
    )
    registry.assign_agent(
        TaskAgent(agent_id="agent-b", task_id="task-b", template_id="t")
    )
    runtime_factory = AgentRuntimeFactory(
        FakeAgentRegistry(["agent-a", "agent-b"]),
        registry,
        FakeTaskService(),
        FakeRunService(),
    )
    router = MessageRouter(
        runtime_factory.create_handlers("task-a"), registry
    )
    scheduler = _scheduler(router)

    results = scheduler.run(_plan("task-a", "agent-a"))

    assert results[0].status == StepStatus.SUCCESS


def test_plan_pointing_at_another_tasks_agent_fails_without_the_validator() -> (
    None
):
    """The core 5E-4D-4 test: a bad TaskPlan (task-a requesting
    agent-b, who belongs to task-b) goes straight into the real
    Scheduler, never through PlanValidator. Layer 1
    (AgentRuntimeFactory.create_handlers("task-a")) already means
    agent-b's handler was never built for this router in the first
    place."""

    registry = TaskAgentRegistry()
    registry.assign_agent(
        TaskAgent(agent_id="agent-a", task_id="task-a", template_id="t")
    )
    registry.assign_agent(
        TaskAgent(agent_id="agent-b", task_id="task-b", template_id="t")
    )
    runtime_factory = AgentRuntimeFactory(
        FakeAgentRegistry(["agent-a", "agent-b"]),
        registry,
        FakeTaskService(),
        FakeRunService(),
    )
    router = MessageRouter(
        runtime_factory.create_handlers("task-a"), registry
    )
    scheduler = _scheduler(router)

    invalid_plan = _plan("task-a", "agent-b")
    results = scheduler.run(invalid_plan)

    assert results[0].status == StepStatus.FAILED


def test_over_broad_router_is_still_blocked_by_dispatch_authorization() -> (
    None
):
    """Isolates Layer 2: this router is deliberately NOT built via
    AgentRuntimeFactory.create_handlers() - it holds handlers for BOTH
    agent-a and agent-b, bypassing Layer 1 entirely. Only
    MessageRouter's own membership check can stop this."""

    registry = TaskAgentRegistry()
    registry.assign_agent(
        TaskAgent(agent_id="agent-a", task_id="task-a", template_id="t")
    )
    registry.assign_agent(
        TaskAgent(agent_id="agent-b", task_id="task-b", template_id="t")
    )
    agent_a_handler = FakeAgentHandler("agent-a")
    agent_b_handler = FakeAgentHandler("agent-b")
    router = MessageRouter([agent_a_handler, agent_b_handler], registry)
    scheduler = _scheduler(router)

    results = scheduler.run(_plan("task-a", "agent-b"))

    assert results[0].status == StepStatus.FAILED
    assert agent_b_handler.calls == []


def test_released_task_rejects_execution_even_through_a_stale_router() -> (
    None
):
    """Authorization must read current TaskAgentRegistry state, not a
    snapshot taken when the router was built."""

    registry = TaskAgentRegistry()
    registry.assign_agent(
        TaskAgent(agent_id="agent-a", task_id="task-a", template_id="t")
    )
    agent_a_handler = FakeAgentHandler("agent-a")
    # Router built while task-a was still active.
    router = MessageRouter([agent_a_handler], registry)
    scheduler = _scheduler(router)

    task_repository = FakeTaskRepository({"task-a": "completed"})
    lifecycle = TaskAgentTeamLifecycle(registry)
    lifecycle.lock("task-a")
    cleanup_service = TaskAgentCleanupService(
        task_repository, registry, lifecycle
    )
    cleaned = cleanup_service.cleanup("task-a")
    assert cleaned is True
    assert registry.list_agents("task-a") == []

    results = scheduler.run(_plan("task-a", "agent-a"))

    assert results[0].status == StepStatus.FAILED
    assert agent_a_handler.calls == []


def test_cross_task_failure_does_not_corrupt_other_tasks_ownership() -> (
    None
):
    registry = TaskAgentRegistry()
    registry.assign_agent(
        TaskAgent(agent_id="agent-a", task_id="task-a", template_id="t")
    )
    registry.assign_agent(
        TaskAgent(agent_id="agent-b", task_id="task-b", template_id="t")
    )
    agent_a_handler = FakeAgentHandler("agent-a")
    agent_b_handler = FakeAgentHandler("agent-b")
    router = MessageRouter([agent_a_handler, agent_b_handler], registry)
    scheduler = _scheduler(router)

    results = scheduler.run(_plan("task-a", "agent-b"))

    assert results[0].status == StepStatus.FAILED
    assert registry.owner_task_id("agent-a") == "task-a"
    assert registry.owner_task_id("agent-b") == "task-b"
    assert registry.list_agents("task-a") == [
        TaskAgent(
            agent_id="agent-a", task_id="task-a", template_id="t"
        )
    ]
    assert registry.list_agents("task-b") == [
        TaskAgent(
            agent_id="agent-b", task_id="task-b", template_id="t"
        )
    ]
