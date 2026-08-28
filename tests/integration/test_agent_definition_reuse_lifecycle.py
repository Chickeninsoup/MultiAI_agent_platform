from __future__ import annotations

from pathlib import Path

from src.agents.task_agent_assignment_service import (
    TaskAgentAssignmentService,
)
from src.agents.task_agent_cleanup_service import TaskAgentCleanupService
from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.planning.plan_execution_result import PlanExecutionResult
from src.planning.task_completion_service import TaskCompletionService
from src.repositories import RunRepository, TaskRepository
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_service import TaskService


class FakeAgentDefinition:
    def __init__(self, agent_id: str, template_id: str = "template-1") -> None:
        self.id = agent_id
        self.template_id = template_id


class FakeAgentRegistry:
    """Stands in for the real, file-backed AgentRegistry - the object
    under test here is the *lifecycle policy*, not AgentRepository's
    own persistence, which is already covered elsewhere."""

    def __init__(self, agent_ids: list[str]) -> None:
        self._ids = set(agent_ids)

    def get_agent(self, agent_id: str) -> FakeAgentDefinition:
        if agent_id not in self._ids:
            raise FileNotFoundError(agent_id)

        return FakeAgentDefinition(agent_id)


def _create_task(task_service: TaskService, task_id: str) -> None:
    task_service.create_task_and_run(
        task_id=task_id,
        title="Build a feature",
        description="Implement the requested feature",
        agent_id="agent-a",
        input_text="implement the feature",
        created_by="user-1",
    )


def _successful_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="step-1", status=StepStatus.SUCCESS, output="done"
            )
        ]
    )


def test_agent_definition_survives_task_completion_and_is_reassigned(
    tmp_path: Path,
) -> None:
    """The core 5E-4E policy test: Task completion + cleanup destroys
    TaskAgent membership only. The underlying AgentDefinition is a
    persistent, reusable asset - it survives cleanup and can be
    assigned to a brand new Task without being recreated."""

    task_repository = TaskRepository(tmp_path)
    run_repository = RunRepository(tmp_path)
    task_service = TaskService(
        task_repository=task_repository, run_repository=run_repository
    )

    agent_registry = FakeAgentRegistry(["agent-a"])
    task_agent_registry = TaskAgentRegistry()
    team_lifecycle = TaskAgentTeamLifecycle(task_agent_registry)
    assignment_service = TaskAgentAssignmentService(
        agent_registry,
        task_agent_registry,
        task_repository,
        team_lifecycle,
    )
    completion_service = TaskCompletionService(task_repository)
    cleanup_service = TaskAgentCleanupService(
        task_repository, task_agent_registry, team_lifecycle
    )

    _create_task(task_service, "task-a")
    _create_task(task_service, "task-b")

    # --- Task A: assign, lock, complete, cleanup ---
    assignment_service.assign("task-a", "agent-a", "template-1")
    assert task_agent_registry.owner_task_id("agent-a") == "task-a"

    team_lifecycle.lock("task-a")
    completed = completion_service.complete_if_successful(
        "task-a", _successful_result()
    )
    assert completed is True

    cleaned = cleanup_service.cleanup("task-a")
    assert cleaned is True
    assert task_agent_registry.owner_task_id("agent-a") is None
    assert task_agent_registry.list_agents("task-a") == []

    # --- The persistent asset must still be there ---
    assert agent_registry.get_agent("agent-a").id == "agent-a"

    # --- Task B: the same AgentDefinition can be reassigned, no
    # recreation needed ---
    result = assignment_service.assign("task-b", "agent-a", "template-1")

    assert result.task_id == "task-b"
    assert task_agent_registry.owner_task_id("agent-a") == "task-b"
    assert [
        agent.agent_id
        for agent in task_agent_registry.list_agents("task-b")
    ] == ["agent-a"]
