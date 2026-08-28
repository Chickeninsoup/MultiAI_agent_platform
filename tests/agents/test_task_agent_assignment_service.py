from __future__ import annotations

import pytest

from src.agents.agent_template_errors import AgentTemplateMismatchError
from src.agents.task_agent_assignment_errors import (
    AgentAlreadyAssignedElsewhereError,
    AgentAlreadyAssignedToTaskError,
    AgentNotFoundForAssignmentError,
    TaskAgentTeamLockedError,
    TaskAgentTeamReleasedError,
    TaskNotFoundForAssignmentError,
)
from src.agents.task_agent_assignment_service import (
    TaskAgentAssignmentService,
)
from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle


class FakeAgentDefinition:
    def __init__(self, agent_id: str, template_id: str) -> None:
        self.id = agent_id
        self.template_id = template_id


class FakeAgentRegistry:
    """Defaults every agent's template_id to "coder" so existing
    callers that assign against template_id="coder" don't need to
    know about template linkage - only tests exercising 5E-4E-1A's
    mismatch behavior need to pass a differing template_ids map."""

    def __init__(
        self,
        agent_ids: list[str],
        template_ids: dict[str, str] | None = None,
    ) -> None:
        self._agent_ids = set(agent_ids)
        self._template_ids = template_ids or {}

    def get_agent(self, agent_id: str) -> FakeAgentDefinition:
        if agent_id not in self._agent_ids:
            raise FileNotFoundError(agent_id)

        return FakeAgentDefinition(
            agent_id, self._template_ids.get(agent_id, "coder")
        )


class FakeTaskRepository:
    def __init__(self, task_ids: list[str]) -> None:
        self._task_ids = set(task_ids)

    def load(self, task_id: str) -> object:
        if task_id not in self._task_ids:
            raise FileNotFoundError(task_id)

        return object()


def _service(
    agent_ids: list[str],
    task_ids: list[str],
    registry: TaskAgentRegistry | None = None,
    lifecycle: TaskAgentTeamLifecycle | None = None,
    template_ids: dict[str, str] | None = None,
) -> tuple[
    TaskAgentAssignmentService, TaskAgentRegistry, TaskAgentTeamLifecycle
]:
    task_agent_registry = registry or TaskAgentRegistry()
    team_lifecycle = lifecycle or TaskAgentTeamLifecycle(
        task_agent_registry
    )
    service = TaskAgentAssignmentService(
        FakeAgentRegistry(agent_ids, template_ids),
        task_agent_registry,
        FakeTaskRepository(task_ids),
        team_lifecycle,
    )
    return service, task_agent_registry, team_lifecycle


def test_normal_assignment_creates_a_task_agent() -> None:
    service, registry, _lifecycle = _service(["agent-coder"], ["task-a"])

    result = service.assign("task-a", "agent-coder", "coder")

    assert result.agent_id == "agent-coder"
    assert result.task_id == "task-a"
    assert registry.get_agent("task-a", "agent-coder") == result


def test_assign_to_a_missing_task_raises_and_does_not_mutate() -> None:
    service, registry, _lifecycle = _service(["agent-coder"], [])

    with pytest.raises(TaskNotFoundForAssignmentError):
        service.assign("task-x", "agent-coder", "coder")

    assert registry.list_agents("task-x") == []
    assert registry.owner_task_id("agent-coder") is None


def test_assign_a_missing_agent_raises() -> None:
    service, _registry, _lifecycle = _service([], ["task-a"])

    with pytest.raises(AgentNotFoundForAssignmentError):
        service.assign("task-a", "agent-imaginary", "coder")


def test_duplicate_assignment_to_the_same_task_raises() -> None:
    service, registry, _lifecycle = _service(["agent-coder"], ["task-a"])
    service.assign("task-a", "agent-coder", "coder")

    with pytest.raises(AgentAlreadyAssignedToTaskError):
        service.assign("task-a", "agent-coder", "coder")

    assert len(registry.list_agents("task-a")) == 1


def test_agent_cannot_be_assigned_to_two_tasks() -> None:
    service, registry, _lifecycle = _service(
        ["agent-coder"], ["task-a", "task-b"]
    )
    service.assign("task-a", "agent-coder", "coder")

    with pytest.raises(AgentAlreadyAssignedElsewhereError):
        service.assign("task-b", "agent-coder", "coder")

    assert registry.list_agents("task-b") == []
    assert registry.owner_task_id("agent-coder") == "task-a"


def test_assignment_to_a_locked_team_is_rejected() -> None:
    service, registry, lifecycle = _service(["agent-coder"], ["task-a"])
    lifecycle.lock("task-a")

    with pytest.raises(TaskAgentTeamLockedError):
        service.assign("task-a", "agent-coder", "coder")

    assert registry.list_agents("task-a") == []


def test_assignment_to_a_released_team_is_rejected() -> None:
    service, registry, lifecycle = _service(["agent-coder"], ["task-a"])
    lifecycle.lock("task-a")
    lifecycle.release("task-a")

    with pytest.raises(TaskAgentTeamReleasedError):
        service.assign("task-a", "agent-coder", "coder")

    assert registry.list_agents("task-a") == []


def test_assignment_allowed_to_another_task_after_release() -> None:
    registry = TaskAgentRegistry()
    lifecycle = TaskAgentTeamLifecycle(registry)
    service, registry, lifecycle = _service(
        ["agent-coder"],
        ["task-a", "task-b"],
        registry=registry,
        lifecycle=lifecycle,
    )
    service.assign("task-a", "agent-coder", "coder")
    lifecycle.lock("task-a")
    lifecycle.release("task-a")

    result = service.assign("task-b", "agent-coder", "coder")

    assert result.task_id == "task-b"
    assert registry.owner_task_id("agent-coder") == "task-b"


def test_assignment_rejects_template_mismatch() -> None:
    service, registry, _lifecycle = _service(
        ["agent-a"],
        ["task-a"],
        template_ids={"agent-a": "backend-template"},
    )

    with pytest.raises(AgentTemplateMismatchError):
        service.assign("task-a", "agent-a", "reviewer-template")

    assert registry.list_agents("task-a") == []
    assert registry.owner_task_id("agent-a") is None


def test_assignment_succeeds_when_template_matches_agent_definition() -> (
    None
):
    service, registry, _lifecycle = _service(
        ["agent-a"],
        ["task-a"],
        template_ids={"agent-a": "backend-template"},
    )

    result = service.assign("task-a", "agent-a", "backend-template")

    assert result.template_id == "backend-template"
    assert registry.owner_task_id("agent-a") == "task-a"


def test_same_agent_definition_reusable_through_same_template() -> None:
    service, registry, lifecycle = _service(
        ["agent-a"],
        ["task-a", "task-b"],
        template_ids={"agent-a": "backend-template"},
    )
    service.assign("task-a", "agent-a", "backend-template")
    lifecycle.lock("task-a")
    lifecycle.release("task-a")

    result = service.assign("task-b", "agent-a", "backend-template")

    assert result.task_id == "task-b"
    assert registry.owner_task_id("agent-a") == "task-b"


def test_different_agent_definitions_can_share_the_same_template() -> (
    None
):
    service, registry, _lifecycle = _service(
        ["agent-a", "agent-b"],
        ["task-a"],
        template_ids={
            "agent-a": "backend-template",
            "agent-b": "backend-template",
        },
    )

    result_a = service.assign("task-a", "agent-a", "backend-template")
    result_b = service.assign("task-a", "agent-b", "backend-template")

    assert result_a.template_id == "backend-template"
    assert result_b.template_id == "backend-template"
    assert {
        agent.agent_id for agent in registry.list_agents("task-a")
    } == {"agent-a", "agent-b"}
