"""Policy-lock tests for docs/architecture/agent_lifecycle_policy.md.

These are not implementation tests - each one exists to catch a
regression of one of the four frozen invariants (5E-4E-2), using the
real production services wherever practical rather than re-deriving
the rules from scratch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent_registry import AgentRegistry
from src.agent_runtime_factory import AgentRuntimeFactory
from src.agents.agent_template import AgentTemplate
from src.agents.agent_template_repository import AgentTemplateRepository
from src.agents.task_agent_assignment_service import (
    TaskAgentAssignmentService,
)
from src.agents.task_agent_cleanup_service import TaskAgentCleanupService
from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.models import AgentDefinition
from src.planning.plan_execution_result import PlanExecutionResult
from src.planning.task_completion_service import TaskCompletionService
from src.repositories import AgentRepository, RunRepository, TaskRepository
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_service import TaskService


def _agent_dict(agent_id: str, template_id: str) -> dict[str, object]:
    return {
        "id": agent_id,
        "name": agent_id,
        "description": "An agent used for policy tests.",
        "owner": "owner-1",
        "status": "ready",
        "role": "engineer",
        "template_id": template_id,
        "default_model": "claude-model-placeholder",
        "credential_id": "cred-1",
        "system_prompt_path": "system-prompt.md",
        "tool_policy_path": "tool-policy.json",
        "default_workspace_id": "workspace-1",
        "capabilities": [],
        "limits": {
            "memory_mb": 512,
            "cpus": 1,
            "timeout_seconds": 60,
            "max_input_tokens": 50_000,
            "max_output_tokens": 10_000,
        },
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


def _write_agent(
    agents_dir: Path, agent_id: str, template_id: str
) -> None:
    agent_dir = agents_dir / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent.json").write_text(
        json.dumps(_agent_dict(agent_id, template_id)),
        encoding="utf-8",
    )


def _successful_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="step-1", status=StepStatus.SUCCESS, output="done"
            )
        ]
    )


def _create_task(task_service: TaskService, task_id: str) -> None:
    task_service.create_task_and_run(
        task_id=task_id,
        title="Build a feature",
        description="Implement the requested feature",
        agent_id="agent-a",
        input_text="implement the feature",
        created_by="user-1",
    )


def _complete_and_cleanup(
    task_id: str,
    lifecycle: TaskAgentTeamLifecycle,
    completion_service: TaskCompletionService,
    cleanup_service: TaskAgentCleanupService,
) -> None:
    lifecycle.lock(task_id)
    completed = completion_service.complete_if_successful(
        task_id, _successful_result()
    )
    assert completed is True
    assert cleanup_service.cleanup(task_id) is True


def test_agent_definition_requires_template_id() -> None:
    """Invariant 2's precondition: there is no orphan AgentDefinition."""

    data = _agent_dict("agent-a", "backend-template")
    del data["template_id"]

    with pytest.raises(ValueError):
        AgentDefinition.from_dict(data)


def test_agent_definition_survives_task_completion_and_cleanup(
    tmp_path: Path,
) -> None:
    """AgentDefinition/AgentRegistry are untouched by
    TaskAgentCleanupService - only TaskAgent membership is removed."""

    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-a", "backend-template")
    agent_registry = AgentRegistry(AgentRepository(agents_dir))

    task_repository = TaskRepository(tmp_path)
    run_repository = RunRepository(tmp_path)
    task_service = TaskService(
        task_repository=task_repository, run_repository=run_repository
    )

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
    assignment_service.assign("task-a", "agent-a", "backend-template")

    _complete_and_cleanup(
        "task-a", team_lifecycle, completion_service, cleanup_service
    )

    assert task_agent_registry.owner_task_id("agent-a") is None
    assert agent_registry.get_agent("agent-a").id == "agent-a"
    assert (
        agent_registry.get_agent("agent-a").template_id
        == "backend-template"
    )


def test_template_survives_multiple_task_assignments(
    tmp_path: Path,
) -> None:
    """AgentTemplate is a user asset - it outlives every Task it has
    ever backed, and the same AgentDefinition can be reassigned to a
    new Task under the same template without recreation."""

    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-a", "backend-template")
    agent_registry = AgentRegistry(AgentRepository(agents_dir))

    templates = AgentTemplateRepository()
    templates.save(
        AgentTemplate(
            template_id="backend-template", name="Backend Developer"
        )
    )

    task_repository = TaskRepository(tmp_path)
    run_repository = RunRepository(tmp_path)
    task_service = TaskService(
        task_repository=task_repository, run_repository=run_repository
    )

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

    assignment_service.assign("task-a", "agent-a", "backend-template")
    _complete_and_cleanup(
        "task-a", team_lifecycle, completion_service, cleanup_service
    )

    result = assignment_service.assign(
        "task-b", "agent-a", "backend-template"
    )

    assert result.task_id == "task-b"
    assert task_agent_registry.owner_task_id("agent-a") == "task-b"
    assert templates.get("backend-template") is not None


def test_runtime_handlers_do_not_persist_after_cleanup(
    tmp_path: Path,
) -> None:
    """AgentRuntimeFactory.create_handlers() only reflects what
    TaskAgentRegistry currently reports for a Task - it must not cache
    or resurrect handlers for a Task whose team has been released."""

    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-a", "backend-template")
    agent_registry = AgentRegistry(AgentRepository(agents_dir))

    task_repository = TaskRepository(tmp_path)
    run_repository = RunRepository(tmp_path)
    task_service = TaskService(
        task_repository=task_repository, run_repository=run_repository
    )

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

    # run_service/task_service below are never invoked - the factory
    # only reads TaskAgentRegistry to decide which handlers to build.
    runtime_factory = AgentRuntimeFactory(
        agent_registry,
        task_agent_registry,
        task_service=object(),
        run_service=object(),
    )

    _create_task(task_service, "task-a")
    assignment_service.assign("task-a", "agent-a", "backend-template")

    handlers_before = runtime_factory.create_handlers("task-a")
    assert len(handlers_before) == 1

    _complete_and_cleanup(
        "task-a", team_lifecycle, completion_service, cleanup_service
    )

    handlers_after = runtime_factory.create_handlers("task-a")
    assert handlers_after == []
