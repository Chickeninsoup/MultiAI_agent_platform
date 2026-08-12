from __future__ import annotations

from src.manager_agent import ManagerAgent
from src.task_plan import TaskPlan


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
