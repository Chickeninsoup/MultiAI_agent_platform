from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.approval_continuation_preparation import (
    ApprovalContinuationPreparation,
)
from src.approval_continuation_preparation_errors import (
    ApprovalResolutionPendingError,
)
from src.approval_continuation_preparation_service import (
    ApprovalContinuationPreparationService,
)
from src.approval_decision import ApprovalDecision
from src.approval_decision_errors import (
    ApprovalCheckpointMismatchError,
    ApprovalRunNotFoundError,
    ApprovalRunNotWaitingForApprovalError,
    OrphanedApprovalRequestError,
)
from src.approval_errors import ApprovalRequestNotFoundError
from src.approval_request import ApprovalRequest, RiskLevel
from src.approval_request_repository import ApprovalRequestRepository
from src.approval_resolution import ApprovalResolution
from src.approval_resolution_repository import (
    ApprovalResolutionRepository,
)
from src.approval_store import ApprovalStore
from src.continuation_next_action import ContinuationNextAction
from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_result import ToolResult
from src.llm.types import LLMMessage
from src.repositories import RunRepository
from src.run_continuation_checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    RunContinuationCheckpoint,
)
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)
from src.run_events import InMemoryRunEventSink

SECRET = "super-secret-token"


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


def _tool_call(
    id_: str = "toolu_1",
    name: str = "write_file",
    content: str = SECRET,
) -> ToolCall:
    return ToolCall(
        id=id_, name=name, input={"path": "a.py", "content": content}
    )


def _make_request(
    store: ApprovalStore,
    *,
    approval_id: str = "approval-1",
    run_id: str = "run-007",
    tool_call: ToolCall | None = None,
) -> ApprovalRequest:
    request = ApprovalRequest(
        approval_id=approval_id,
        run_id=run_id,
        proposed_action=tool_call or _tool_call(),
        reason="writes files outside the sandbox",
        risk_level=RiskLevel.MEDIUM,
        input_preview="write a.py",
    )
    return store.create(request)


def _make_checkpoint(
    checkpoint_repository: RunContinuationCheckpointRepository,
    *,
    task_id: str = "task-1",
    run_id: str = "run-007",
    approval_id: str = "approval-1",
    tool_calls: tuple[ToolCall, ...] | None = None,
    pending_index: int = 0,
    completed_results: tuple[ToolResult, ...] = (),
) -> RunContinuationCheckpoint:
    calls = tool_calls or (_tool_call(),)
    checkpoint = RunContinuationCheckpoint(
        schema_version=CHECKPOINT_SCHEMA_VERSION,
        task_id=task_id,
        run_id=run_id,
        approval_id=approval_id,
        messages=(LLMMessage(role="user", content="do the task"),),
        pending_round_tool_calls=calls,
        pending_tool_call_index=pending_index,
        pending_tool_call_id=calls[pending_index].id,
        completed_tool_results=completed_results,
        llm_rounds=3,
        tool_rounds=2,
        cumulative_tool_calls=len(calls) + len(completed_results),
        total_input_tokens=1234,
        total_output_tokens=567,
        max_tool_rounds=8,
        max_total_tokens=100_000,
        created_at="2026-01-01T00:00:00Z",
    )
    checkpoint_repository.save(checkpoint)
    return checkpoint


def _build_scenario(
    tmp_path: Path,
    *,
    run_status: str = "waiting_for_approval",
    skip_checkpoint: bool = False,
    approval_id: str = "approval-1",
    run_id: str = "run-007",
    task_id: str = "task-1",
    tool_calls: tuple[ToolCall, ...] | None = None,
    pending_index: int = 0,
    completed_results: tuple[ToolResult, ...] = (),
    event_sink: InMemoryRunEventSink | None = None,
):
    tasks_dir = tmp_path / "tasks"
    _write_task_and_run(
        tasks_dir, task_id=task_id, run_id=run_id, run_status=run_status
    )

    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
        event_sink=event_sink,
    )
    calls = tool_calls or (_tool_call(),)
    request = _make_request(
        approval_store,
        approval_id=approval_id,
        run_id=run_id,
        tool_call=calls[pending_index],
    )

    checkpoint_repository = RunContinuationCheckpointRepository(
        tasks_dir
    )
    checkpoint = None
    if not skip_checkpoint:
        checkpoint = _make_checkpoint(
            checkpoint_repository,
            task_id=task_id,
            run_id=run_id,
            approval_id=approval_id,
            tool_calls=calls,
            pending_index=pending_index,
            completed_results=completed_results,
        )

    run_repository = RunRepository(tasks_dir)
    service = ApprovalContinuationPreparationService(
        run_repository, checkpoint_repository, approval_store
    )

    return {
        "tasks_dir": tasks_dir,
        "service": service,
        "store": approval_store,
        "checkpoints": checkpoint_repository,
        "runs": run_repository,
        "request": request,
        "checkpoint": checkpoint,
    }


# --- decision mapping -------------------------------------------------


def test_approve_yields_original_pending_call(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path)
    scenario["store"].resolve(
        "approval-1", ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.APPROVE
        )
    )

    preparation = scenario["service"].prepare("task-1", "run-007")

    assert (
        preparation.next_action
        is ContinuationNextAction.EXECUTE_PENDING_TOOL
    )
    assert preparation.decision is ApprovalDecision.APPROVE
    assert preparation.effective_tool_call == scenario[
        "checkpoint"
    ].pending_round_tool_calls[0]
    assert preparation.effective_tool_call is (
        preparation.checkpoint.pending_round_tool_calls[
            preparation.checkpoint.pending_tool_call_index
        ]
    )


def test_modify_replaces_input_and_preserves_id_name(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    modified_input = {"path": "sandbox/safe.py"}
    scenario["store"].resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1",
            decision=ApprovalDecision.MODIFY,
            modified_input=modified_input,
        ),
    )
    original_request = scenario["store"].get("approval-1")
    original_checkpoint = scenario["checkpoints"].load(
        "task-1", "run-007"
    )
    original_resolution = scenario["store"].get_resolution(
        "approval-1"
    )

    preparation = scenario["service"].prepare("task-1", "run-007")

    pending_call = scenario["checkpoint"].pending_round_tool_calls[0]
    assert preparation.next_action is (
        ContinuationNextAction.EXECUTE_PENDING_TOOL
    )
    assert preparation.decision is ApprovalDecision.MODIFY
    assert preparation.effective_tool_call.id == pending_call.id
    assert preparation.effective_tool_call.name == pending_call.name
    assert preparation.effective_tool_call.input == modified_input
    assert preparation.effective_tool_call is not pending_call

    # Original persisted records are untouched.
    assert scenario["store"].get("approval-1") == original_request
    assert (
        scenario["checkpoints"].load("task-1", "run-007")
        == original_checkpoint
    )
    assert (
        scenario["store"].get_resolution("approval-1")
        == original_resolution
    )


def test_mutating_effective_modified_input_does_not_mutate_resolution(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    modified_input = {"path": "sandbox/safe.py", "nested": {"a": 1}}
    scenario["store"].resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1",
            decision=ApprovalDecision.MODIFY,
            modified_input=modified_input,
        ),
    )

    preparation = scenario["service"].prepare("task-1", "run-007")
    preparation.effective_tool_call.input["nested"]["a"] = 999
    preparation.effective_tool_call.input["new_key"] = "added"

    resolution = scenario["store"].get_resolution("approval-1")
    assert resolution.modified_input == {
        "path": "sandbox/safe.py",
        "nested": {"a": 1},
    }


def test_reject_yields_non_execution_action(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path)
    scenario["store"].resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1",
            decision=ApprovalDecision.REJECT,
            explanation="too risky",
        ),
    )

    preparation = scenario["service"].prepare("task-1", "run-007")

    assert preparation.next_action is (
        ContinuationNextAction.REJECT_PENDING_TOOL
    )
    assert preparation.decision is ApprovalDecision.REJECT
    assert preparation.effective_tool_call is None


def test_cancel_yields_non_execution_action(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path)
    scenario["store"].resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.CANCEL
        ),
    )

    preparation = scenario["service"].prepare("task-1", "run-007")

    assert preparation.next_action is ContinuationNextAction.CANCEL_RUN
    assert preparation.decision is ApprovalDecision.CANCEL
    assert preparation.effective_tool_call is None


def test_reject_and_cancel_actions_are_distinct(tmp_path: Path) -> None:
    reject_scenario = _build_scenario(tmp_path / "a")
    reject_scenario["store"].resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.REJECT
        ),
    )
    reject_preparation = reject_scenario["service"].prepare(
        "task-1", "run-007"
    )

    cancel_scenario = _build_scenario(tmp_path / "b")
    cancel_scenario["store"].resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.CANCEL
        ),
    )
    cancel_preparation = cancel_scenario["service"].prepare(
        "task-1", "run-007"
    )

    assert (
        reject_preparation.next_action != cancel_preparation.next_action
    )


# --- not-ready ----------------------------------------------------------


def test_missing_decision_fails_explicitly(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path)

    with pytest.raises(ApprovalResolutionPendingError):
        scenario["service"].prepare("task-1", "run-007")


# --- validation failures --------------------------------------------------


def test_missing_run_raises(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    _make_request(approval_store)
    checkpoint_repository = RunContinuationCheckpointRepository(
        tasks_dir
    )
    _make_checkpoint(checkpoint_repository)
    service = ApprovalContinuationPreparationService(
        RunRepository(tasks_dir), checkpoint_repository, approval_store
    )

    with pytest.raises(ApprovalRunNotFoundError):
        service.prepare("task-1", "run-007")


def test_wrong_run_status_raises(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path, run_status="completed")

    with pytest.raises(ApprovalRunNotWaitingForApprovalError):
        scenario["service"].prepare("task-1", "run-007")


def test_missing_checkpoint_raises_orphan_error(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path, skip_checkpoint=True)

    with pytest.raises(OrphanedApprovalRequestError):
        scenario["service"].prepare("task-1", "run-007")


def test_checkpoint_references_unknown_approval_raises(
    tmp_path: Path,
) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task_and_run(tasks_dir)
    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    checkpoint_repository = RunContinuationCheckpointRepository(
        tasks_dir
    )
    # No ApprovalRequest ever created for "approval-1".
    _make_checkpoint(checkpoint_repository)
    service = ApprovalContinuationPreparationService(
        RunRepository(tasks_dir), checkpoint_repository, approval_store
    )

    with pytest.raises(ApprovalRequestNotFoundError):
        service.prepare("task-1", "run-007")


def test_pending_tool_call_input_mismatch_raises(
    tmp_path: Path,
) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task_and_run(tasks_dir)
    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    _make_request(
        approval_store,
        tool_call=ToolCall(
            id="toolu_1", name="write_file", input={"path": "a.py"}
        ),
    )
    checkpoint_repository = RunContinuationCheckpointRepository(
        tasks_dir
    )
    _make_checkpoint(
        checkpoint_repository,
        tool_calls=(
            ToolCall(
                id="toolu_1",
                name="write_file",
                input={"path": "different.py"},
            ),
        ),
    )
    service = ApprovalContinuationPreparationService(
        RunRepository(tasks_dir), checkpoint_repository, approval_store
    )
    approval_store.resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.APPROVE
        ),
    )

    with pytest.raises(ApprovalCheckpointMismatchError):
        service.prepare("task-1", "run-007")


def test_checkpoint_run_id_mismatch_raises(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task_and_run(tasks_dir)
    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    _make_request(approval_store)
    checkpoint_repository = RunContinuationCheckpointRepository(
        tasks_dir
    )
    checkpoint = RunContinuationCheckpoint(
        schema_version=CHECKPOINT_SCHEMA_VERSION,
        task_id="task-1",
        run_id="run-different",
        approval_id="approval-1",
        messages=(LLMMessage(role="user", content="x"),),
        pending_round_tool_calls=(_tool_call(),),
        pending_tool_call_index=0,
        pending_tool_call_id="toolu_1",
        completed_tool_results=(),
        llm_rounds=1,
        tool_rounds=1,
        cumulative_tool_calls=1,
        total_input_tokens=1,
        total_output_tokens=1,
        max_tool_rounds=8,
        max_total_tokens=100_000,
    )
    file_path = checkpoint_repository.get_checkpoint_file(
        "task-1", "run-007"
    )
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(checkpoint.to_dict()), encoding="utf-8"
    )
    approval_store.resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.APPROVE
        ),
    )
    service = ApprovalContinuationPreparationService(
        RunRepository(tasks_dir), checkpoint_repository, approval_store
    )

    with pytest.raises(ApprovalCheckpointMismatchError):
        service.prepare("task-1", "run-007")


# --- multi-call rounds ------------------------------------------------


def test_three_call_round_preserves_all_positions(
    tmp_path: Path,
) -> None:
    call_a = _tool_call(id_="toolu_a", name="read_file")
    call_b = _tool_call(id_="toolu_b", name="write_file")
    call_c = _tool_call(id_="toolu_c", name="run_test")
    result_a = ToolResult(
        tool_call_id="toolu_a",
        tool_name="read_file",
        success=True,
        output="contents of a",
    )
    scenario = _build_scenario(
        tmp_path,
        tool_calls=(call_a, call_b, call_c),
        pending_index=1,
        completed_results=(result_a,),
    )
    scenario["store"].resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.APPROVE
        ),
    )

    preparation = scenario["service"].prepare("task-1", "run-007")

    assert preparation.checkpoint.pending_round_tool_calls == (
        call_a,
        call_b,
        call_c,
    )
    assert preparation.checkpoint.completed_tool_results == (result_a,)
    assert preparation.checkpoint.pending_tool_call_index == 1
    assert preparation.pending_tool_call == call_b
    assert preparation.effective_tool_call == call_b


def test_counters_and_budgets_remain_unchanged(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path)
    original_checkpoint = scenario["checkpoint"]
    scenario["store"].resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.APPROVE
        ),
    )

    preparation = scenario["service"].prepare("task-1", "run-007")

    assert (
        preparation.checkpoint.llm_rounds
        == original_checkpoint.llm_rounds
    )
    assert (
        preparation.checkpoint.tool_rounds
        == original_checkpoint.tool_rounds
    )
    assert (
        preparation.checkpoint.cumulative_tool_calls
        == original_checkpoint.cumulative_tool_calls
    )
    assert (
        preparation.checkpoint.total_input_tokens
        == original_checkpoint.total_input_tokens
    )
    assert (
        preparation.checkpoint.total_output_tokens
        == original_checkpoint.total_output_tokens
    )
    assert (
        preparation.checkpoint.max_tool_rounds
        == original_checkpoint.max_tool_rounds
    )
    assert (
        preparation.checkpoint.max_total_tokens
        == original_checkpoint.max_total_tokens
    )


# --- restart / idempotency ----------------------------------------------


def test_restart_rebuilt_repositories_prepare_successfully(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    scenario["store"].resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.APPROVE
        ),
    )
    tasks_dir = scenario["tasks_dir"]

    # Discard every in-memory object and rebuild from disk.
    rebuilt_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    rebuilt_service = ApprovalContinuationPreparationService(
        RunRepository(tasks_dir),
        RunContinuationCheckpointRepository(tasks_dir),
        rebuilt_store,
    )

    preparation = rebuilt_service.prepare("task-1", "run-007")

    assert (
        preparation.next_action
        is ContinuationNextAction.EXECUTE_PENDING_TOOL
    )


def test_repeated_preparation_writes_nothing(tmp_path: Path) -> None:
    sink = InMemoryRunEventSink()
    scenario = _build_scenario(tmp_path, event_sink=sink)
    scenario["store"].resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.APPROVE
        ),
    )
    tasks_dir = scenario["tasks_dir"]

    def _snapshot() -> dict[str, float]:
        return {
            str(path): path.stat().st_mtime_ns
            for path in sorted(tasks_dir.rglob("*"))
            if path.is_file()
        }

    before = _snapshot()
    events_before = len(sink.events)

    scenario["service"].prepare("task-1", "run-007")
    scenario["service"].prepare("task-1", "run-007")
    scenario["service"].prepare("task-1", "run-007")

    after = _snapshot()
    assert after == before
    assert len(sink.events) == events_before


# --- secrecy --------------------------------------------------------------


def test_secret_absent_from_preparation_repr(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path)
    scenario["store"].resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1",
            decision=ApprovalDecision.MODIFY,
            modified_input={"path": "a.py", "content": "another-secret"},
        ),
    )

    preparation = scenario["service"].prepare("task-1", "run-007")

    assert SECRET not in repr(preparation)
    assert "another-secret" not in repr(preparation)


def test_secret_absent_from_validation_errors(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path, run_status="completed")

    with pytest.raises(
        ApprovalRunNotWaitingForApprovalError
    ) as excinfo:
        scenario["service"].prepare("task-1", "run-007")

    assert SECRET not in str(excinfo.value)


def test_secret_absent_from_mismatch_error(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task_and_run(tasks_dir)
    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    _make_request(
        approval_store,
        tool_call=ToolCall(
            id="toolu_1", name="write_file", input={"path": "a.py"}
        ),
    )
    checkpoint_repository = RunContinuationCheckpointRepository(
        tasks_dir
    )
    _make_checkpoint(
        checkpoint_repository,
        tool_calls=(
            ToolCall(
                id="toolu_1",
                name="write_file",
                input={"path": "a.py", "content": SECRET},
            ),
        ),
    )
    service = ApprovalContinuationPreparationService(
        RunRepository(tasks_dir), checkpoint_repository, approval_store
    )
    approval_store.resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.APPROVE
        ),
    )

    with pytest.raises(ApprovalCheckpointMismatchError) as excinfo:
        service.prepare("task-1", "run-007")

    assert SECRET not in str(excinfo.value)
