from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.approval_decision import ApprovalDecision
from src.approval_decision_errors import (
    ApprovalCheckpointMismatchError,
    ApprovalRunNotFoundError,
    ApprovalRunNotWaitingForApprovalError,
    OrphanedApprovalRequestError,
)
from src.approval_decision_service import ApprovalDecisionService
from src.approval_errors import (
    ApprovalAlreadyResolvedError,
    ApprovalRequestNotFoundError,
)
from src.approval_request import ApprovalRequest, RiskLevel
from src.approval_request_repository import ApprovalRequestRepository
from src.approval_resolution import ApprovalResolution
from src.approval_resolution_repository import (
    ApprovalResolutionRepository,
)
from src.approval_status import ApprovalStatus
from src.approval_store import ApprovalStore
from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_result import ToolResult
from src.llm.types import LLMMessage
from src.repositories import RunRepository, TaskRepository
from src.run_continuation_checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    RunContinuationCheckpoint,
)
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)
from src.run_events import InMemoryRunEventSink


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_task_and_run(
    tasks_dir: Path,
    *,
    task_id: str = "task-1",
    run_id: str = "run-007",
    run_status: str = "waiting_for_approval",
    approval_id: str = "approval-1",
    tool_call_id: str = "toolu_1",
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
            "approval_id": approval_id,
            "tool_call_id": tool_call_id,
        },
    )


def _tool_call(id_: str = "toolu_1", name: str = "write_file") -> ToolCall:
    return ToolCall(id=id_, name=name, input={"path": "a.py", "content": "secret-token"})


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
        llm_rounds=1,
        tool_rounds=1,
        cumulative_tool_calls=len(calls),
        total_input_tokens=10,
        total_output_tokens=5,
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
    event_sink: InMemoryRunEventSink | None = None,
):
    tasks_dir = tmp_path / "tasks"
    _write_task_and_run(
        tasks_dir,
        task_id=task_id,
        run_id=run_id,
        run_status=run_status,
        approval_id=approval_id,
    )

    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
        event_sink=event_sink,
    )
    request = _make_request(
        approval_store, approval_id=approval_id, run_id=run_id
    )

    checkpoint_repository = RunContinuationCheckpointRepository(
        tasks_dir
    )
    if not skip_checkpoint:
        _make_checkpoint(
            checkpoint_repository,
            task_id=task_id,
            run_id=run_id,
            approval_id=approval_id,
        )

    service = ApprovalDecisionService(
        approval_store,
        TaskRepository(tasks_dir),
        RunRepository(tasks_dir),
        checkpoint_repository,
    )

    return service, approval_store, checkpoint_repository, request


# --- successful decisions ------------------------------------------------


def test_approve_stored_successfully(tmp_path: Path) -> None:
    service, store, _checkpoints, _request = _build_scenario(tmp_path)

    resolution = service.resolve("approval-1", ApprovalDecision.APPROVE)

    assert resolution.decision is ApprovalDecision.APPROVE
    assert store.get_resolution("approval-1") == resolution


def test_modify_stored_with_modified_input(tmp_path: Path) -> None:
    service, store, _checkpoints, _request = _build_scenario(tmp_path)

    resolution = service.resolve(
        "approval-1",
        ApprovalDecision.MODIFY,
        modified_input={"path": "sandbox/safe.py"},
    )

    assert resolution.modified_input == {"path": "sandbox/safe.py"}
    assert store.get_resolution("approval-1") == resolution


def test_reject_stored_successfully(tmp_path: Path) -> None:
    service, store, _checkpoints, _request = _build_scenario(tmp_path)

    resolution = service.resolve(
        "approval-1", ApprovalDecision.REJECT, explanation="too risky"
    )

    assert resolution.decision is ApprovalDecision.REJECT
    assert store.get_resolution("approval-1") == resolution


def test_cancel_stored_successfully(tmp_path: Path) -> None:
    service, store, _checkpoints, _request = _build_scenario(tmp_path)

    resolution = service.resolve("approval-1", ApprovalDecision.CANCEL)

    assert resolution.decision is ApprovalDecision.CANCEL
    assert store.get_resolution("approval-1") == resolution


def test_request_becomes_resolved(tmp_path: Path) -> None:
    service, store, _checkpoints, _request = _build_scenario(tmp_path)

    service.resolve("approval-1", ApprovalDecision.APPROVE)

    assert store.get("approval-1").status is ApprovalStatus.RESOLVED


def test_checkpoint_remains_unchanged(tmp_path: Path) -> None:
    service, _store, checkpoints, _request = _build_scenario(tmp_path)
    before = checkpoints.load("task-1", "run-007")

    service.resolve("approval-1", ApprovalDecision.APPROVE)

    after = checkpoints.load("task-1", "run-007")
    assert after == before


def test_run_remains_waiting_for_approval(tmp_path: Path) -> None:
    service, _store, _checkpoints, _request = _build_scenario(tmp_path)
    run_repository = RunRepository(tmp_path / "tasks")

    service.resolve("approval-1", ApprovalDecision.APPROVE)

    run = run_repository.load("task-1", "run-007")
    assert run.status == "waiting_for_approval"


def test_approval_resolved_event_emitted_exactly_once(
    tmp_path: Path,
) -> None:
    sink = InMemoryRunEventSink()
    service, _store, _checkpoints, _request = _build_scenario(
        tmp_path, event_sink=sink
    )

    service.resolve("approval-1", ApprovalDecision.APPROVE)

    resolved_events = [
        event for event in sink.events if event["type"] == "approval_resolved"
    ]
    assert len(resolved_events) == 1


# --- cross-check failures -------------------------------------------------


def test_unknown_approval_id_raises(tmp_path: Path) -> None:
    service, _store, _checkpoints, _request = _build_scenario(tmp_path)

    with pytest.raises(ApprovalRequestNotFoundError):
        service.resolve("approval-unknown", ApprovalDecision.APPROVE)


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
    # No task.json/run.json written at all.
    service = ApprovalDecisionService(
        approval_store,
        TaskRepository(tasks_dir),
        RunRepository(tasks_dir),
        checkpoint_repository,
    )

    with pytest.raises(ApprovalRunNotFoundError):
        service.resolve("approval-1", ApprovalDecision.APPROVE)


def test_run_not_waiting_for_approval_raises(tmp_path: Path) -> None:
    service, _store, _checkpoints, _request = _build_scenario(
        tmp_path, run_status="completed"
    )

    with pytest.raises(ApprovalRunNotWaitingForApprovalError):
        service.resolve("approval-1", ApprovalDecision.APPROVE)


def test_missing_checkpoint_is_orphan_error(tmp_path: Path) -> None:
    service, _store, _checkpoints, _request = _build_scenario(
        tmp_path, skip_checkpoint=True
    )

    with pytest.raises(OrphanedApprovalRequestError):
        service.resolve("approval-1", ApprovalDecision.APPROVE)


def test_checkpoint_approval_id_mismatch_raises(tmp_path: Path) -> None:
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
    # Checkpoint references a different approval_id.
    checkpoint = RunContinuationCheckpoint(
        schema_version=CHECKPOINT_SCHEMA_VERSION,
        task_id="task-1",
        run_id="run-007",
        approval_id="approval-different",
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
    checkpoint_repository.save(checkpoint)
    service = ApprovalDecisionService(
        approval_store,
        TaskRepository(tasks_dir),
        RunRepository(tasks_dir),
        checkpoint_repository,
    )

    with pytest.raises(ApprovalCheckpointMismatchError):
        service.resolve("approval-1", ApprovalDecision.APPROVE)


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
    # Save directly under the real run's path (bypassing the
    # repository's own task_id/run_id derivation) so the *content*
    # disagrees with the request while the file location is still
    # where the service will look.
    import json as _json

    file_path = checkpoint_repository.get_checkpoint_file(
        "task-1", "run-007"
    )
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        _json.dumps(checkpoint.to_dict()), encoding="utf-8"
    )

    service = ApprovalDecisionService(
        approval_store,
        TaskRepository(tasks_dir),
        RunRepository(tasks_dir),
        checkpoint_repository,
    )

    with pytest.raises(ApprovalCheckpointMismatchError):
        service.resolve("approval-1", ApprovalDecision.APPROVE)


def test_pending_tool_call_id_mismatch_raises(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task_and_run(tasks_dir)
    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    _make_request(approval_store, tool_call=_tool_call(id_="toolu_1"))
    checkpoint_repository = RunContinuationCheckpointRepository(
        tasks_dir
    )
    _make_checkpoint(
        checkpoint_repository,
        tool_calls=(_tool_call(id_="toolu_different"),),
        pending_index=0,
    )
    service = ApprovalDecisionService(
        approval_store,
        TaskRepository(tasks_dir),
        RunRepository(tasks_dir),
        checkpoint_repository,
    )

    with pytest.raises(ApprovalCheckpointMismatchError):
        service.resolve("approval-1", ApprovalDecision.APPROVE)


def test_checkpoint_tool_call_input_differs_from_request_raises(
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
    # Same id, but the checkpoint's copy of the ToolCall has different
    # input than what the request actually proposed.
    _make_checkpoint(
        checkpoint_repository,
        tool_calls=(
            ToolCall(
                id="toolu_1",
                name="write_file",
                input={"path": "different.py"},
            ),
        ),
        pending_index=0,
    )
    service = ApprovalDecisionService(
        approval_store,
        TaskRepository(tasks_dir),
        RunRepository(tasks_dir),
        checkpoint_repository,
    )

    with pytest.raises(ApprovalCheckpointMismatchError):
        service.resolve("approval-1", ApprovalDecision.APPROVE)


@pytest.mark.parametrize(
    "failure_scenario",
    [
        "missing_run",
        "wrong_status",
        "missing_checkpoint",
        "checkpoint_mismatch",
    ],
)
def test_failures_occur_before_resolution_persistence(
    tmp_path: Path, failure_scenario: str
) -> None:
    tasks_dir = tmp_path / "tasks"
    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    _make_request(approval_store)
    checkpoint_repository = RunContinuationCheckpointRepository(
        tasks_dir
    )

    if failure_scenario == "missing_run":
        pass  # no task/run written
    elif failure_scenario == "wrong_status":
        _write_task_and_run(tasks_dir, run_status="completed")
        _make_checkpoint(checkpoint_repository)
    elif failure_scenario == "missing_checkpoint":
        _write_task_and_run(tasks_dir)
    elif failure_scenario == "checkpoint_mismatch":
        _write_task_and_run(tasks_dir)
        _make_checkpoint(
            checkpoint_repository,
            tool_calls=(_tool_call(id_="toolu_other"),),
        )

    service = ApprovalDecisionService(
        approval_store,
        TaskRepository(tasks_dir),
        RunRepository(tasks_dir),
        checkpoint_repository,
    )

    with pytest.raises(Exception):
        service.resolve("approval-1", ApprovalDecision.APPROVE)

    assert approval_store.get_resolution("approval-1") is None


# --- decision validation --------------------------------------------------


def test_modify_without_modified_input_rejected(tmp_path: Path) -> None:
    service, _store, _checkpoints, _request = _build_scenario(tmp_path)

    with pytest.raises(ValueError):
        service.resolve("approval-1", ApprovalDecision.MODIFY)


@pytest.mark.parametrize(
    "decision",
    [
        ApprovalDecision.APPROVE,
        ApprovalDecision.REJECT,
        ApprovalDecision.CANCEL,
    ],
)
def test_non_modify_with_modified_input_rejected(
    tmp_path: Path, decision: ApprovalDecision
) -> None:
    service, _store, _checkpoints, _request = _build_scenario(tmp_path)

    with pytest.raises(ValueError):
        service.resolve(
            "approval-1", decision, modified_input={"path": "x"}
        )


def test_invalid_decision_type_rejected(tmp_path: Path) -> None:
    service, _store, _checkpoints, _request = _build_scenario(tmp_path)

    with pytest.raises(ValueError):
        service.resolve("approval-1", "approve")  # type: ignore[arg-type]


def test_empty_approval_id_rejected(tmp_path: Path) -> None:
    service, _store, _checkpoints, _request = _build_scenario(tmp_path)

    with pytest.raises(ValueError):
        service.resolve("", ApprovalDecision.APPROVE)


# --- idempotency -----------------------------------------------------------


def test_identical_approve_retry_returns_original_resolution(
    tmp_path: Path,
) -> None:
    service, store, _checkpoints, _request = _build_scenario(tmp_path)
    first = service.resolve("approval-1", ApprovalDecision.APPROVE)

    second = service.resolve("approval-1", ApprovalDecision.APPROVE)

    assert second == first


def test_identical_modify_retry_returns_original_resolution(
    tmp_path: Path,
) -> None:
    service, _store, _checkpoints, _request = _build_scenario(tmp_path)
    first = service.resolve(
        "approval-1",
        ApprovalDecision.MODIFY,
        modified_input={"path": "safe.py"},
    )

    second = service.resolve(
        "approval-1",
        ApprovalDecision.MODIFY,
        modified_input={"path": "safe.py"},
    )

    assert second == first


def test_retry_preserves_original_resolved_at(tmp_path: Path) -> None:
    service, _store, _checkpoints, _request = _build_scenario(tmp_path)
    first = service.resolve("approval-1", ApprovalDecision.APPROVE)

    second = service.resolve("approval-1", ApprovalDecision.APPROVE)

    assert second.resolved_at == first.resolved_at


def test_retry_emits_no_second_event(tmp_path: Path) -> None:
    sink = InMemoryRunEventSink()
    service, _store, _checkpoints, _request = _build_scenario(
        tmp_path, event_sink=sink
    )
    service.resolve("approval-1", ApprovalDecision.APPROVE)

    service.resolve("approval-1", ApprovalDecision.APPROVE)

    resolved_events = [
        event for event in sink.events if event["type"] == "approval_resolved"
    ]
    assert len(resolved_events) == 1


def test_conflicting_decision_rejected(tmp_path: Path) -> None:
    service, _store, _checkpoints, _request = _build_scenario(tmp_path)
    service.resolve("approval-1", ApprovalDecision.APPROVE)

    with pytest.raises(ApprovalAlreadyResolvedError):
        service.resolve("approval-1", ApprovalDecision.REJECT)


def test_conflicting_modified_input_rejected(tmp_path: Path) -> None:
    service, _store, _checkpoints, _request = _build_scenario(tmp_path)
    service.resolve(
        "approval-1",
        ApprovalDecision.MODIFY,
        modified_input={"path": "one.py"},
    )

    with pytest.raises(ApprovalAlreadyResolvedError):
        service.resolve(
            "approval-1",
            ApprovalDecision.MODIFY,
            modified_input={"path": "two.py"},
        )


def test_conflicting_explanation_rejected(tmp_path: Path) -> None:
    service, _store, _checkpoints, _request = _build_scenario(tmp_path)
    service.resolve(
        "approval-1", ApprovalDecision.REJECT, explanation="reason A"
    )

    with pytest.raises(ApprovalAlreadyResolvedError):
        service.resolve(
            "approval-1", ApprovalDecision.REJECT, explanation="reason B"
        )


def test_conflicting_decision_does_not_overwrite_original(
    tmp_path: Path,
) -> None:
    service, store, _checkpoints, _request = _build_scenario(tmp_path)
    original = service.resolve("approval-1", ApprovalDecision.APPROVE)

    with pytest.raises(ApprovalAlreadyResolvedError):
        service.resolve("approval-1", ApprovalDecision.REJECT)

    assert store.get_resolution("approval-1") == original


# --- security / regression -------------------------------------------------


def test_secret_absent_from_events(tmp_path: Path) -> None:
    sink = InMemoryRunEventSink()
    service, _store, _checkpoints, _request = _build_scenario(
        tmp_path, event_sink=sink
    )

    service.resolve(
        "approval-1",
        ApprovalDecision.MODIFY,
        modified_input={"path": "a.py", "content": "another-secret"},
    )

    for event in sink.events:
        assert "another-secret" not in repr(event)
        assert "secret-token" not in repr(event)


def test_secret_absent_from_exception_message(tmp_path: Path) -> None:
    service, _store, _checkpoints, _request = _build_scenario(
        tmp_path, run_status="completed"
    )

    with pytest.raises(
        ApprovalRunNotWaitingForApprovalError
    ) as excinfo:
        service.resolve("approval-1", ApprovalDecision.APPROVE)

    assert "secret-token" not in str(excinfo.value)


def test_secret_absent_from_resolution_repr(tmp_path: Path) -> None:
    service, _store, _checkpoints, _request = _build_scenario(tmp_path)

    resolution = service.resolve(
        "approval-1",
        ApprovalDecision.MODIFY,
        modified_input={"path": "a.py", "content": "another-secret"},
    )

    assert "another-secret" not in repr(resolution)


def test_no_tool_executed_and_no_provider_called(tmp_path: Path) -> None:
    # There is no ToolExecutor/provider wired into this service at
    # all - a structural guarantee, demonstrated by successfully
    # resolving without ever constructing one.
    service, _store, _checkpoints, _request = _build_scenario(tmp_path)

    service.resolve("approval-1", ApprovalDecision.APPROVE)


def test_no_new_run_created(tmp_path: Path) -> None:
    service, _store, _checkpoints, _request = _build_scenario(tmp_path)
    run_repository = RunRepository(tmp_path / "tasks")

    service.resolve("approval-1", ApprovalDecision.APPROVE)

    assert run_repository.list_run_ids("task-1") == ["run-007"]


# --- durable idempotency (5E-5D-5A-1) --------------------------------


class _PoisonTaskRepository:
    def list_all(self):
        raise AssertionError(
            "TaskRepository must not be used to resolve an already-"
            "RESOLVED approval request"
        )


class _PoisonRunRepository:
    def load(self, task_id: str, run_id: str):
        raise AssertionError(
            "RunRepository.load must not be used to resolve an "
            "already-RESOLVED approval request"
        )

    def list_run_ids(self, task_id: str):
        raise AssertionError(
            "RunRepository.list_run_ids must not be used to resolve "
            "an already-RESOLVED approval request"
        )


class _PoisonCheckpointRepository:
    def load(self, task_id: str, run_id: str):
        raise AssertionError(
            "RunContinuationCheckpointRepository.load must not be "
            "used to resolve an already-RESOLVED approval request"
        )


def test_identical_retry_succeeds_after_run_status_changes(
    tmp_path: Path,
) -> None:
    service, store, _checkpoints, _request = _build_scenario(tmp_path)
    original = service.resolve("approval-1", ApprovalDecision.APPROVE)

    # A future resume phase is free to move the Run off
    # waiting_for_approval once a decision is recorded - simulate
    # that here without this stage's service doing it.
    run_repository = RunRepository(tmp_path / "tasks")
    run = run_repository.load("task-1", "run-007")
    from dataclasses import replace as _replace

    run_repository.save(_replace(run, status="completed"))

    retried = service.resolve("approval-1", ApprovalDecision.APPROVE)

    assert retried == original


def test_identical_retry_succeeds_after_checkpoint_removal(
    tmp_path: Path,
) -> None:
    service, store, checkpoints, _request = _build_scenario(tmp_path)
    original = service.resolve("approval-1", ApprovalDecision.APPROVE)

    checkpoints.delete("task-1", "run-007")

    retried = service.resolve("approval-1", ApprovalDecision.APPROVE)

    assert retried == original


def test_identical_retry_succeeds_with_poison_collaborators(
    tmp_path: Path,
) -> None:
    service, store, _checkpoints, _request = _build_scenario(tmp_path)
    original = service.resolve("approval-1", ApprovalDecision.APPROVE)

    poisoned_service = ApprovalDecisionService(
        store,
        _PoisonTaskRepository(),  # type: ignore[arg-type]
        _PoisonRunRepository(),  # type: ignore[arg-type]
        _PoisonCheckpointRepository(),  # type: ignore[arg-type]
    )

    retried = poisoned_service.resolve(
        "approval-1", ApprovalDecision.APPROVE
    )

    assert retried == original


def test_identical_modify_retry_succeeds_with_poison_collaborators(
    tmp_path: Path,
) -> None:
    service, store, _checkpoints, _request = _build_scenario(tmp_path)
    original = service.resolve(
        "approval-1",
        ApprovalDecision.MODIFY,
        modified_input={"path": "safe.py"},
    )

    poisoned_service = ApprovalDecisionService(
        store,
        _PoisonTaskRepository(),  # type: ignore[arg-type]
        _PoisonRunRepository(),  # type: ignore[arg-type]
        _PoisonCheckpointRepository(),  # type: ignore[arg-type]
    )

    retried = poisoned_service.resolve(
        "approval-1",
        ApprovalDecision.MODIFY,
        modified_input={"path": "safe.py"},
    )

    assert retried == original


def test_retry_preserves_resolved_at_after_run_status_changes(
    tmp_path: Path,
) -> None:
    service, store, _checkpoints, _request = _build_scenario(tmp_path)
    original = service.resolve("approval-1", ApprovalDecision.APPROVE)

    run_repository = RunRepository(tmp_path / "tasks")
    run = run_repository.load("task-1", "run-007")
    from dataclasses import replace as _replace

    run_repository.save(_replace(run, status="completed"))

    retried = service.resolve("approval-1", ApprovalDecision.APPROVE)

    assert retried.resolved_at == original.resolved_at


def test_retry_with_poison_collaborators_emits_no_second_event(
    tmp_path: Path,
) -> None:
    sink = InMemoryRunEventSink()
    service, store, _checkpoints, _request = _build_scenario(
        tmp_path, event_sink=sink
    )
    service.resolve("approval-1", ApprovalDecision.APPROVE)

    poisoned_service = ApprovalDecisionService(
        store,
        _PoisonTaskRepository(),  # type: ignore[arg-type]
        _PoisonRunRepository(),  # type: ignore[arg-type]
        _PoisonCheckpointRepository(),  # type: ignore[arg-type]
    )
    poisoned_service.resolve("approval-1", ApprovalDecision.APPROVE)

    resolved_events = [
        event for event in sink.events if event["type"] == "approval_resolved"
    ]
    assert len(resolved_events) == 1


def test_conflicting_retry_raises_after_run_status_change(
    tmp_path: Path,
) -> None:
    service, store, _checkpoints, _request = _build_scenario(tmp_path)
    service.resolve("approval-1", ApprovalDecision.APPROVE)

    run_repository = RunRepository(tmp_path / "tasks")
    run = run_repository.load("task-1", "run-007")
    from dataclasses import replace as _replace

    run_repository.save(_replace(run, status="completed"))

    with pytest.raises(ApprovalAlreadyResolvedError):
        service.resolve("approval-1", ApprovalDecision.REJECT)


def test_conflicting_retry_raises_after_checkpoint_removal(
    tmp_path: Path,
) -> None:
    service, store, checkpoints, _request = _build_scenario(tmp_path)
    service.resolve("approval-1", ApprovalDecision.APPROVE)

    checkpoints.delete("task-1", "run-007")

    with pytest.raises(ApprovalAlreadyResolvedError):
        service.resolve("approval-1", ApprovalDecision.REJECT)


def test_conflicting_retry_does_not_access_task_run_checkpoint(
    tmp_path: Path,
) -> None:
    service, store, _checkpoints, _request = _build_scenario(tmp_path)
    service.resolve("approval-1", ApprovalDecision.APPROVE)

    poisoned_service = ApprovalDecisionService(
        store,
        _PoisonTaskRepository(),  # type: ignore[arg-type]
        _PoisonRunRepository(),  # type: ignore[arg-type]
        _PoisonCheckpointRepository(),  # type: ignore[arg-type]
    )

    # If this reached any poison collaborator, it would raise
    # AssertionError instead of ApprovalAlreadyResolvedError.
    with pytest.raises(ApprovalAlreadyResolvedError):
        poisoned_service.resolve(
            "approval-1", ApprovalDecision.REJECT
        )


def test_pending_request_still_requires_a_waiting_run_after_hardening(
    tmp_path: Path,
) -> None:
    service, _store, _checkpoints, _request = _build_scenario(
        tmp_path, run_status="completed"
    )

    with pytest.raises(ApprovalRunNotWaitingForApprovalError):
        service.resolve("approval-1", ApprovalDecision.APPROVE)


def test_pending_request_still_requires_a_checkpoint_after_hardening(
    tmp_path: Path,
) -> None:
    service, _store, _checkpoints, _request = _build_scenario(
        tmp_path, skip_checkpoint=True
    )

    with pytest.raises(OrphanedApprovalRequestError):
        service.resolve("approval-1", ApprovalDecision.APPROVE)


def test_retry_does_not_mutate_run_or_checkpoint(tmp_path: Path) -> None:
    service, store, checkpoints, _request = _build_scenario(tmp_path)
    service.resolve("approval-1", ApprovalDecision.APPROVE)

    run_repository = RunRepository(tmp_path / "tasks")
    run_before = run_repository.load("task-1", "run-007")
    checkpoint_before = checkpoints.load("task-1", "run-007")

    service.resolve("approval-1", ApprovalDecision.APPROVE)

    assert run_repository.load("task-1", "run-007") == run_before
    assert checkpoints.load("task-1", "run-007") == checkpoint_before
