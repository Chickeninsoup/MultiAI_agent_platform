from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models import RunExecutionContext, RunExecutionResult
from src.repositories import AgentRepository, RunRepository, TaskRepository
from src.run_service import RunService
from src.task_service import TaskAlreadyExistsError, TaskService


def _build_service(tmp_path: Path) -> tuple[
    TaskService, TaskRepository, RunRepository
]:
    tasks_dir = tmp_path / "tasks"
    task_repository = TaskRepository(tasks_dir)
    run_repository = RunRepository(tasks_dir)

    service = TaskService(
        task_repository=task_repository,
        run_repository=run_repository,
    )

    return service, task_repository, run_repository


def test_create_task_and_run_persists_task_and_run(
    tmp_path: Path,
) -> None:
    service, task_repository, run_repository = _build_service(
        tmp_path
    )

    task, run = service.create_task_and_run(
        task_id="task-x",
        title="Fix the bug",
        description="Fix the authentication bug in auth.py.",
        agent_id="agent-coder",
        input_text="Fix the authentication bug in auth.py.",
        created_by="agent:manager",
    )

    assert task.id == "task-x"
    assert task.status == "in_progress"
    assert task.assigned_agents == ["agent-coder"]
    assert task.current_run_id == "run-001"
    assert task.run_count == 1

    assert run.id == "run-001"
    assert run.task_id == "task-x"
    assert run.agent_id == "agent-coder"
    assert run.status == "in_progress"

    saved_task = task_repository.load("task-x")
    assert saved_task == task

    saved_run = run_repository.load("task-x", "run-001")
    assert saved_run == run

    assert (
        run_repository.read_input("task-x", "run-001")
        == "Fix the authentication bug in auth.py."
    )

    background = task_repository.get_background_file("task-x")
    assert background.exists()
    assert "Fix the authentication bug in auth.py." in (
        background.read_text(encoding="utf-8")
    )


def test_create_task_and_run_applies_defaults(
    tmp_path: Path,
) -> None:
    service, _, _ = _build_service(tmp_path)

    task, _ = service.create_task_and_run(
        task_id="task-x",
        title="Title",
        description="Description",
        agent_id="agent-coder",
        input_text="Do the thing.",
        created_by="agent:manager",
    )

    assert task.workspace_id == "workspace-main"
    assert task.priority == "normal"
    assert task.completion_criteria == []
    assert task.tags == []


def test_create_task_and_run_accepts_overrides(
    tmp_path: Path,
) -> None:
    service, _, _ = _build_service(tmp_path)

    task, _ = service.create_task_and_run(
        task_id="task-x",
        title="Title",
        description="Description",
        agent_id="agent-coder",
        input_text="Do the thing.",
        created_by="agent:manager",
        workspace_id="workspace-other",
        priority="high",
        completion_criteria=["Tests pass"],
        tags=["multi-agent"],
    )

    assert task.workspace_id == "workspace-other"
    assert task.priority == "high"
    assert task.completion_criteria == ["Tests pass"]
    assert task.tags == ["multi-agent"]


def test_create_task_and_run_rejects_existing_task_id(
    tmp_path: Path,
) -> None:
    service, _, _ = _build_service(tmp_path)

    service.create_task_and_run(
        task_id="task-x",
        title="Title",
        description="Description",
        agent_id="agent-coder",
        input_text="Do the thing.",
        created_by="agent:manager",
    )

    with pytest.raises(TaskAlreadyExistsError):
        service.create_task_and_run(
            task_id="task-x",
            title="Different title",
            description="Different description",
            agent_id="agent-coder",
            input_text="Do a different thing.",
            created_by="agent:manager",
        )


class _FakeContextBuilder:
    def build(self, *, task, run, agent) -> RunExecutionContext:
        return RunExecutionContext(
            task=task,
            run=run,
            agent=agent,
            run_input="do the thing",
        )


class _FakeExecutor:
    def execute(self, context: RunExecutionContext) -> RunExecutionResult:
        return RunExecutionResult(
            output_markdown="# out",
            summary_markdown="# sum",
        )


def test_created_task_executes_through_real_run_service(
    tmp_path: Path,
) -> None:
    # Proves TaskService doesn't bypass the existing state machine:
    # a Task/Run it creates must be indistinguishable, from
    # RunService's point of view, from one that was hand-authored.
    service, task_repository, run_repository = _build_service(
        tmp_path
    )

    agents_dir = tmp_path / "agents"
    (agents_dir / "agent-coder").mkdir(parents=True)
    (agents_dir / "agent-coder" / "agent.json").write_text(
        json.dumps(
            {
                "id": "agent-coder",
                "name": "Coder",
                "description": "A test agent.",
                "owner": "owner-1",
                "status": "ready",
                "role": "coder",
                "template_id": "coder",
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
                    "max_input_tokens": 1000,
                    "max_output_tokens": 1000,
                },
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    service.create_task_and_run(
        task_id="task-x",
        title="Title",
        description="Description",
        agent_id="agent-coder",
        input_text="Do the thing.",
        created_by="agent:manager",
    )

    run_service = RunService(
        task_repository=task_repository,
        run_repository=run_repository,
        agent_repository=AgentRepository(agents_dir),
        context_builder=_FakeContextBuilder(),
        executor=_FakeExecutor(),
        project_root=tmp_path,
    )

    result = run_service.execute("task-x")

    assert result.status == "completed"

    saved_run = run_repository.load("task-x", "run-001")
    assert saved_run.status == "completed"
