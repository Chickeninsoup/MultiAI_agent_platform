from __future__ import annotations

import pytest

from src.agent_message import AgentMessage
from src.message_router import MessageRouter
from src.planning.approved_plan_executor import ApprovedPlanExecutor
from src.planning.plan_approval import PlanApproval
from src.planning.plan_review import PlanReview
from src.planning.plan_validation import PlanValidationResult
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_dependency_resolver import TaskDependencyResolver
from src.task_plan import TaskPlan, TaskStep
from src.task_plan_converter import TaskPlanConverter
from src.task_plan_executor import TaskPlanExecutor
from src.task_scheduler import TaskScheduler


class FakeScheduler:
    def __init__(self) -> None:
        self.received = None

    def run(self, plan):
        self.received = plan
        return ["done"]


class FakeAgent:
    def __init__(self, agent_id: str, response: str) -> None:
        self._agent_id = agent_id
        self._response = response

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def handle(self, message: AgentMessage) -> str:
        return self._response


def _review() -> PlanReview:
    plan = TaskPlan(
        task_id="task-1",
        steps=[
            TaskStep(
                step_id="coding",
                agent_id="agent-coder",
                description="write code",
            )
        ],
    )
    return PlanReview(
        plan=plan,
        validation=PlanValidationResult(
            valid=True, errors=[], warnings=[]
        ),
        summary="summary",
    )


def test_approved_plan_is_executed() -> None:
    scheduler = FakeScheduler()
    executor = ApprovedPlanExecutor(scheduler)
    review = _review()
    approval = PlanApproval(review=review, status="approved")

    result = executor.execute(approval)

    assert result == ["done"]
    assert scheduler.received is review.plan


def test_pending_plan_is_blocked() -> None:
    scheduler = FakeScheduler()
    executor = ApprovedPlanExecutor(scheduler)
    approval = PlanApproval(review=_review(), status="pending")

    with pytest.raises(ValueError):
        executor.execute(approval)

    assert scheduler.received is None


def test_rejected_plan_is_blocked() -> None:
    scheduler = FakeScheduler()
    executor = ApprovedPlanExecutor(scheduler)
    approval = PlanApproval(review=_review(), status="rejected")

    with pytest.raises(ValueError):
        executor.execute(approval)

    assert scheduler.received is None


def test_approved_plan_runs_through_a_real_scheduler() -> None:
    agent = FakeAgent("agent-coder", "done")
    scheduler = TaskScheduler(
        TaskDependencyResolver(),
        TaskPlanExecutor(
            TaskPlanConverter(), MessageRouter([agent])
        ),
    )
    executor = ApprovedPlanExecutor(scheduler)
    approval = PlanApproval(review=_review(), status="approved")

    result = executor.execute(approval)

    assert result == [
        StepExecutionResult(
            step_id="coding", status=StepStatus.SUCCESS, output="done"
        )
    ]
