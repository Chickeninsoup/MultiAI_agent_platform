from __future__ import annotations

from src.manager_agent import ManagerAgent
from src.task_plan import TaskPlan, TaskStep


class FakePlanner:
    def __init__(self, plan: TaskPlan) -> None:
        self._plan = plan
        self.calls: list[tuple[str, str]] = []

    def create_plan(self, request: str, task_id: str) -> TaskPlan:
        self.calls.append((request, task_id))
        return self._plan


def test_plan_delegates_to_the_injected_planner() -> None:
    expected_plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id="agent-researcher",
                description="find useful APIs",
            )
        ],
    )
    planner = FakePlanner(expected_plan)
    manager = ManagerAgent(planner=planner)

    plan = manager.plan("Build a web scraper", task_id="task-001")

    assert plan == expected_plan
    assert planner.calls == [("Build a web scraper", "task-001")]


def test_plan_returns_a_task_plan() -> None:
    manager = ManagerAgent()

    plan = manager.plan("Build a web scraper", task_id="task-001")

    assert isinstance(plan, TaskPlan)


def test_plan_uses_the_provided_task_id() -> None:
    manager = ManagerAgent()

    plan = manager.plan("Build a web scraper", task_id="task-042")

    assert plan.task_id == "task-042"


def test_plan_produces_a_single_step_assigned_to_agent_coder() -> None:
    manager = ManagerAgent()

    plan = manager.plan("Build a web scraper", task_id="task-001")

    assert len(plan.steps) == 1
    assert plan.steps[0].agent_id == "agent-coder"


def test_plan_step_description_carries_the_request() -> None:
    manager = ManagerAgent()

    plan = manager.plan("Build a web scraper", task_id="task-001")

    assert plan.steps[0].description == "Build a web scraper"
