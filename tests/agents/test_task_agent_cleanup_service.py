from __future__ import annotations

import pytest

from src.agents.task_agent import TaskAgent
from src.agents.task_agent_cleanup_errors import (
    TaskNotFoundForCleanupError,
)
from src.agents.task_agent_cleanup_service import TaskAgentCleanupService
from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.agents.task_agent_team_state import TaskAgentTeamState
from src.models import TaskDefinition


class FakeTaskRepository:
    def __init__(self, tasks: dict[str, TaskDefinition]) -> None:
        self._tasks = dict(tasks)
        self.save_calls = 0

    def load(self, task_id: str) -> TaskDefinition:
        if task_id not in self._tasks:
            raise FileNotFoundError(task_id)

        return self._tasks[task_id]

    def save(self, task: TaskDefinition) -> None:
        self._tasks[task.id] = task
        self.save_calls += 1


def _task(task_id: str = "task-a", status: str = "completed") -> TaskDefinition:
    return TaskDefinition(
        id=task_id,
        title="Build a feature",
        description="Implement the requested feature",
        workspace_id="workspace-main",
        status=status,
        priority="normal",
        created_by="user-1",
        assigned_agents=["agent-coder"],
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        started_at="2026-01-01T00:00:00Z",
        completed_at=(
            "2026-01-01T00:05:00Z" if status == "completed" else None
        ),
        abandoned_at=None,
        current_run_id="run-001",
        run_count=1,
        completion_criteria=[],
        tags=[],
    )


def test_completed_task_can_be_cleaned_up() -> None:
    task_repository = FakeTaskRepository({"task-a": _task()})
    registry = TaskAgentRegistry()
    registry.assign_agent(
        TaskAgent(
            agent_id="agent-coder", task_id="task-a", template_id="coder"
        )
    )
    lifecycle = TaskAgentTeamLifecycle(registry)
    service = TaskAgentCleanupService(task_repository, registry, lifecycle)

    cleaned = service.cleanup("task-a")

    assert cleaned is True
    assert registry.list_agents("task-a") == []
    assert registry.owner_task_id("agent-coder") is None


def test_cleanup_sets_team_state_to_released() -> None:
    task_repository = FakeTaskRepository({"task-a": _task()})
    registry = TaskAgentRegistry()
    lifecycle = TaskAgentTeamLifecycle(registry)
    service = TaskAgentCleanupService(task_repository, registry, lifecycle)

    service.cleanup("task-a")

    assert lifecycle.state("task-a") is TaskAgentTeamState.RELEASED


def test_in_progress_task_cleanup_is_refused_without_mutation() -> None:
    task_repository = FakeTaskRepository(
        {"task-a": _task(status="in_progress")}
    )
    registry = TaskAgentRegistry()
    registry.assign_agent(
        TaskAgent(
            agent_id="agent-coder", task_id="task-a", template_id="coder"
        )
    )
    lifecycle = TaskAgentTeamLifecycle(registry)
    lifecycle.lock("task-a")
    service = TaskAgentCleanupService(task_repository, registry, lifecycle)

    cleaned = service.cleanup("task-a")

    assert cleaned is False
    assert registry.get_agent("task-a", "agent-coder") is not None
    assert lifecycle.state("task-a") is TaskAgentTeamState.LOCKED


def test_missing_task_raises_and_does_not_mutate() -> None:
    task_repository = FakeTaskRepository({})
    registry = TaskAgentRegistry()
    registry.assign_agent(
        TaskAgent(
            agent_id="agent-coder", task_id="task-a", template_id="coder"
        )
    )
    lifecycle = TaskAgentTeamLifecycle(registry)
    service = TaskAgentCleanupService(task_repository, registry, lifecycle)

    with pytest.raises(TaskNotFoundForCleanupError):
        service.cleanup("missing-task")

    assert registry.get_agent("task-a", "agent-coder") is not None
    assert lifecycle.state("task-a") is TaskAgentTeamState.OPEN


def test_cleanup_does_not_affect_other_tasks() -> None:
    task_repository = FakeTaskRepository(
        {"task-a": _task("task-a"), "task-b": _task("task-b", "in_progress")}
    )
    registry = TaskAgentRegistry()
    registry.assign_agent(
        TaskAgent(
            agent_id="agent-a", task_id="task-a", template_id="coder"
        )
    )
    agent_b = TaskAgent(
        agent_id="agent-b", task_id="task-b", template_id="coder"
    )
    registry.assign_agent(agent_b)
    lifecycle = TaskAgentTeamLifecycle(registry)
    service = TaskAgentCleanupService(task_repository, registry, lifecycle)

    service.cleanup("task-a")

    assert registry.list_agents("task-a") == []
    assert registry.list_agents("task-b") == [agent_b]
    assert lifecycle.state("task-b") is TaskAgentTeamState.OPEN


def test_cleanup_is_idempotent() -> None:
    task_repository = FakeTaskRepository({"task-a": _task()})
    registry = TaskAgentRegistry()
    registry.assign_agent(
        TaskAgent(
            agent_id="agent-coder", task_id="task-a", template_id="coder"
        )
    )
    lifecycle = TaskAgentTeamLifecycle(registry)
    service = TaskAgentCleanupService(task_repository, registry, lifecycle)

    first = service.cleanup("task-a")
    second = service.cleanup("task-a")

    assert first is True
    assert second is True
    assert registry.list_agents("task-a") == []
    assert lifecycle.state("task-a") is TaskAgentTeamState.RELEASED
