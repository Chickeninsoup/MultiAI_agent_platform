from __future__ import annotations

from src.agents.task_agent import TaskAgent
from src.agents.task_agent_registry import TaskAgentRegistry
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


class FakeTaskAgent:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id


class FakeTaskAgentRegistry:
    def __init__(self, task_agents: dict[str, list[str]]) -> None:
        self._task_agents = task_agents

    def list_agents(self, task_id: str) -> list[FakeTaskAgent]:
        return [
            FakeTaskAgent(agent_id)
            for agent_id in self._task_agents.get(task_id, [])
        ]


def _validator(
    known_agents: list[str],
    task_agents: dict[str, list[str]] | None = None,
) -> PlanValidator:
    return PlanValidator(
        FakeAgentRegistry(known_agents),
        FakeTaskAgentRegistry(task_agents or {}),
    )


def test_valid_plan_has_no_errors() -> None:
    validator = _validator(
        ["agent-coder"], {"task-001": ["agent-coder"]}
    )
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
    validator = _validator(
        ["agent-coder"], {"task-001": ["agent-coder"]}
    )
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
    assert result.error_messages() == ["Unknown agent: agent-researcher"]


def test_unknown_agent_is_repairable() -> None:
    validator = _validator(
        ["agent-coder"], {"task-001": ["agent-coder"]}
    )
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

    assert result.errors[0].code == "UNKNOWN_AGENT"
    assert result.errors[0].repairable is True
    assert result.repairable is True


def test_missing_dependency_is_reported() -> None:
    validator = _validator(
        ["agent-coder"], {"task-001": ["agent-coder"]}
    )
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
    assert result.error_messages() == [
        "Missing dependency step: research"
    ]
    assert result.errors[0].code == "MISSING_DEPENDENCY"
    assert result.errors[0].repairable is True


def test_dependency_cycle_is_reported() -> None:
    validator = _validator(
        ["agent-coder"], {"task-001": ["agent-coder"]}
    )
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
    assert result.error_messages() == ["Task dependency cycle detected"]


def test_cycle_is_repairable() -> None:
    validator = _validator(
        ["agent-coder"], {"task-001": ["agent-coder"]}
    )
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

    assert result.errors[0].code == "DEPENDENCY_CYCLE"
    assert result.errors[0].repairable


def test_multiple_unknown_agents_are_all_reported() -> None:
    validator = _validator(["agent-coder"])
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
    assert result.error_messages() == [
        "Unknown agent: agent-researcher",
        "Unknown agent: agent-reviewer",
    ]


def test_empty_plan_is_valid() -> None:
    validator = _validator(
        ["agent-coder"], {"task-001": ["agent-coder"]}
    )
    plan = TaskPlan(task_id="task-001", steps=[])

    result = validator.validate(plan)

    assert result.valid is True
    assert result.errors == []


# --- Phase 1-E: AGENT_NOT_IN_TASK ---------------------------------


def test_agent_belonging_to_current_task_is_valid() -> None:
    validator = _validator(
        ["agent-a"], {"task-a": ["agent-a"]}
    )
    plan = TaskPlan(
        task_id="task-a",
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id="agent-a",
                description="do work",
            )
        ],
    )

    result = validator.validate(plan)

    assert result.valid is True
    assert result.errors == []


def test_agent_belonging_to_another_task_is_agent_not_in_task() -> (
    None
):
    validator = _validator(
        ["agent-a", "agent-b"],
        {"task-a": ["agent-a"], "task-b": ["agent-b"]},
    )
    plan = TaskPlan(
        task_id="task-a",
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id="agent-b",
                description="do work",
            )
        ],
    )

    result = validator.validate(plan)

    assert result.valid is False
    assert [error.code for error in result.errors] == [
        "AGENT_NOT_IN_TASK"
    ]


def test_agent_not_existing_at_all_is_unknown_agent_not_not_in_task() -> (
    None
):
    validator = _validator(["agent-a"], {"task-a": ["agent-a"]})
    plan = TaskPlan(
        task_id="task-a",
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id="imaginary-agent",
                description="do work",
            )
        ],
    )

    result = validator.validate(plan)

    assert result.valid is False
    assert [error.code for error in result.errors] == ["UNKNOWN_AGENT"]


def test_mixed_steps_classify_each_agent_independently() -> None:
    validator = _validator(
        ["agent-a", "agent-b"],
        {"task-a": ["agent-a"], "task-b": ["agent-b"]},
    )
    plan = TaskPlan(
        task_id="task-a",
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id="agent-a",
                description="valid",
            ),
            TaskStep(
                step_id="step-2",
                agent_id="agent-b",
                description="belongs to task-b",
            ),
            TaskStep(
                step_id="step-3",
                agent_id="fake-agent",
                description="does not exist",
            ),
        ],
    )

    result = validator.validate(plan)

    errors_by_message = {
        error.message: error.code for error in result.errors
    }
    assert (
        errors_by_message["Agent agent-b is not assigned to task task-a"]
        == "AGENT_NOT_IN_TASK"
    )
    assert (
        errors_by_message["Unknown agent: fake-agent"] == "UNKNOWN_AGENT"
    )
    assert len(result.errors) == 2


def test_agent_not_in_task_is_repairable() -> None:
    validator = _validator(
        ["agent-a", "agent-b"],
        {"task-a": ["agent-a"], "task-b": ["agent-b"]},
    )
    plan = TaskPlan(
        task_id="task-a",
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id="agent-b",
                description="do work",
            )
        ],
    )

    result = validator.validate(plan)

    assert result.errors[0].repairable is True
    assert result.repairable is True


def test_task_isolation_through_the_real_task_agent_registry() -> None:
    task_agent_registry = TaskAgentRegistry()
    task_agent_registry.assign_agent(
        TaskAgent(
            agent_id="agent-a", task_id="task-a", template_id="coder"
        )
    )
    task_agent_registry.assign_agent(
        TaskAgent(
            agent_id="agent-b", task_id="task-b", template_id="coder"
        )
    )
    validator = PlanValidator(
        FakeAgentRegistry(["agent-a", "agent-b"]),
        task_agent_registry,
    )
    plan = TaskPlan(
        task_id="task-a",
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id="agent-b",
                description="do work",
            )
        ],
    )

    result = validator.validate(plan)

    assert [error.code for error in result.errors] == [
        "AGENT_NOT_IN_TASK"
    ]
