from __future__ import annotations

from src.agent_message import AgentMessage
from src.message_router import MessageRouter
from src.task_plan import TaskPlan, TaskStep
from src.task_plan_converter import TaskPlanConverter
from src.task_plan_executor import TaskPlanExecutor


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


def test_execute_runs_a_single_step_plan() -> None:
    coder = FakeAgent("agent-coder", "done")
    executor = TaskPlanExecutor(
        TaskPlanConverter(), MessageRouter([coder])
    )
    plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id="agent-coder",
                description="implement login",
            )
        ],
    )

    results = executor.execute(plan)

    assert results == ["done"]
    assert len(coder.received_messages) == 1


def test_execute_runs_multiple_steps_in_order() -> None:
    researcher = FakeAgent("agent-researcher", "research finished")
    coder = FakeAgent("agent-coder", "coder finished")
    executor = TaskPlanExecutor(
        TaskPlanConverter(), MessageRouter([researcher, coder])
    )
    plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id="agent-researcher",
                description="find useful APIs",
            ),
            TaskStep(
                step_id="step-2",
                agent_id="agent-coder",
                description="implement scraper",
            ),
        ],
    )

    results = executor.execute(plan)

    assert results == ["research finished", "coder finished"]


def test_execute_runs_steps_with_depends_on_in_list_order() -> None:
    researcher = FakeAgent("agent-researcher", "research finished")
    coder = FakeAgent("agent-coder", "coder finished")
    executor = TaskPlanExecutor(
        TaskPlanConverter(), MessageRouter([researcher, coder])
    )
    plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id="agent-researcher",
                description="find useful APIs",
            ),
            TaskStep(
                step_id="step-2",
                agent_id="agent-coder",
                description="implement scraper",
                depends_on=["step-1"],
            ),
        ],
    )

    results = executor.execute(plan)

    assert results == ["research finished", "coder finished"]


def test_execute_returns_empty_list_for_empty_plan() -> None:
    executor = TaskPlanExecutor(TaskPlanConverter(), MessageRouter([]))
    plan = TaskPlan(task_id="task-001", steps=[])

    assert executor.execute(plan) == []


def test_execute_steps_runs_only_the_given_steps() -> None:
    coder = FakeAgent("agent-coder", "coder finished")
    executor = TaskPlanExecutor(
        TaskPlanConverter(), MessageRouter([coder])
    )
    step = TaskStep(
        step_id="step-1",
        agent_id="agent-coder",
        description="implement login",
    )

    results = executor.execute_steps([step], "task-001")

    assert results == ["coder finished"]
    assert coder.received_messages[0].task_id == "task-001"


def test_execute_steps_returns_empty_list_for_empty_steps() -> None:
    executor = TaskPlanExecutor(TaskPlanConverter(), MessageRouter([]))

    assert executor.execute_steps([], "task-001") == []
