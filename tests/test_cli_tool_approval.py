from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import src.main as main
from src.approval_decision import ApprovalDecision
from src.approval_decision_errors import ApprovalRunNotFoundError
from src.approval_errors import ApprovalAlreadyResolvedError
from src.approval_request import ApprovalRequest, RiskLevel
from src.approval_request_repository import ApprovalRequestRepository
from src.approval_resolution_repository import (
    ApprovalResolutionRepository,
)
from src.approval_store import ApprovalStore
from src.domain.tools.tool_call import ToolCall
from src.llm.types import LLMMessage
from src.repositories import RunRepository, TaskRepository
from src.run_continuation_checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    RunContinuationCheckpoint,
)
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_task_and_run(
    tasks_dir: Path,
    *,
    task_id: str = "task-1",
    run_id: str = "run-007",
    run_status: str = "waiting_for_approval",
) -> None:
    _write_json(
        tasks_dir / task_id / "task.json",
        {
            "id": task_id,
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
            "current_run_id": run_id,
            "run_count": 1,
            "completion_criteria": [],
            "tags": [],
        },
    )

    _write_json(
        tasks_dir / task_id / "runs" / run_id / "run.json",
        {
            "id": run_id,
            "task_id": task_id,
            "agent_id": "agent-test",
            "status": run_status,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": None,
        },
    )


def _tool_call() -> ToolCall:
    return ToolCall(
        id="toolu_1",
        name="write_file",
        input={"path": "a.py", "content": "super-secret-token"},
    )


def _wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_status: str = "waiting_for_approval",
    task_id: str = "task-1",
    run_id: str = "run-007",
    approval_id: str = "approval-1",
    skip_checkpoint: bool = False,
) -> Path:
    tasks_dir = tmp_path / "tasks"
    _write_task_and_run(
        tasks_dir,
        task_id=task_id,
        run_id=run_id,
        run_status=run_status,
    )

    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    approval_store.create(
        ApprovalRequest(
            approval_id=approval_id,
            run_id=run_id,
            proposed_action=_tool_call(),
            reason="writes files outside the sandbox",
            risk_level=RiskLevel.MEDIUM,
            input_preview="write a.py",
        )
    )

    if not skip_checkpoint:
        calls = (_tool_call(),)
        RunContinuationCheckpointRepository(tasks_dir).save(
            RunContinuationCheckpoint(
                schema_version=CHECKPOINT_SCHEMA_VERSION,
                task_id=task_id,
                run_id=run_id,
                approval_id=approval_id,
                messages=(
                    LLMMessage(role="user", content="do the task"),
                ),
                pending_round_tool_calls=calls,
                pending_tool_call_index=0,
                pending_tool_call_id=calls[0].id,
                completed_tool_results=(),
                llm_rounds=1,
                tool_rounds=1,
                cumulative_tool_calls=len(calls),
                total_input_tokens=10,
                total_output_tokens=5,
                max_tool_rounds=8,
                max_total_tokens=100_000,
                created_at="2026-01-01T00:00:00Z",
            )
        )

    monkeypatch.setattr(main, "TASKS_DIR", tasks_dir)
    monkeypatch.setattr(main, "task_repository", TaskRepository(tasks_dir))
    monkeypatch.setattr(main, "run_repository", RunRepository(tasks_dir))

    return tasks_dir


def _events(tasks_dir: Path, task_id: str, run_id: str) -> list[dict]:
    events_path = tasks_dir / task_id / "runs" / run_id / "events.jsonl"
    if not events_path.exists():
        return []
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --- parsing / help -------------------------------------------------------


def test_all_four_commands_appear_in_help() -> None:
    parser = main.build_parser()
    subcommands = parser._subparsers._group_actions[0].choices

    for name in (
        "approve-tool-call",
        "reject-tool-call",
        "modify-tool-call",
        "cancel-tool-call",
    ):
        assert name in subcommands


def test_no_collision_with_plan_level_commands() -> None:
    parser = main.build_parser()
    subcommands = parser._subparsers._group_actions[0].choices

    assert "approve-plan" in subcommands
    assert "reject-plan" in subcommands
    assert "approve-plan" != "approve-tool-call"
    assert "reject-plan" != "reject-tool-call"


def test_approval_id_required() -> None:
    parser = main.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["approve-tool-call"])


def test_explanation_optional() -> None:
    parser = main.build_parser()

    args = parser.parse_args(["approve-tool-call", "approval-1"])

    assert args.explanation is None


def test_modify_requires_input_file() -> None:
    parser = main.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["modify-tool-call", "approval-1"])


def test_non_modify_commands_reject_modified_input_option() -> None:
    parser = main.build_parser()

    for name in ("approve-tool-call", "reject-tool-call", "cancel-tool-call"):
        with pytest.raises(SystemExit):
            parser.parse_args(
                [name, "approval-1", "--modified-input-file", "x.json"]
            )


# --- successful commands ---------------------------------------------------


def test_approve_records_correct_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)

    main.approve_tool_call("approval-1")

    resolution = ApprovalResolutionRepository(tasks_dir).get("approval-1")
    assert resolution is not None
    assert resolution.decision is ApprovalDecision.APPROVE
    assert resolution.modified_input is None

    run = RunRepository(tasks_dir).load("task-1", "run-007")
    assert run.status == "waiting_for_approval"

    # Checkpoint remains unchanged.
    checkpoint = RunContinuationCheckpointRepository(tasks_dir).load(
        "task-1", "run-007"
    )
    assert checkpoint.pending_tool_call_id == "toolu_1"

    output = capsys.readouterr().out
    assert "Approval ID: approval-1" in output
    assert "Decision:    approve" in output
    assert "Run status:  waiting_for_approval" in output
    assert "Resumed:     false" in output
    assert "Executed:    false" in output
    assert "super-secret-token" not in output
    assert "a.py" not in output


def test_reject_records_correct_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)

    main.reject_tool_call("approval-1", explanation="not safe")

    resolution = ApprovalResolutionRepository(tasks_dir).get("approval-1")
    assert resolution.decision is ApprovalDecision.REJECT
    assert resolution.explanation == "not safe"


def test_modify_records_exact_parsed_dict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)
    input_file = tmp_path / "modified.json"
    input_file.write_text(
        json.dumps({"path": "sandbox/safe.py"}), encoding="utf-8"
    )

    main.modify_tool_call("approval-1", str(input_file))

    resolution = ApprovalResolutionRepository(tasks_dir).get("approval-1")
    assert resolution.decision is ApprovalDecision.MODIFY
    assert resolution.modified_input == {"path": "sandbox/safe.py"}


def test_cancel_records_correct_decision_and_does_not_cancel_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)

    main.cancel_tool_call("approval-1")

    resolution = ApprovalResolutionRepository(tasks_dir).get("approval-1")
    assert resolution.decision is ApprovalDecision.CANCEL

    run = RunRepository(tasks_dir).load("task-1", "run-007")
    assert run.status == "waiting_for_approval"

    output = capsys.readouterr().out
    assert "has not been cancelled yet" in output


# --- JSON handling -----------------------------------------------------


def test_modify_accepts_valid_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(tmp_path, monkeypatch)
    input_file = tmp_path / "modified.json"
    input_file.write_text(json.dumps({"a": 1}), encoding="utf-8")

    main.modify_tool_call("approval-1", str(input_file))


def test_modify_rejects_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(tmp_path, monkeypatch)
    input_file = tmp_path / "modified.json"
    input_file.write_text("{not valid", encoding="utf-8")

    with pytest.raises(ValueError):
        main.modify_tool_call("approval-1", str(input_file))


@pytest.mark.parametrize("payload", ["[1, 2]", '"a string"', "null", "42"])
def test_modify_rejects_non_object_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    _wire(tmp_path, monkeypatch)
    input_file = tmp_path / "modified.json"
    input_file.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError):
        main.modify_tool_call("approval-1", str(input_file))


def test_modify_rejects_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(tmp_path, monkeypatch)

    with pytest.raises(ValueError):
        main.modify_tool_call("approval-1", str(tmp_path / "missing.json"))


def test_modify_error_does_not_echo_secret_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(tmp_path, monkeypatch)
    input_file = tmp_path / "modified.json"
    input_file.write_text("{super-secret-not-json", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        main.modify_tool_call("approval-1", str(input_file))

    assert "super-secret-not-json" not in str(excinfo.value)


# --- idempotency / conflicts --------------------------------------------


def test_identical_repeat_succeeds_and_preserves_resolved_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)

    main.approve_tool_call("approval-1")
    first = ApprovalResolutionRepository(tasks_dir).get("approval-1")

    main.approve_tool_call("approval-1")
    second = ApprovalResolutionRepository(tasks_dir).get("approval-1")

    assert first.resolved_at == second.resolved_at

    events = [
        event
        for event in _events(tasks_dir, "task-1", "run-007")
        if event["type"] == "approval_resolved"
    ]
    assert len(events) == 1


def test_conflicting_second_decision_fails_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)

    main.approve_tool_call("approval-1")

    with pytest.raises(ApprovalAlreadyResolvedError):
        main.reject_tool_call("approval-1")

    resolution = ApprovalResolutionRepository(tasks_dir).get("approval-1")
    assert resolution.decision is ApprovalDecision.APPROVE


def test_conflicting_modify_input_fails_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)
    first_file = tmp_path / "first.json"
    first_file.write_text(json.dumps({"a": 1}), encoding="utf-8")
    second_file = tmp_path / "second.json"
    second_file.write_text(json.dumps({"a": 2}), encoding="utf-8")

    main.modify_tool_call("approval-1", str(first_file))

    with pytest.raises(ApprovalAlreadyResolvedError):
        main.modify_tool_call("approval-1", str(second_file))

    resolution = ApprovalResolutionRepository(tasks_dir).get("approval-1")
    assert resolution.modified_input == {"a": 1}


# --- audit routing -------------------------------------------------------


def test_event_written_to_correct_run_events_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)

    main.approve_tool_call("approval-1", explanation="looks fine")

    events = _events(tasks_dir, "task-1", "run-007")
    resolved = [e for e in events if e["type"] == "approval_resolved"]

    assert len(resolved) == 1
    event = resolved[0]
    assert event["approval_id"] == "approval-1"
    assert event["run_id"] == "run-007"
    assert event["decision"] == "approve"
    assert "super-secret-token" not in json.dumps(event)
    assert "modified_input" not in event
    assert "input" not in event


def test_event_not_written_to_a_different_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)
    # A second, unrelated run must never receive this event.
    _write_task_and_run(
        tasks_dir, task_id="task-2", run_id="run-099", run_status="completed"
    )

    main.approve_tool_call("approval-1")

    assert _events(tasks_dir, "task-2", "run-099") == []


def test_unknown_run_for_approval_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    approval_store.create(
        ApprovalRequest(
            approval_id="approval-orphan",
            run_id="run-does-not-exist",
            proposed_action=_tool_call(),
            reason="test",
            risk_level=RiskLevel.LOW,
            input_preview="preview",
        )
    )

    monkeypatch.setattr(main, "TASKS_DIR", tasks_dir)
    monkeypatch.setattr(main, "task_repository", TaskRepository(tasks_dir))
    monkeypatch.setattr(main, "run_repository", RunRepository(tasks_dir))

    with pytest.raises(ApprovalRunNotFoundError):
        main.approve_tool_call("approval-orphan")

    assert (
        ApprovalResolutionRepository(tasks_dir).get("approval-orphan")
        is None
    )
    # A still-PENDING request whose ownership can't be resolved must
    # fail before any events.jsonl is ever created, anywhere.
    assert list(tasks_dir.rglob("events.jsonl")) == []


def test_existing_events_are_preserved_when_new_decision_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)
    events_path = (
        tasks_dir / "task-1" / "runs" / "run-007" / "events.jsonl"
    )
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(
        json.dumps(
            {"type": "approval_requested", "approval_id": "approval-1"}
        )
        + "\n",
        encoding="utf-8",
    )

    main.approve_tool_call("approval-1")

    lines = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 2
    assert lines[0]["type"] == "approval_requested"
    assert lines[1]["type"] == "approval_resolved"


# --- durable idempotency through the CLI (5E-5D-5B-1) ---------------------
#
# ApprovalDecisionService.resolve() already answers a RESOLVED request
# entirely off ApprovalStore's own projection (5E-5D-5A-1) - it never
# touches Task, Run, or the continuation checkpoint for a replay. These
# tests prove the CLI composition preserves that: an already-recorded
# decision can still be replayed (idempotently, or rejected as a
# conflict) even after the Run/Task that originated it is gone.


def _make_run_and_task_undiscoverable(tasks_dir: Path, task_id: str) -> None:
    """Removes the task's entire directory (task.json, runs/<run_id>/
    run.json, events.jsonl, checkpoint.json) while leaving the
    approval record - tasks_dir/approvals/<approval_id>/... lives in a
    completely separate subtree - untouched."""

    shutil.rmtree(tasks_dir / task_id)


def test_identical_retry_succeeds_after_run_and_task_become_undiscoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)

    main.approve_tool_call("approval-1")
    first = ApprovalResolutionRepository(tasks_dir).get("approval-1")
    capsys.readouterr()

    _make_run_and_task_undiscoverable(tasks_dir, "task-1")

    main.approve_tool_call("approval-1")
    second = ApprovalResolutionRepository(tasks_dir).get("approval-1")

    assert first == second
    assert first.resolved_at == second.resolved_at

    output = capsys.readouterr().out
    assert "Approval ID: approval-1" in output
    assert "Decision:    approve" in output
    assert "Run status:  not checked" in output
    assert "waiting_for_approval" not in output


def test_conflicting_retry_after_run_and_task_become_undiscoverable_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)

    main.approve_tool_call("approval-1")
    _make_run_and_task_undiscoverable(tasks_dir, "task-1")

    with pytest.raises(ApprovalAlreadyResolvedError):
        main.reject_tool_call("approval-1")

    resolution = ApprovalResolutionRepository(tasks_dir).get("approval-1")
    assert resolution.decision is ApprovalDecision.APPROVE


def test_identical_modify_retry_succeeds_after_run_and_task_become_undiscoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)
    input_file = tmp_path / "modified.json"
    input_file.write_text(
        json.dumps({"path": "sandbox/safe.py"}), encoding="utf-8"
    )

    main.modify_tool_call("approval-1", str(input_file))
    first = ApprovalResolutionRepository(tasks_dir).get("approval-1")

    _make_run_and_task_undiscoverable(tasks_dir, "task-1")

    # Same file, same parsed content - an identical retry.
    main.modify_tool_call("approval-1", str(input_file))
    second = ApprovalResolutionRepository(tasks_dir).get("approval-1")

    assert first.resolved_at == second.resolved_at
    assert second.modified_input == {"path": "sandbox/safe.py"}


def test_resolved_retry_does_not_access_task_run_or_checkpoint_lookups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)

    main.approve_tool_call("approval-1")
    first = ApprovalResolutionRepository(tasks_dir).get("approval-1")

    def _poisoned(*args, **kwargs):
        raise AssertionError(
            "a RESOLVED-request replay must not call this collaborator"
        )

    # Poison every Task/Run/checkpoint collaborator a fresh PENDING
    # resolution would need - if the replay path below touches any of
    # these, the poisoned call raises and fails the test.
    monkeypatch.setattr(main.task_repository, "list_all", _poisoned)
    monkeypatch.setattr(main.run_repository, "list_run_ids", _poisoned)
    monkeypatch.setattr(main.run_repository, "get_events_file", _poisoned)
    monkeypatch.setattr(main.run_repository, "load", _poisoned)
    monkeypatch.setattr(
        RunContinuationCheckpointRepository, "load", _poisoned
    )

    main.approve_tool_call("approval-1")
    second = ApprovalResolutionRepository(tasks_dir).get("approval-1")

    assert first.resolved_at == second.resolved_at


def test_resolved_retry_creates_no_event_and_leaves_resolution_file_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)

    main.approve_tool_call("approval-1")

    events_path = (
        tasks_dir / "task-1" / "runs" / "run-007" / "events.jsonl"
    )
    events_before = events_path.read_text(encoding="utf-8")

    resolution_path = (
        tasks_dir / "approvals" / "approval-1" / "resolution.json"
    )
    resolution_bytes_before = resolution_path.read_bytes()

    main.approve_tool_call("approval-1")

    assert events_path.read_text(encoding="utf-8") == events_before
    assert resolution_path.read_bytes() == resolution_bytes_before


# --- error behavior --------------------------------------------------------


def test_unknown_approval_id_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(tmp_path, monkeypatch)

    with pytest.raises(ValueError):
        main.approve_tool_call("does-not-exist")


def test_run_not_waiting_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(tmp_path, monkeypatch, run_status="in_progress")

    with pytest.raises(ValueError):
        main.approve_tool_call("approval-1")


def test_orphan_checkpoint_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(tmp_path, monkeypatch, skip_checkpoint=True)

    with pytest.raises(ValueError):
        main.approve_tool_call("approval-1")


# --- full CLI entrypoint (main.main()) ---------------------------------


def test_main_approve_tool_call_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    tasks_dir = _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sys.argv", ["main.py", "approve-tool-call", "approval-1"]
    )

    main.main()

    resolution = ApprovalResolutionRepository(tasks_dir).get("approval-1")
    assert resolution.decision is ApprovalDecision.APPROVE


def test_main_unknown_approval_id_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sys.argv", ["main.py", "approve-tool-call", "does-not-exist"]
    )

    with pytest.raises(SystemExit) as excinfo:
        main.main()

    assert excinfo.value.code != 0
    assert "Traceback" not in capsys.readouterr().err
