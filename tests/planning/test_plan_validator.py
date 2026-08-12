from __future__ import annotations

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


def test_valid_plan_has_no_errors() -> None:
    registry = FakeAgentRegistry(["agent-coder"])
    validator = PlanValidator(registry)
    plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="coding",
                agent_id="agent-coder",
                description="fix the bug",
            )
        ],
    )

    result = validator.validate(plan)

    assert result.valid is True
    assert result.errors == []


def test_unknown_agent_is_reported() -> None:
    registry = FakeAgentRegistry(["agent-coder"])
    validator = PlanValidator(registry)
    plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="research",
                agent_id="agent-researcher",
                description="find useful APIs",
            )
        ],
    )

    result = validator.validate(plan)

    assert result.valid is False
    assert result.errors == ["Unknown agent: agent-researcher"]


def test_missing_dependency_is_reported() -> None:
    registry = FakeAgentRegistry(["agent-coder"])
    validator = PlanValidator(registry)
    plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="coding",
                agent_id="agent-coder",
                description="implement API",
                depends_on=["research"],
            )
        ],
    )

    result = validator.validate(plan)

    assert result.valid is False
    assert result.errors == ["Missing dependency step: research"]


def test_dependency_cycle_is_reported() -> None:
    registry = FakeAgentRegistry(["agent-coder"])
    validator = PlanValidator(registry)
    plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="a",
                agent_id="agent-coder",
                description="do a",
                depends_on=["b"],
            ),
            TaskStep(
                step_id="b",
                agent_id="agent-coder",
                description="do b",
                depends_on=["a"],
            ),
        ],
    )

    result = validator.validate(plan)

    assert result.valid is False
    assert result.errors == ["Task dependency cycle detected"]


def test_multiple_unknown_agents_are_all_reported() -> None:
    registry = FakeAgentRegistry(["agent-coder"])
    validator = PlanValidator(registry)
    plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="research",
                agent_id="agent-researcher",
                description="find useful APIs",
            ),
            TaskStep(
                step_id="review",
                agent_id="agent-reviewer",
                description="review code",
            ),
        ],
    )

    result = validator.validate(plan)

    assert result.valid is False
    assert result.errors == [
        "Unknown agent: agent-researcher",
        "Unknown agent: agent-reviewer",
    ]


def test_empty_plan_is_valid() -> None:
    registry = FakeAgentRegistry(["agent-coder"])
    validator = PlanValidator(registry)
    plan = TaskPlan(task_id="task-001", steps=[])

    result = validator.validate(plan)

    assert result.valid is True
    assert result.errors == []
