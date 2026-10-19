from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_result import ToolResult
from src.llm.types import LLMMessage
from src.run_continuation_checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    RunContinuationCheckpoint,
)
from src.run_continuation_checkpoint_errors import (
    MismatchedCheckpointError,
)
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)


def _checkpoint(
    task_id: str = "task-1", run_id: str = "run-007"
) -> RunContinuationCheckpoint:
    return RunContinuationCheckpoint(
        schema_version=CHECKPOINT_SCHEMA_VERSION,
        task_id=task_id,
        run_id=run_id,
        approval_id="approval-1",
        messages=(LLMMessage(role="user", content="do the task"),),
        pending_round_tool_calls=(
            ToolCall(id="toolu_a", name="write_file", input={"a": 1}),
        ),
        pending_tool_call_index=0,
        pending_tool_call_id="toolu_a",
        completed_tool_results=(),
        llm_rounds=1,
        tool_rounds=1,
        cumulative_tool_calls=1,
        total_input_tokens=10,
        total_output_tokens=5,
        max_tool_rounds=8,
        max_total_tokens=100_000,
        created_at="2026-01-01T00:00:00Z",
    )


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    repository = RunContinuationCheckpointRepository(tmp_path)
    checkpoint = _checkpoint()

    repository.save(checkpoint)
    loaded = repository.load("task-1", "run-007")

    assert loaded == checkpoint


def test_load_missing_checkpoint_raises(tmp_path: Path) -> None:
    repository = RunContinuationCheckpointRepository(tmp_path)

    with pytest.raises(FileNotFoundError):
        repository.load("task-1", "run-unknown")


def test_runs_do_not_overwrite_each_other(tmp_path: Path) -> None:
    repository = RunContinuationCheckpointRepository(tmp_path)
    checkpoint_a = _checkpoint(run_id="run-a")
    checkpoint_b = _checkpoint(run_id="run-b")

    repository.save(checkpoint_a)
    repository.save(checkpoint_b)

    assert repository.load("task-1", "run-a") == checkpoint_a
    assert repository.load("task-1", "run-b") == checkpoint_b


def test_tasks_do_not_overwrite_each_other(tmp_path: Path) -> None:
    repository = RunContinuationCheckpointRepository(tmp_path)
    checkpoint_a = _checkpoint(task_id="task-a")
    checkpoint_b = _checkpoint(task_id="task-b")

    repository.save(checkpoint_a)
    repository.save(checkpoint_b)

    assert repository.load("task-a", "run-007") == checkpoint_a
    assert repository.load("task-b", "run-007") == checkpoint_b


def test_repeated_identical_save_is_idempotent(tmp_path: Path) -> None:
    repository = RunContinuationCheckpointRepository(tmp_path)
    checkpoint = _checkpoint()

    repository.save(checkpoint)
    repository.save(checkpoint)

    assert repository.load("task-1", "run-007") == checkpoint


def test_load_rejects_a_checkpoint_placed_at_the_wrong_location(
    tmp_path: Path,
) -> None:
    repository = RunContinuationCheckpointRepository(tmp_path)
    # A checkpoint whose own identity doesn't match where it's being
    # read from - e.g. a manually copied/moved file.
    wrong_checkpoint = _checkpoint(task_id="task-1", run_id="run-XXX")
    repository.save(wrong_checkpoint)

    # Manually place a run-XXX checkpoint's content at run-007's path.
    correct_path = repository.get_checkpoint_file("task-1", "run-007")
    correct_path.parent.mkdir(parents=True, exist_ok=True)
    correct_path.write_text(
        repository.get_checkpoint_file(
            "task-1", "run-XXX"
        ).read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(MismatchedCheckpointError):
        repository.load("task-1", "run-007")


def test_delete_removes_the_checkpoint(tmp_path: Path) -> None:
    repository = RunContinuationCheckpointRepository(tmp_path)
    repository.save(_checkpoint())

    repository.delete("task-1", "run-007")

    with pytest.raises(FileNotFoundError):
        repository.load("task-1", "run-007")


def test_delete_is_idempotent_for_a_missing_checkpoint(
    tmp_path: Path,
) -> None:
    repository = RunContinuationCheckpointRepository(tmp_path)

    repository.delete("task-1", "run-unknown")


def test_checkpoint_file_lives_under_the_runs_directory(
    tmp_path: Path,
) -> None:
    repository = RunContinuationCheckpointRepository(tmp_path)

    file_path = repository.get_checkpoint_file("task-1", "run-007")

    assert file_path == (
        tmp_path / "task-1" / "runs" / "run-007" / "checkpoint.json"
    )


def test_corrupt_checkpoint_json_fails_explicitly(
    tmp_path: Path,
) -> None:
    repository = RunContinuationCheckpointRepository(tmp_path)
    file_path = repository.get_checkpoint_file("task-1", "run-007")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("not json", encoding="utf-8")

    with pytest.raises(ValueError):
        repository.load("task-1", "run-007")


def test_missing_field_in_stored_checkpoint_fails_explicitly(
    tmp_path: Path,
) -> None:
    import json

    repository = RunContinuationCheckpointRepository(tmp_path)
    file_path = repository.get_checkpoint_file("task-1", "run-007")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    data = _checkpoint().to_dict()
    del data["messages"]
    file_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(KeyError):
        repository.load("task-1", "run-007")
