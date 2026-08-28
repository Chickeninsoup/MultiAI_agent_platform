from __future__ import annotations

from pathlib import Path

from src.agents.agent_template import AgentTemplate
from src.agents.agent_template_repository import (
    AgentTemplateRepository,
)
from src.agents.task_agent import TaskAgent
from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.manager_agent import ManagerAgent
from src.planning.plan_repository import PlanRepository
from src.planning.plan_service import PlanService
from src.planning.task_planning_context_factory import (
    TaskPlanningContextFactory,
)
from src.task_plan import TaskPlan


class RecordingPlanner:
    """Stands in for a real Planner - just records what context it saw.

    This is the whole point of the test: proving the context an actual
    Planner receives, assembled through the real production path
    (Registry -> Factory -> ManagerAgent), is scoped to the requested
    task and nothing else.
    """

    def __init__(self) -> None:
        self.received_context = None

    def create_plan(self, request, task_id, context=None) -> TaskPlan:
        self.received_context = context
        return TaskPlan(task_id=task_id, steps=[])


class _UnusedReviewService:
    """PlanService requires a review_service; create_plan() never
    calls it, so this only needs to exist, not do anything."""

    def create_review(self, plan):
        raise NotImplementedError


def _build(tmp_path: Path) -> tuple[PlanService, RecordingPlanner]:
    registry = TaskAgentRegistry()
    templates = AgentTemplateRepository()
    templates.save(
        AgentTemplate(template_id="backend", name="Backend Developer")
    )
    templates.save(
        AgentTemplate(template_id="reviewer", name="Code Reviewer")
    )

    registry.assign_agent(
        TaskAgent(
            agent_id="agent-a", task_id="task-a", template_id="backend"
        )
    )
    registry.assign_agent(
        TaskAgent(
            agent_id="agent-b", task_id="task-b", template_id="reviewer"
        )
    )

    context_factory = TaskPlanningContextFactory(registry, templates)
    planner = RecordingPlanner()
    manager = ManagerAgent(planner=planner)
    plan_service = PlanService(
        _UnusedReviewService(),
        PlanRepository(tmp_path),
        manager,
        context_factory,
        TaskAgentTeamLifecycle(registry),
    )

    return plan_service, planner


def _agent_ids(context) -> list[str]:
    return [agent.agent_id for agent in context.available_agents]


def test_task_a_planning_context_only_contains_task_a_agents(
    tmp_path: Path,
) -> None:
    plan_service, planner = _build(tmp_path)

    plan_service.create_plan("task-a", "implement backend")

    context = planner.received_context
    assert context.task_id == "task-a"
    assert _agent_ids(context) == ["agent-a"]
    assert "agent-b" not in _agent_ids(context)


def test_task_b_planning_context_only_contains_task_b_agents(
    tmp_path: Path,
) -> None:
    plan_service, planner = _build(tmp_path)

    plan_service.create_plan("task-b", "review code")

    context = planner.received_context
    assert context.task_id == "task-b"
    assert _agent_ids(context) == ["agent-b"]
    assert "agent-a" not in _agent_ids(context)


def test_planning_both_tasks_never_leaks_agents_across_tasks(
    tmp_path: Path,
) -> None:
    plan_service, planner = _build(tmp_path)

    plan_service.create_plan("task-a", "implement backend")
    context_a = planner.received_context

    plan_service.create_plan("task-b", "review code")
    context_b = planner.received_context

    assert _agent_ids(context_a) == ["agent-a"]
    assert _agent_ids(context_b) == ["agent-b"]


def test_same_template_reused_across_tasks_but_agent_instances_are_not(
    tmp_path: Path,
) -> None:
    registry = TaskAgentRegistry()
    templates = AgentTemplateRepository()
    templates.save(
        AgentTemplate(
            template_id="backend",
            name="Backend Developer",
            capabilities=["python", "api"],
        )
    )
    registry.assign_agent(
        TaskAgent(
            agent_id="agent-a", task_id="task-a", template_id="backend"
        )
    )
    registry.assign_agent(
        TaskAgent(
            agent_id="agent-c", task_id="task-c", template_id="backend"
        )
    )
    context_factory = TaskPlanningContextFactory(registry, templates)

    context_a = context_factory.create("task-a")
    context_c = context_factory.create("task-c")

    assert context_a.available_agents[0].role == "Backend Developer"
    assert context_c.available_agents[0].role == "Backend Developer"
    assert _agent_ids(context_a) != _agent_ids(context_c)


def test_empty_agent_task_produces_a_context_with_no_agents(
    tmp_path: Path,
) -> None:
    plan_service, planner = _build(tmp_path)

    plan_service.create_plan("task-empty", "do something")

    assert planner.received_context.available_agents == []
