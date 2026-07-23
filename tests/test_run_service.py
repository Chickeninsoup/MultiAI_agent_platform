from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.llm_executor import LLMRunLimitError
from src.models import RunExecutionContext, RunExecutionResult
from src.repositories import AgentRepository, RunRepository, TaskRepository
from src.run_service import (
    RunExecutionFailedError,
    RunService,
    RunServiceResult,
)


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


def _setup_fixture(tasks_dir: Path, agents_dir: Path) -> None:
    _write_json(
        agents_dir / "agent-test" / "agent.json",
        {
            "id": "agent-test",
            "name": "Test Agent",
            "description": "An agent used for testing.",
            "owner": "owner-1",
            "status": "ready",
            "role": "engineer",
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
            "assigned_agents": ["agent-test"],
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
            "agent_id": "agent-test",
            "status": "in_progress",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": None,
        },
    )


def _build_service(
    tmp_path: Path,
    outcome,
):
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
    )

    return service, task_repository, run_repository, executor


def test_successful_run_returns_run_service_result(
    tmp_path: Path,
) -> None:
    result_from_executor = RunExecutionResult(
        output_markdown="# out",
        summary_markdown="# sum",
        metadata={
            "llm_rounds": 2,
            "tool_rounds": 1,
            "tool_calls": 1,
            "total_input_tokens": 50,
            "total_output_tokens": 20,
        },
    )

    service, task_repository, run_repository, _ = _build_service(
        tmp_path, result_from_executor
    )

    result = service.execute("task-1")

    assert isinstance(result, RunServiceResult)
    assert result.task_id == "task-1"
    assert result.run_id == "run-1"
    assert result.agent_id == "agent-test"
    assert result.status == "completed"
    assert result.llm_rounds == 2
    assert result.tool_rounds == 1
    assert result.tool_calls == 1
    assert result.total_input_tokens == 50
    assert result.total_output_tokens == 20

    assert result.output_path.read_text(encoding="utf-8") == "# out"
    assert result.summary_path.read_text(encoding="utf-8") == "# sum"

    saved_run = run_repository.load("task-1", "run-1")
    assert saved_run.status == "completed"
    assert saved_run.completed_at is not None

    saved_task = task_repository.load("task-1")
    assert saved_task.updated_at == saved_run.updated_at


def test_simulated_style_result_has_none_usage_fields(
    tmp_path: Path,
) -> None:
    result_from_executor = RunExecutionResult(
        output_markdown="# out",
        summary_markdown="# sum",
        metadata={"execution_mode": "simulated"},
    )

    service, _, _, _ = _build_service(tmp_path, result_from_executor)

    result = service.execute("task-1")

    assert result.llm_rounds is None
    assert result.tool_rounds is None
    assert result.tool_calls is None
    assert result.total_input_tokens is None
    assert result.total_output_tokens is None


def test_unclassified_failure_marks_run_failed_not_retryable(
    tmp_path: Path,
) -> None:
    original_error = RuntimeError("Something unexpected broke.")

    service, _, run_repository, _ = _build_service(
        tmp_path, original_error
    )

    with pytest.raises(RunExecutionFailedError) as excinfo:
        service.execute("task-1")

    error = excinfo.value
    assert error.task_id == "task-1"
    assert error.run_id == "run-1"
    assert error.agent_id == "agent-test"
    assert error.status == "failed"
    assert error.category == "INTERNAL_ERROR"
    assert error.retryable is False
    assert error.original_error is original_error
    assert error.events_path == run_repository.get_events_file(
        "task-1", "run-1"
    )

    # the run must NOT be silently marked completed on failure
    saved_run = run_repository.load("task-1", "run-1")
    assert saved_run.status == "failed"
    assert saved_run.completed_at is None
    assert saved_run.metadata["error_category"] == "INTERNAL_ERROR"
    assert saved_run.metadata["retryable"] is False


def test_limit_exceeded_failure_marks_run_interrupted_and_retryable(
    tmp_path: Path,
) -> None:
    original_error = LLMRunLimitError("Maximum tool rounds exceeded.")

    service, _, run_repository, _ = _build_service(
        tmp_path, original_error
    )

    with pytest.raises(RunExecutionFailedError) as excinfo:
        service.execute("task-1")

    error = excinfo.value
    assert error.status == "interrupted"
    assert error.category == "LIMIT_EXCEEDED"
    assert error.retryable is True

    saved_run = run_repository.load("task-1", "run-1")
    assert saved_run.status == "interrupted"
    assert saved_run.metadata["retryable"] is True


def test_execute_rejects_a_run_that_is_not_in_progress(
    tmp_path: Path,
) -> None:
    # First execution fails and moves run-1 to "failed" (INTERNAL_ERROR).
    service, _, _, _ = _build_service(tmp_path, RuntimeError("boom"))

    with pytest.raises(RunExecutionFailedError):
        service.execute("task-1")

    # Running the same task again must not silently retry in place.
    with pytest.raises(ValueError, match="use `resume"):
        service.execute("task-1")


def test_resume_marks_crashed_run_interrupted_and_creates_new_run(
    tmp_path: Path,
) -> None:
    result_from_executor = RunExecutionResult(
        output_markdown="# out",
        summary_markdown="# sum",
        metadata={
            "llm_rounds": 1,
            "tool_rounds": 0,
            "tool_calls": 0,
            "total_input_tokens": 10,
            "total_output_tokens": 5,
        },
    )

    service, task_repository, run_repository, executor = _build_service(
        tmp_path, result_from_executor
    )

    input_path = run_repository.get_input_file("task-1", "run-1")
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text("original instructions", encoding="utf-8")

    # run-1 is still "in_progress" with no live process behind it,
    # simulating a crash that never got to mark a terminal status.
    result = service.resume("run-1")

    old_run = run_repository.load("task-1", "run-1")
    assert old_run.status == "interrupted"

    assert result.run_id == "run-002"
    assert result.status == "completed"

    new_run = run_repository.load("task-1", "run-002")
    assert new_run.metadata["retry_of"] == "run-1"
    assert (
        run_repository.read_input("task-1", "run-002")
        == "original instructions"
    )

    updated_task = task_repository.load("task-1")
    assert updated_task.current_run_id == "run-002"
    assert updated_task.run_count == 2


def test_resume_rejects_completed_run(tmp_path: Path) -> None:
    service, task_repository, run_repository, _ = _build_service(
        tmp_path,
        RunExecutionResult(output_markdown="", summary_markdown=""),
    )

    service.execute("task-1")  # marks run-1 completed

    with pytest.raises(ValueError, match="cannot be resumed"):
        service.resume("run-1")


def test_resume_unknown_run_id_raises(tmp_path: Path) -> None:
    service, _, _, _ = _build_service(
        tmp_path,
        RunExecutionResult(output_markdown="", summary_markdown=""),
    )

    with pytest.raises(ValueError, match="No task owns run"):
        service.resume("run-does-not-exist")
