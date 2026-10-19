from __future__ import annotations

import json
from pathlib import Path

from src.models import RunExecutionContext, RunExecutionResult
from src.repositories import AgentRepository, RunRepository, TaskRepository
from src.run_service import RunService, RunServiceResult


class FakeContextBuilder:
    def build(self, *, task, run, agent) -> RunExecutionContext:
        return RunExecutionContext(
            task=task,
            run=run,
            agent=agent,
            run_input="do the thing",
        )


class FakeExecutor:
    def __init__(self, outcome) -> None:
        self.outcome = outcome

    def execute(self, context: RunExecutionContext):
        if isinstance(self.outcome, Exception):
            raise self.outcome

        return self.outcome


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _setup_fixture(
    tasks_dir: Path, agents_dir: Path, agent_id: str = "agent-test"
) -> None:
    _write_json(
        agents_dir / agent_id / "agent.json",
        {
            "id": agent_id,
            "name": "Test Agent",
            "description": "An agent used for testing.",
            "owner": "owner-1",
            "status": "ready",
            "role": "engineer",
            "template_id": "engineer",
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
        },
    )

    _write_json(
        tasks_dir / "task-1" / "task.json",
        {
            "id": "task-1",
            "title": "Test task",
            "description": "A task used for testing.",
            "workspace_id": "workspace-1",
            "status": "in_progress",
            "priority": "normal",
            "created_by": "user-1",
            "assigned_agents": [agent_id],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": None,
            "abandoned_at": None,
            "current_run_id": "run-1",
            "run_count": 1,
            "completion_criteria": [],
            "tags": [],
        },
    )

    _write_json(
        tasks_dir / "task-1" / "runs" / "run-1" / "run.json",
        {
            "id": "run-1",
            "task_id": "task-1",
            "agent_id": agent_id,
            "status": "in_progress",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": None,
        },
    )


def _build_service(tmp_path: Path, outcome):
    tasks_dir = tmp_path / "tasks"
    agents_dir = tmp_path / "agents"
    _setup_fixture(tasks_dir, agents_dir)

    task_repository = TaskRepository(tasks_dir)
    run_repository = RunRepository(tasks_dir)
    agent_repository = AgentRepository(agents_dir)
    executor = FakeExecutor(outcome)

    service = RunService(
        task_repository=task_repository,
        run_repository=run_repository,
        agent_repository=agent_repository,
        context_builder=FakeContextBuilder(),
        executor=executor,
        project_root=tmp_path,
    )

    return service, task_repository, run_repository


def _waiting_result() -> RunExecutionResult:
    return RunExecutionResult(
        output_markdown="# out\n\nwaiting_for_approval: approval-1",
        summary_markdown="# sum\n\nStatus: waiting_for_approval",
        metadata={
            "llm_rounds": 1,
            "tool_rounds": 1,
            "tool_calls": 1,
            "total_input_tokens": 10,
            "total_output_tokens": 5,
            "waiting_for_approval": True,
            "approval_id": "approval-1",
            "tool_call_id": "toolu_1",
        },
    )


def test_run_service_result_reports_waiting_status(
    tmp_path: Path,
) -> None:
    service, _task_repository, _run_repository = _build_service(
        tmp_path, _waiting_result()
    )

    result = service.execute("task-1")

    assert isinstance(result, RunServiceResult)
    assert result.status == "waiting_for_approval"
    assert result.approval_id == "approval-1"


def test_persisted_run_status_becomes_waiting_for_approval(
    tmp_path: Path,
) -> None:
    service, _task_repository, run_repository = _build_service(
        tmp_path, _waiting_result()
    )

    service.execute("task-1")

    saved_run = run_repository.load("task-1", "run-1")
    assert saved_run.status == "waiting_for_approval"
    assert saved_run.metadata["approval_id"] == "approval-1"
    assert saved_run.metadata["tool_call_id"] == "toolu_1"


def test_waiting_run_is_not_terminal(tmp_path: Path) -> None:
    service, _task_repository, run_repository = _build_service(
        tmp_path, _waiting_result()
    )

    service.execute("task-1")

    saved_run = run_repository.load("task-1", "run-1")
    assert saved_run.is_completed() is False
    assert saved_run.completed_at is None


def test_waiting_run_is_not_in_resumable_statuses(
    tmp_path: Path,
) -> None:
    from src.run_service import RESUMABLE_STATUSES

    assert "waiting_for_approval" not in RESUMABLE_STATUSES


def test_output_and_summary_files_are_still_written(
    tmp_path: Path,
) -> None:
    service, _task_repository, _run_repository = _build_service(
        tmp_path, _waiting_result()
    )

    result = service.execute("task-1")

    assert "waiting_for_approval" in result.output_path.read_text(
        encoding="utf-8"
    )
    assert "waiting_for_approval" in result.summary_path.read_text(
        encoding="utf-8"
    )


def test_completed_result_still_has_no_approval_id(
    tmp_path: Path,
) -> None:
    completed_result = RunExecutionResult(
        output_markdown="# out",
        summary_markdown="# sum",
        metadata={
            "llm_rounds": 1,
            "tool_rounds": 0,
            "tool_calls": 0,
            "total_input_tokens": 5,
            "total_output_tokens": 5,
        },
    )
    service, _task_repository, _run_repository = _build_service(
        tmp_path, completed_result
    )

    result = service.execute("task-1")

    assert result.status == "completed"
    assert result.approval_id is None
