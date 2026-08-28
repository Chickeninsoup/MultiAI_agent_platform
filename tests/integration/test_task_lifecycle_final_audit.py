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


def _successful_execution_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="step-1",
                status=StepStatus.SUCCESS,
                output="done",
            )
        ]
    )


def _failed_execution_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="step-1",
                status=StepStatus.FAILED,
                error="execution failed",
            )
        ]
    )


def _skipped_execution_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="step-1",
                status=StepStatus.SKIPPED,
                error="dependency failed",
            )
        ]
    )


def _create_task(task_service: TaskService, task_id: str) -> None:
    """Same real TaskService bootstrap already used in
    test_task_completion_flow.py / test_task_completion_cleanup_flow.py."""

    task_service.create_task_and_run(
        task_id=task_id,
        title="Build a feature",
        description="Implement the requested feature",
        agent_id="agent-a",
        input_text="implement the feature",
        created_by="user-1",
    )


def _assign_task_agent(
    registry: TaskAgentRegistry, task_id: str, agent_id: str
) -> TaskAgent:
    task_agent = TaskAgent(
        agent_id=agent_id,
        task_id=task_id,
        template_id=f"template-{agent_id}",
    )

    registry.assign_agent(task_agent)

    return task_agent


def _build_services(tmp_path: Path):
    task_repository = TaskRepository(tmp_path)
    run_repository = RunRepository(tmp_path)
    task_service = TaskService(
        task_repository=task_repository, run_repository=run_repository
    )

    task_agent_registry = TaskAgentRegistry()
    team_lifecycle = TaskAgentTeamLifecycle(task_agent_registry)
    completion_service = TaskCompletionService(task_repository)
    cleanup_service = TaskAgentCleanupService(
        task_repository, task_agent_registry, team_lifecycle
    )

    return (
        task_repository,
        task_service,
        task_agent_registry,
        team_lifecycle,
        completion_service,
        cleanup_service,
    )


def test_successful_execution_completes_task_and_releases_team(
    tmp_path: Path,
) -> None:
    (
        task_repository,
        task_service,
        registry,
        lifecycle,
        completion_service,
        cleanup_service,
    ) = _build_services(tmp_path)

    task_id = "task-a"
    agent_id = "agent-a"

    _create_task(task_service, task_id)
    _assign_task_agent(registry, task_id, agent_id)
    lifecycle.lock(task_id)

    completed = completion_service.complete_if_successful(
        task_id, _successful_execution_result()
    )

    assert completed is True

    if completed:
        cleaned = cleanup_service.cleanup(task_id)
        assert cleaned is True

    task = task_repository.load(task_id)
    assert task.status == "completed"
    assert task.completed_at is not None

    assert registry.list_agents(task_id) == []
    assert registry.owner_task_id(agent_id) is None
    assert lifecycle.state(task_id) is TaskAgentTeamState.RELEASED


def test_failed_execution_preserves_task_team_and_agents(
    tmp_path: Path,
) -> None:
    (
        task_repository,
        task_service,
        registry,
        lifecycle,
        completion_service,
        cleanup_service,
    ) = _build_services(tmp_path)

    task_id = "task-a"
    agent_id = "agent-a"

    _create_task(task_service, task_id)
    task_agent = _assign_task_agent(registry, task_id, agent_id)
    lifecycle.lock(task_id)

    completed = completion_service.complete_if_successful(
        task_id, _failed_execution_result()
    )

    assert completed is False

    if completed:
        cleanup_service.cleanup(task_id)

    task = task_repository.load(task_id)
    assert task.status == "in_progress"
    assert task.completed_at is None

    assert registry.list_agents(task_id) == [task_agent]
    assert registry.owner_task_id(agent_id) == task_id
    assert lifecycle.state(task_id) is TaskAgentTeamState.LOCKED


def test_skipped_execution_does_not_trigger_terminal_cleanup(
    tmp_path: Path,
) -> None:
    (
        task_repository,
        task_service,
        registry,
        lifecycle,
        completion_service,
        cleanup_service,
    ) = _build_services(tmp_path)

    task_id = "task-a"
    agent_id = "agent-a"

    _create_task(task_service, task_id)
    task_agent = _assign_task_agent(registry, task_id, agent_id)
    lifecycle.lock(task_id)

    completed = completion_service.complete_if_successful(
        task_id, _skipped_execution_result()
    )

    assert completed is False

    if completed:
        cleanup_service.cleanup(task_id)

    task = task_repository.load(task_id)
    assert task.status == "in_progress"
    assert task.completed_at is None

    assert registry.list_agents(task_id) == [task_agent]
    assert registry.owner_task_id(agent_id) == task_id
    assert lifecycle.state(task_id) is TaskAgentTeamState.LOCKED


def test_cleanup_of_completed_task_is_isolated_from_other_task(
    tmp_path: Path,
) -> None:
    (
        task_repository,
        task_service,
        registry,
        lifecycle,
        completion_service,
        cleanup_service,
    ) = _build_services(tmp_path)

    task_a = "task-a"
    task_b = "task-b"
    agent_a = "agent-a"
    agent_b = "agent-b"

    _create_task(task_service, task_a)
    _create_task(task_service, task_b)

    _assign_task_agent(registry, task_a, agent_a)
    task_agent_b = _assign_task_agent(registry, task_b, agent_b)

    lifecycle.lock(task_a)
    lifecycle.lock(task_b)

    completed = completion_service.complete_if_successful(
        task_a, _successful_execution_result()
    )

    assert completed is True

    cleanup_service.cleanup(task_a)

    loaded_a = task_repository.load(task_a)
    loaded_b = task_repository.load(task_b)

    assert loaded_a.status == "completed"
    assert loaded_b.status == "in_progress"

    assert registry.list_agents(task_a) == []
    assert registry.list_agents(task_b) == [task_agent_b]

    assert registry.owner_task_id(agent_a) is None
    assert registry.owner_task_id(agent_b) == task_b

    assert lifecycle.state(task_a) is TaskAgentTeamState.RELEASED
    assert lifecycle.state(task_b) is TaskAgentTeamState.LOCKED


def test_terminal_cleanup_is_idempotent(tmp_path: Path) -> None:
    (
        _task_repository,
        task_service,
        registry,
        lifecycle,
        completion_service,
        cleanup_service,
    ) = _build_services(tmp_path)

    task_id = "task-a"
    agent_id = "agent-a"

    _create_task(task_service, task_id)
    _assign_task_agent(registry, task_id, agent_id)
    lifecycle.lock(task_id)

    completed = completion_service.complete_if_successful(
        task_id, _successful_execution_result()
    )

    assert completed is True
    assert cleanup_service.cleanup(task_id) is True
    assert cleanup_service.cleanup(task_id) is True

    assert registry.list_agents(task_id) == []
    assert registry.owner_task_id(agent_id) is None
    assert lifecycle.state(task_id) is TaskAgentTeamState.RELEASED
