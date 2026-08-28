from __future__ import annotations

from src.agent_message import AgentMessage
from src.agents.task_agent import TaskAgent
from src.agents.task_agent_registry import TaskAgentRegistry
from src.failure_classifier import FailureClassifier
from src.failure_retry_classifier import FailureRetryClassifier
from src.message_router import MessageRouter
from src.retry_manager import RetryManager
from src.retry_policy import RetryPolicy
from src.step_execution_result import StepStatus
from src.task_dependency_resolver import TaskDependencyResolver
from src.task_plan import TaskPlan, TaskStep
from src.task_plan_converter import TaskPlanConverter
from src.task_plan_executor import TaskPlanExecutor
from src.task_scheduler import TaskScheduler


def _registry(*agent_ids: str) -> TaskAgentRegistry:
    registry = TaskAgentRegistry()

    for agent_id in agent_ids:
        registry.assign_agent(
            TaskAgent(
                agent_id=agent_id, task_id="task-1", template_id="t"
            )
        )

    return registry


class AlwaysFailingAgent:
    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        self.call_count = 0

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def handle(self, message: AgentMessage) -> str:
        self.call_count += 1
        raise TimeoutError("permanent failure")


class FakeAgent:
    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        self.call_count = 0

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def handle(self, message: AgentMessage) -> str:
        self.call_count += 1
        return "done"


def test_failed_retry_blocks_dependency() -> None:
    agent_a = AlwaysFailingAgent("agent-a")
    agent_b = FakeAgent("agent-b")
    scheduler = TaskScheduler(
        TaskDependencyResolver(),
        TaskPlanExecutor(
            TaskPlanConverter(),
            MessageRouter([agent_a, agent_b], _registry("agent-a", "agent-b")),
        ),
        FailureClassifier(),
        retry_manager=RetryManager(RetryPolicy(max_attempts=2), FailureRetryClassifier()),
    )
    plan = TaskPlan(
        task_id="task-1",
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

    result = scheduler.run(plan)

    assert result[0].status == StepStatus.FAILED
    assert result[0].attempt == 2
    assert result[1].status == StepStatus.SKIPPED
    assert agent_a.call_count == 2
    assert agent_b.call_count == 0


def test_retry_succeeding_before_exhaustion_unblocks_dependency() -> (
    None
):
    class RecoversOnSecondTry:
        def __init__(self, agent_id: str) -> None:
            self._agent_id = agent_id
            self.call_count = 0

        @property
        def agent_id(self) -> str:
            return self._agent_id

        def handle(self, message: AgentMessage) -> str:
            self.call_count += 1
            if self.call_count == 1:
                raise TimeoutError("transient")
            return "recovered"

    agent_a = RecoversOnSecondTry("agent-a")
    agent_b = FakeAgent("agent-b")
    scheduler = TaskScheduler(
        TaskDependencyResolver(),
        TaskPlanExecutor(
            TaskPlanConverter(),
            MessageRouter([agent_a, agent_b], _registry("agent-a", "agent-b")),
        ),
        FailureClassifier(),
        retry_manager=RetryManager(RetryPolicy(max_attempts=2), FailureRetryClassifier()),
    )
    plan = TaskPlan(
        task_id="task-1",
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

    result = scheduler.run(plan)

    assert result[0].status == StepStatus.SUCCESS
    assert result[1].status == StepStatus.SUCCESS
    assert agent_b.call_count == 1


def test_skip_still_propagates_transitively_through_a_retried_failure() -> (
    None
):
    agent_a = AlwaysFailingAgent("agent-a")
    agent_b = FakeAgent("agent-b")
    agent_c = FakeAgent("agent-c")
    scheduler = TaskScheduler(
        TaskDependencyResolver(),
        TaskPlanExecutor(
            TaskPlanConverter(),
            MessageRouter([agent_a, agent_b, agent_c], _registry("agent-a", "agent-b", "agent-c")),
        ),
        FailureClassifier(),
        retry_manager=RetryManager(RetryPolicy(max_attempts=2), FailureRetryClassifier()),
    )
    plan = TaskPlan(
        task_id="task-1",
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
            TaskStep(
                step_id="C",
                agent_id="agent-c",
                description="do c",
                depends_on=["B"],
            ),
        ],
    )

    result = scheduler.run(plan)

    assert result[0].status == StepStatus.FAILED
    assert result[1].status == StepStatus.SKIPPED
    assert result[2].status == StepStatus.SKIPPED
    assert agent_b.call_count == 0
    assert agent_c.call_count == 0
