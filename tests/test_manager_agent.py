from __future__ import annotations

from src.agents.task_agent_info import TaskAgentInfo
from src.manager_agent import ManagerAgent
from src.planning.claude_planner import ClaudePlanner
from src.planning.planning_context import PlanningContext
from src.planning.rule_based_planner import RuleBasedPlanner
from src.planning.task_planning_context import TaskPlanningContext
from src.task_plan import TaskPlan, TaskStep


class FakePlanner:
    def __init__(self, plan: TaskPlan) -> None:
        self._plan = plan
        self.calls: list[tuple[str, str]] = []
        self.received = None

    def create_plan(
        self,
        request: str,
        task_id: str,
        context: PlanningContext | None = None,
    ) -> TaskPlan:
        self.calls.append((request, task_id))
        self.received = context
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


def test_plan_forwards_context_to_the_planner() -> None:
    planner = FakePlanner(TaskPlan(task_id="task1", steps=[]))
    manager = ManagerAgent(planner=planner)
    context = PlanningContext(available_agents=["coder"])

    manager.plan("build feature", "task1", context)

    assert planner.received is context


def test_manager_passes_task_planning_context() -> None:
    planner = FakePlanner(TaskPlan(task_id="task1", steps=[]))
    manager = ManagerAgent(planner=planner)
    context = TaskPlanningContext(
        task_id="task1",
        available_agents=[
            TaskAgentInfo(agent_id="coder", role="Backend Developer")
        ],
    )

    manager.plan("build feature", "task1", context)

    assert planner.received is context


def test_plan_forwards_none_when_no_context_is_given() -> None:
    planner = FakePlanner(TaskPlan(task_id="task1", steps=[]))
    manager = ManagerAgent(planner=planner)

    manager.plan("build feature", "task1")

    assert planner.received is None


class FakeProvider:
    def complete(self, prompt: str) -> str:
        return '{"steps": []}'


def test_manager_accepts_claude_planner() -> None:
    manager = ManagerAgent(
        planner=ClaudePlanner(provider=FakeProvider())
    )

    assert isinstance(manager._planner, ClaudePlanner)


def test_manager_default_planner_is_still_rule_based() -> None:
    manager = ManagerAgent()

    assert isinstance(manager._planner, RuleBasedPlanner)


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
