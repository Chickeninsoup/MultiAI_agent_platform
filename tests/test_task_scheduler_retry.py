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


class FlakyAgent:
    """Fails its first N calls, then succeeds - simulates a
    transient error (e.g. a network blip) that a retry should
    recover from."""

    def __init__(self, agent_id: str, failures_before_success: int) -> None:
        self._agent_id = agent_id
        self._remaining_failures = failures_before_success
        self.call_count = 0

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def handle(self, message: AgentMessage) -> str:
        self.call_count += 1

        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise TimeoutError("transient failure")

        return "done"


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


def _plan(step_id: str = "a") -> TaskPlan:
    return TaskPlan(
        task_id="task-1",
        steps=[
            TaskStep(
                step_id=step_id,
                agent_id="agent-flaky",
                description="do it",
            )
        ],
    )


def test_scheduler_retries_a_failed_step_until_it_succeeds() -> None:
    agent = FlakyAgent("agent-flaky", failures_before_success=1)
    scheduler = TaskScheduler(
        TaskDependencyResolver(),
        TaskPlanExecutor(
            TaskPlanConverter(), MessageRouter([agent], _registry("agent-flaky"))
        ),
        FailureClassifier(),
        retry_manager=RetryManager(RetryPolicy(max_attempts=2), FailureRetryClassifier()),
    )

    results = scheduler.run(_plan())

    assert results[0].status == StepStatus.SUCCESS
    assert results[0].attempt == 2
    assert agent.call_count == 2


def test_scheduler_returns_final_failure_after_exhausting_retries() -> (
    None
):
    agent = AlwaysFailingAgent("agent-flaky")
    scheduler = TaskScheduler(
        TaskDependencyResolver(),
        TaskPlanExecutor(
            TaskPlanConverter(), MessageRouter([agent], _registry("agent-flaky"))
        ),
        FailureClassifier(),
        retry_manager=RetryManager(RetryPolicy(max_attempts=3), FailureRetryClassifier()),
    )

    results = scheduler.run(_plan())

    assert results[0].status == StepStatus.FAILED
    assert results[0].attempt == 3
    assert agent.call_count == 3


def test_scheduler_without_a_retry_manager_does_not_retry() -> None:
    agent = FlakyAgent("agent-flaky", failures_before_success=1)
    scheduler = TaskScheduler(
        TaskDependencyResolver(),
        TaskPlanExecutor(
            TaskPlanConverter(), MessageRouter([agent], _registry("agent-flaky"))
        ),
        FailureClassifier(),
    )

    results = scheduler.run(_plan())

    assert results[0].status == StepStatus.FAILED
    assert agent.call_count == 1


def test_wave_still_runs_concurrently_with_retries_configured() -> None:
    agent_a = FlakyAgent("agent-a", failures_before_success=0)
    agent_b = FlakyAgent("agent-b", failures_before_success=0)
    scheduler = TaskScheduler(
        TaskDependencyResolver(),
        TaskPlanExecutor(
            TaskPlanConverter(), MessageRouter([agent_a, agent_b], _registry("agent-a", "agent-b"))
        ),
        FailureClassifier(),
        retry_manager=RetryManager(RetryPolicy(max_attempts=2), FailureRetryClassifier()),
    )
    plan = TaskPlan(
        task_id="task-1",
        steps=[
            TaskStep(
                step_id="a", agent_id="agent-a", description="do a"
            ),
            TaskStep(
                step_id="b", agent_id="agent-b", description="do b"
            ),
        ],
    )

    results = scheduler.run(plan)

    assert {r.status for r in results} == {StepStatus.SUCCESS}
    assert agent_a.call_count == 1
    assert agent_b.call_count == 1
