from __future__ import annotations

from src.planning.rule_based_planner import RuleBasedPlanner
from src.task_plan import TaskPlan


def test_create_plan_returns_a_task_plan() -> None:
    planner = RuleBasedPlanner()

    plan = planner.create_plan("Build a web scraper", task_id="task-001")

    assert isinstance(plan, TaskPlan)


def test_create_plan_uses_the_provided_task_id() -> None:
    planner = RuleBasedPlanner()

    plan = planner.create_plan("Build a web scraper", task_id="task-042")

    assert plan.task_id == "task-042"


def test_create_plan_produces_a_single_step_for_agent_coder() -> None:
    planner = RuleBasedPlanner()

    plan = planner.create_plan("Build a web scraper", task_id="task-001")

    assert len(plan.steps) == 1
    assert plan.steps[0].agent_id == "agent-coder"


def test_create_plan_step_description_carries_the_request() -> None:
    planner = RuleBasedPlanner()

    plan = planner.create_plan("Build a web scraper", task_id="task-001")

    assert plan.steps[0].description == "Build a web scraper"


def test_coding_request_uses_coder() -> None:
    planner = RuleBasedPlanner()

    plan = planner.create_plan("fix the login bug", "task-001")

    assert len(plan.steps) == 1
    assert plan.steps[0].agent_id == "agent-coder"
    assert plan.steps[0].depends_on == []


def test_research_and_implement_creates_dependency() -> None:
    planner = RuleBasedPlanner()

    plan = planner.create_plan(
        "research the API and implement it", "task-002"
    )

    assert len(plan.steps) == 2

    research = plan.steps[0]
    coding = plan.steps[1]

    assert research.step_id == "research"
    assert research.agent_id == "agent-researcher"
    assert research.depends_on == []

    assert coding.step_id == "coding"
    assert coding.agent_id == "agent-coder"
    assert coding.depends_on == ["research"]


def test_review_request_uses_reviewer() -> None:
    planner = RuleBasedPlanner()

    plan = planner.create_plan(
        "review the authentication changes", "task-003"
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].step_id == "review"
    assert plan.steps[0].agent_id == "agent-reviewer"


def test_rule_matching_is_case_insensitive() -> None:
    planner = RuleBasedPlanner()

    plan = planner.create_plan(
        "RESEARCH the API and IMPLEMENT it", "task-004"
    )

    assert len(plan.steps) == 2


def test_research_without_implement_or_code_falls_back_to_coding() -> (
    None
):
    planner = RuleBasedPlanner()

    plan = planner.create_plan("research the market", "task-005")

    assert len(plan.steps) == 1
    assert plan.steps[0].step_id == "coding"
    assert plan.steps[0].agent_id == "agent-coder"
