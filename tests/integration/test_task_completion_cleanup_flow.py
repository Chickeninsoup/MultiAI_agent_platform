from __future__ import annotations

from pathlib import Path

from src.agents.task_agent import TaskAgent
from src.agents.task_agent_cleanup_service import TaskAgentCleanupService
from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.agents.task_agent_team_state import TaskAgentTeamState
from src.planning.plan_execution_result import PlanExecutionResult
from src.planning.task_completion_service import TaskCompletionService
from src.repositories import RunRepository, TaskRepository
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_service import TaskService


def _create_task(tmp_path: Path, task_id: str) -> TaskRepository:
    """Bootstraps a real, on-disk Task via TaskService, mirroring
    production - this test exercises real TaskRepository persistence,
    not a fake."""

    task_repository = TaskRepository(tmp_path)
    run_repository = RunRepository(tmp_path)
    task_service = TaskService(
        task_repository=task_repository, run_repository=run_repository
    )
    task_service.create_task_and_run(
        task_id=task_id,
        title="Build a feature",
        description="Implement the requested feature",
        agent_id="agent-a",
        input_text="implement the feature",
        created_by="user-1",
    )

    return task_repository


def _successful_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="coding", status=StepStatus.SUCCESS, output="done"
            )
        ]
    )


def _failed_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="coding", status=StepStatus.FAILED, error="boom"
            )
        ]
    )


def test_successful_execution_completes_and_cleans_up_the_task(
    tmp_path: Path,
) -> None:
    task_id = "task-a"
    task_repository = _create_task(tmp_path, task_id)
    registry = TaskAgentRegistry()
    registry.assign_agent(
        TaskAgent(
            agent_id="agent-a", task_id=task_id, template_id="coder"
        )
    )
    lifecycle = TaskAgentTeamLifecycle(registry)
    lifecycle.lock(task_id)

    completion_service = TaskCompletionService(task_repository)
    cleanup_service = TaskAgentCleanupService(
        task_repository, registry, lifecycle
    )

    completed = completion_service.complete_if_successful(
        task_id, _successful_result()
    )
    if completed:
        cleanup_service.cleanup(task_id)

    assert completed is True
    assert registry.list_agents(task_id) == []
    assert registry.owner_task_id("agent-a") is None
    assert lifecycle.state(task_id) is TaskAgentTeamState.RELEASED
    task = task_repository.load(task_id)
    assert task.status == "completed"


def test_failed_execution_leaves_the_team_locked_and_agents_intact(
    tmp_path: Path,
) -> None:
    task_id = "task-a"
    task_repository = _create_task(tmp_path, task_id)
    registry = TaskAgentRegistry()
    agent_a = TaskAgent(
        agent_id="agent-a", task_id=task_id, template_id="coder"
    )
    registry.assign_agent(agent_a)
    lifecycle = TaskAgentTeamLifecycle(registry)
    lifecycle.lock(task_id)

    completion_service = TaskCompletionService(task_repository)
    cleanup_service = TaskAgentCleanupService(
        task_repository, registry, lifecycle
    )

    completed = completion_service.complete_if_successful(
        task_id, _failed_result()
    )
    if completed:
        cleanup_service.cleanup(task_id)

    assert completed is False
    task = task_repository.load(task_id)
    assert task.status == "in_progress"
    assert registry.list_agents(task_id) == [agent_a]
    assert registry.owner_task_id("agent-a") == task_id
    assert lifecycle.state(task_id) is TaskAgentTeamState.LOCKED
