from __future__ import annotations

from src.planning.plan_review_service import PlanReviewService
from src.planning.plan_validator import PlanValidator
from src.task_plan import TaskPlan, TaskStep


class FakeAgent:
    def __init__(self, agent_id: str) -> None:
        self.id = agent_id


class FakeAgentRegistry:
    def __init__(self, agent_ids: list[str]) -> None:
        self._agents = [FakeAgent(agent_id) for agent_id in agent_ids]

    def list_agents(self) -> list[FakeAgent]:
        return self._agents


def _service(agent_ids: list[str]) -> PlanReviewService:
    return PlanReviewService(
        PlanValidator(FakeAgentRegistry(agent_ids))
    )


def test_valid_plan_produces_a_passing_review() -> None:
    service = _service(["agent-coder"])
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

    review = service.create_review(plan)

    assert review.validation.valid is True
    assert "Task Plan: task-1" in review.summary
    assert "Validation: PASSED" in review.summary
    assert "agent-coder" in review.summary


def test_invalid_plan_shows_validation_errors_in_summary() -> None:
    service = _service(["agent-coder"])
    plan = TaskPlan(
        task_id="task-1",
        steps=[
            TaskStep(
                step_id="research",
                agent_id="missing-agent",
                description="find useful APIs",
            )
        ],
    )

    review = service.create_review(plan)

    assert review.validation.valid is False
    assert "Validation: FAILED" in review.summary
    assert "Unknown agent: missing-agent" in review.summary


def test_summary_shows_step_dependencies() -> None:
    service = _service(["agent-researcher", "agent-coder"])
    plan = TaskPlan(
        task_id="task-1",
        steps=[
            TaskStep(
                step_id="research",
                agent_id="agent-researcher",
                description="find useful APIs",
            ),
            TaskStep(
                step_id="coding",
                agent_id="agent-coder",
                description="implement API",
                depends_on=["research"],
            ),
        ],
    )

    review = service.create_review(plan)

    assert "Depends on: research" in review.summary
    assert "Depends on: None" in review.summary


def test_create_review_does_not_mutate_the_plan() -> None:
    service = _service(["agent-coder"])
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

    review = service.create_review(plan)

    assert review.plan is plan
    assert review.plan == plan
