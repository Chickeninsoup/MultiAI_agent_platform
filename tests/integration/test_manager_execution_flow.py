from __future__ import annotations

import pytest

from src.agent_handlers.llm_agent_handler import LLMAgentHandler
from src.agent_message import AgentMessage
from src.agents.task_agent import TaskAgent
from src.agents.task_agent_registry import TaskAgentRegistry
from src.manager_agent import ManagerAgent
from src.message_router import MessageRouter
from src.task_plan import TaskPlan, TaskStep
from src.task_plan_converter import TaskPlanConverter
from src.task_plan_executor import TaskPlanExecutor


def _registry(task_id: str, *agent_ids: str) -> TaskAgentRegistry:
    registry = TaskAgentRegistry()

    for agent_id in agent_ids:
        registry.assign_agent(
            TaskAgent(
                agent_id=agent_id, task_id=task_id, template_id="t"
            )
        )

    return registry


class FakeAgent:
    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        self.received_messages: list[AgentMessage] = []

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def handle(self, message: AgentMessage) -> str:
        self.received_messages.append(message)
        return f"{self._agent_id} completed: {message.content}"


def test_manager_execution_flow() -> None:
    agent = FakeAgent("agent-coder")
    router = MessageRouter(
        [agent], _registry("task-001", "agent-coder")
    )
    converter = TaskPlanConverter()
    executor = TaskPlanExecutor(converter, router)
    manager = ManagerAgent()

    plan = manager.plan(
        request="implement login feature",
        task_id="task-001",
    )

    assert plan.task_id == "task-001"
    assert len(plan.steps) == 1
    assert plan.steps[0].agent_id == "agent-coder"

    results = executor.execute(plan)

    assert results == ["agent-coder completed: implement login feature"]

    assert len(agent.received_messages) == 1
    message = agent.received_messages[0]
    assert message.sender_id == "agent-manager"
    assert message.receiver_id == "agent-coder"
    assert message.task_id == "task-001"
    assert message.content == "implement login feature"


def test_multi_step_plan_executes_each_step_in_order() -> None:
    agent_a = FakeAgent("agent-a")
    agent_b = FakeAgent("agent-b")
    router = MessageRouter(
        [agent_a, agent_b],
        _registry("task-002", "agent-a", "agent-b"),
    )
    executor = TaskPlanExecutor(TaskPlanConverter(), router)

    plan = TaskPlan(
        task_id="task-002",
        steps=[
            TaskStep(
                step_id="1",
                agent_id="agent-a",
                description="research",
            ),
            TaskStep(
                step_id="2",
                agent_id="agent-b",
                description="code",
            ),
        ],
    )

    results = executor.execute(plan)

    assert results == [
        "agent-a completed: research",
        "agent-b completed: code",
    ]
    assert len(agent_a.received_messages) == 1
    assert len(agent_b.received_messages) == 1


def test_execute_raises_for_unknown_agent() -> None:
    # "missing" is assigned to task-003 (membership passes) but no
    # handler for it was ever built - this is specifically testing
    # the "assigned but unreachable" runtime error, not authorization.
    router = MessageRouter([], _registry("task-003", "missing"))
    executor = TaskPlanExecutor(TaskPlanConverter(), router)

    plan = TaskPlan(
        task_id="task-003",
        steps=[
            TaskStep(
                step_id="1",
                agent_id="missing",
                description="test",
            )
        ],
    )

    with pytest.raises(ValueError, match="Unknown agent: missing"):
        executor.execute(plan)


class _FakeTask:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class _FakeRunResult:
    def __init__(self) -> None:
        self.run_id = "run-001"
        self.status = "completed"
        self.output_path = "tasks/task-001/runs/run-001/output.md"


class FakeTaskService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_task_and_run(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeTask(kwargs["task_id"]), None


class FakeRunService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, task_id: str):
        self.calls.append(task_id)
        return _FakeRunResult()


def test_manager_request_reaches_task_and_run_services_via_real_handler() -> (
    None
):
    task_service = FakeTaskService()
    run_service = FakeRunService()
    handler = LLMAgentHandler("agent-coder", task_service, run_service)
    executor = TaskPlanExecutor(
        TaskPlanConverter(),
        MessageRouter(
            [handler], _registry("task-001", "agent-coder")
        ),
    )
    manager = ManagerAgent()

    plan = manager.plan("fix authentication bug", task_id="task-001")
    results = executor.execute(plan)

    assert results == [
        "Run run-001 finished with status 'completed'. "
        "Output: tasks/task-001/runs/run-001/output.md"
    ]
    assert task_service.calls == [
        {
            "task_id": "task-001",
            "title": "fix authentication bug",
            "description": "fix authentication bug",
            "agent_id": "agent-coder",
            "input_text": "fix authentication bug",
            "created_by": "agent-manager",
        }
    ]
    assert run_service.calls == ["task-001"]
