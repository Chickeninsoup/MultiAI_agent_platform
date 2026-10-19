from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

import pytest

from src.approval_application_errors import (
    ApprovalApplicationBlockedError,
    ApprovalApplicationDispatchError,
    ApprovalApplicationMismatchError,
    ApprovalApplicationPersistenceError,
)
from src.approval_application_repository import (
    ApprovalApplicationRepository,
)
from src.approval_application_service import ApprovalApplicationService
from src.approval_application_status import ApprovalApplicationStatus
from src.approval_continuation_preparation_errors import (
    ApprovalResolutionPendingError,
)
from src.approval_continuation_preparation_service import (
    ApprovalContinuationPreparationService,
)
from src.approval_decision import ApprovalDecision
from src.approval_decision_errors import (
    ApprovalRunNotWaitingForApprovalError,
)
from src.approval_request import ApprovalRequest, RiskLevel
from src.approval_request_repository import ApprovalRequestRepository
from src.approval_resolution import ApprovalResolution
from src.approval_resolution_repository import (
    ApprovalResolutionRepository,
)
from src.approval_store import ApprovalStore
from src.continuation_next_action import ContinuationNextAction
from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_definition import ToolDefinition
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
from src.services.tools.tool_executor import ToolExecutor
from src.services.tools.tool_policy import ToolPolicy, ToolPolicyEntry

SECRET = "super-secret-token"


class RecordingToolHandler:
    def __init__(
        self,
        name: str = "write_file",
        on_execute: (
            Callable[[str, dict[str, Any]], ToolResult] | None
        ) = None,
    ) -> None:
        self.name = name
        self.definition = ToolDefinition(
            name=name, description="test tool", input_schema={}
        )
        self.calls: list[dict[str, Any]] = []
        self._on_execute = on_execute

    def execute(
        self,
        *,
        tool_call_id: str,
        tool_input: dict[str, Any],
        repository_root: Path,
        max_output_chars: int,
    ) -> ToolResult:
        self.calls.append(
            {"tool_call_id": tool_call_id, "tool_input": tool_input}
        )

        if self._on_execute is not None:
            return self._on_execute(tool_call_id, tool_input)

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            success=True,
            output=f"wrote {tool_input.get('path')}",
        )


class RaisingToolExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, tool_call: ToolCall) -> ToolResult:
        self.calls += 1
        raise RuntimeError("dispatch exploded")


class ClaimFailingRepository(ApprovalApplicationRepository):
    def create_exclusive(self, record) -> bool:  # type: ignore[override]
        raise OSError("disk unavailable")


class CompleteFailingRepository(ApprovalApplicationRepository):
    def complete(self, approval_id, outcome):  # type: ignore[override]
        raise OSError("disk unavailable")


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
    approval_id: str = "approval-1",
    run_id: str = "run-007",
    task_id: str = "task-1",
    tool_calls: tuple[ToolCall, ...] | None = None,
    pending_index: int = 0,
    completed_results: tuple[ToolResult, ...] = (),
    enabled_tools: set[str] | None = None,
    handler: RecordingToolHandler | None = None,
    application_repository_cls: type[
        ApprovalApplicationRepository
    ] = ApprovalApplicationRepository,
    tool_executor_override: Any = None,
    event_sink: InMemoryRunEventSink | None = None,
) -> dict[str, Any]:
    tasks_dir = tmp_path / "tasks"
    _write_task_and_run(
        tasks_dir, task_id=task_id, run_id=run_id, run_status=run_status
    )

    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
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
    preparation_service = ApprovalContinuationPreparationService(
        run_repository, checkpoint_repository, approval_store
    )

    application_repository = application_repository_cls(tasks_dir)

    handler = handler or RecordingToolHandler()
    enabled = enabled_tools if enabled_tools is not None else {
        "write_file"
    }
    tool_policy = ToolPolicy(
        default="deny",
        tools={
            tool_name: ToolPolicyEntry(enabled=True)
            for tool_name in enabled
        },
    )
    tool_executor = tool_executor_override or ToolExecutor(
        repository_root=tmp_path / "repo",
        handlers=[handler],
        tool_policy=tool_policy,
    )

    service = ApprovalApplicationService(
        preparation_service,
        application_repository,
        tool_executor,
        event_sink=event_sink,
    )

    return {
        "tasks_dir": tasks_dir,
        "service": service,
        "store": approval_store,
        "checkpoints": checkpoint_repository,
        "runs": run_repository,
        "applications": application_repository,
        "request": request,
        "checkpoint": checkpoint,
        "handler": handler,
        "preparation_service": preparation_service,
        "tool_executor": tool_executor,
    }


def _resolve(
    scenario: dict[str, Any],
    decision: ApprovalDecision,
    *,
    approval_id: str = "approval-1",
    modified_input: dict[str, Any] | None = None,
    explanation: str | None = None,
) -> None:
    scenario["store"].resolve(
        approval_id,
        ApprovalResolution(
            approval_id=approval_id,
            decision=decision,
            modified_input=modified_input,
            explanation=explanation,
        ),
    )


# --- decision behavior ------------------------------------------------


def test_approve_executes_original_input_and_persists_result(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    _resolve(scenario, ApprovalDecision.APPROVE)

    outcome = scenario["service"].apply(
        "task-1", "run-007", "approval-1"
    )

    assert outcome.next_action is (
        ContinuationNextAction.EXECUTE_PENDING_TOOL
    )
    assert outcome.tool_result.success is True
    assert outcome.tool_result.tool_call_id == "toolu_1"
    assert len(scenario["handler"].calls) == 1
    assert scenario["handler"].calls[0]["tool_input"] == {
        "path": "a.py",
        "content": SECRET,
    }


def test_modify_executes_only_replacement_input(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    modified_input = {"path": "sandbox/safe.py"}
    _resolve(
        scenario,
        ApprovalDecision.MODIFY,
        modified_input=modified_input,
    )

    outcome = scenario["service"].apply(
        "task-1", "run-007", "approval-1"
    )

    assert outcome.tool_result.success is True
    assert len(scenario["handler"].calls) == 1
    call = scenario["handler"].calls[0]
    assert call["tool_input"] == modified_input
    assert call["tool_call_id"] == "toolu_1"


def test_changed_authorization_prevents_handler_execution(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path, enabled_tools=set())
    _resolve(scenario, ApprovalDecision.APPROVE)

    outcome = scenario["service"].apply(
        "task-1", "run-007", "approval-1"
    )

    assert outcome.tool_result.success is False
    assert outcome.tool_result.error_code == "TOOL_DISABLED"
    assert scenario["handler"].calls == []


def test_reject_returns_rejection_without_executing_handler(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    _resolve(
        scenario, ApprovalDecision.REJECT, explanation="too risky"
    )

    outcome = scenario["service"].apply(
        "task-1", "run-007", "approval-1"
    )

    assert outcome.next_action is (
        ContinuationNextAction.REJECT_PENDING_TOOL
    )
    assert outcome.tool_result.success is False
    assert outcome.tool_result.tool_call_id == "toolu_1"
    assert outcome.tool_result.error_code == "APPROVAL_REJECTED"
    assert "too risky" not in outcome.tool_result.output
    assert scenario["handler"].calls == []


def test_cancel_returns_cancellation_without_executing_handler(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    _resolve(scenario, ApprovalDecision.CANCEL)

    outcome = scenario["service"].apply(
        "task-1", "run-007", "approval-1"
    )

    assert outcome.next_action is ContinuationNextAction.CANCEL_RUN
    assert outcome.tool_result is None
    assert scenario["handler"].calls == []


def test_three_call_round_only_pending_executes(
    tmp_path: Path,
) -> None:
    call_a = _tool_call(id_="toolu_a", name="write_file")
    call_b = _tool_call(id_="toolu_b", name="write_file")
    call_c = _tool_call(id_="toolu_c", name="write_file")
    result_a = ToolResult(
        tool_call_id="toolu_a",
        tool_name="write_file",
        success=True,
        output="already done",
    )
    scenario = _build_scenario(
        tmp_path,
        tool_calls=(call_a, call_b, call_c),
        pending_index=1,
        completed_results=(result_a,),
    )
    _resolve(scenario, ApprovalDecision.APPROVE)

    outcome = scenario["service"].apply(
        "task-1", "run-007", "approval-1"
    )

    assert outcome.tool_result.tool_call_id == "toolu_b"
    assert len(scenario["handler"].calls) == 1
    assert scenario["handler"].calls[0]["tool_call_id"] == "toolu_b"


# --- validation failures ------------------------------------------------


def test_missing_resolution_prevents_dispatch(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path)

    with pytest.raises(ApprovalResolutionPendingError):
        scenario["service"].apply("task-1", "run-007", "approval-1")

    assert scenario["handler"].calls == []


def test_mismatched_approval_id_prevents_dispatch(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    _resolve(scenario, ApprovalDecision.APPROVE)

    with pytest.raises(ApprovalApplicationMismatchError):
        scenario["service"].apply(
            "task-1", "run-007", "approval-unknown"
        )

    assert scenario["handler"].calls == []


def test_changed_run_state_prevents_dispatch(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path, run_status="completed")
    _resolve(scenario, ApprovalDecision.APPROVE)

    with pytest.raises(ApprovalRunNotWaitingForApprovalError):
        scenario["service"].apply("task-1", "run-007", "approval-1")

    assert scenario["handler"].calls == []


# --- claim / retry semantics --------------------------------------------


def test_retry_after_completion_returns_same_outcome_without_redispatch(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    _resolve(scenario, ApprovalDecision.APPROVE)
    first = scenario["service"].apply(
        "task-1", "run-007", "approval-1"
    )

    second = scenario["service"].apply(
        "task-1", "run-007", "approval-1"
    )

    assert second == first
    assert len(scenario["handler"].calls) == 1


def test_restart_rebuilt_objects_return_same_outcome(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    _resolve(scenario, ApprovalDecision.APPROVE)
    first = scenario["service"].apply(
        "task-1", "run-007", "approval-1"
    )
    tasks_dir = scenario["tasks_dir"]

    rebuilt_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    rebuilt_checkpoints = RunContinuationCheckpointRepository(tasks_dir)
    rebuilt_preparation_service = ApprovalContinuationPreparationService(
        RunRepository(tasks_dir), rebuilt_checkpoints, rebuilt_store
    )
    rebuilt_applications = ApprovalApplicationRepository(tasks_dir)
    new_handler = RecordingToolHandler()
    rebuilt_tool_executor = ToolExecutor(
        repository_root=tmp_path / "repo2",
        handlers=[new_handler],
        tool_policy=ToolPolicy(
            default="deny",
            tools={"write_file": ToolPolicyEntry(enabled=True)},
        ),
    )
    rebuilt_service = ApprovalApplicationService(
        rebuilt_preparation_service,
        rebuilt_applications,
        rebuilt_tool_executor,
    )

    second = rebuilt_service.apply("task-1", "run-007", "approval-1")

    assert second == first
    assert new_handler.calls == []


def test_incomplete_claim_blocks_dispatch_after_restart(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    _resolve(scenario, ApprovalDecision.APPROVE)

    # Simulate a crash right after claim creation: write a CLAIMED
    # record directly, bypassing the service entirely.
    from src.approval_application_record import (
        APPLICATION_RECORD_SCHEMA_VERSION,
        ApprovalApplicationRecord,
    )

    claim = ApprovalApplicationRecord(
        schema_version=APPLICATION_RECORD_SCHEMA_VERSION,
        approval_id="approval-1",
        task_id="task-1",
        run_id="run-007",
        pending_tool_call_id="toolu_1",
        decision=ApprovalDecision.APPROVE,
        next_action=ContinuationNextAction.EXECUTE_PENDING_TOOL,
        effective_input_digest="deadbeef",
        status=ApprovalApplicationStatus.CLAIMED,
    )
    scenario["applications"].create_exclusive(claim)

    with pytest.raises(ApprovalApplicationBlockedError):
        scenario["service"].apply("task-1", "run-007", "approval-1")

    assert scenario["handler"].calls == []


def test_handler_side_effect_not_repeated_after_outcome_save_failure(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(
        tmp_path,
        application_repository_cls=CompleteFailingRepository,
    )
    _resolve(scenario, ApprovalDecision.APPROVE)

    with pytest.raises(ApprovalApplicationPersistenceError):
        scenario["service"].apply("task-1", "run-007", "approval-1")

    assert len(scenario["handler"].calls) == 1

    stored = ApprovalApplicationRepository(
        scenario["tasks_dir"]
    ).try_load("approval-1")
    assert stored.status is ApprovalApplicationStatus.CLAIMED

    # Retry - on the same poisoned repository or a fresh plain one -
    # must not call the handler again.
    plain_repository = ApprovalApplicationRepository(
        scenario["tasks_dir"]
    )
    retry_service = ApprovalApplicationService(
        scenario["preparation_service"],
        plain_repository,
        scenario["tool_executor"],
    )

    with pytest.raises(ApprovalApplicationBlockedError):
        retry_service.apply("task-1", "run-007", "approval-1")

    assert len(scenario["handler"].calls) == 1


def test_claim_persistence_failure_prevents_handler_call(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(
        tmp_path,
        application_repository_cls=ClaimFailingRepository,
    )
    _resolve(scenario, ApprovalDecision.APPROVE)

    with pytest.raises(ApprovalApplicationPersistenceError):
        scenario["service"].apply("task-1", "run-007", "approval-1")

    assert scenario["handler"].calls == []


def test_dispatch_raising_preserves_claim_and_blocks_retry(
    tmp_path: Path,
) -> None:
    raising_executor = RaisingToolExecutor()
    scenario = _build_scenario(
        tmp_path, tool_executor_override=raising_executor
    )
    _resolve(scenario, ApprovalDecision.APPROVE)

    with pytest.raises(ApprovalApplicationDispatchError):
        scenario["service"].apply("task-1", "run-007", "approval-1")

    assert raising_executor.calls == 1

    stored = scenario["applications"].try_load("approval-1")
    assert stored.status is ApprovalApplicationStatus.CLAIMED

    with pytest.raises(ApprovalApplicationBlockedError):
        scenario["service"].apply("task-1", "run-007", "approval-1")

    assert raising_executor.calls == 1


def test_normal_tool_failure_is_saved_and_replayed_without_reexecution(
    tmp_path: Path,
) -> None:
    def _fail(tool_call_id: str, tool_input: dict) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name="write_file",
            success=False,
            output="disk full",
            error_code="WRITE_FAILED",
        )

    handler = RecordingToolHandler(on_execute=_fail)
    scenario = _build_scenario(tmp_path, handler=handler)
    _resolve(scenario, ApprovalDecision.APPROVE)

    first = scenario["service"].apply(
        "task-1", "run-007", "approval-1"
    )
    second = scenario["service"].apply(
        "task-1", "run-007", "approval-1"
    )

    assert first.tool_result.success is False
    assert first.tool_result.error_code == "WRITE_FAILED"
    assert second == first
    assert len(handler.calls) == 1


def test_approval_records_and_checkpoint_remain_unchanged(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    _resolve(scenario, ApprovalDecision.APPROVE)
    request_before = scenario["store"].get("approval-1")
    checkpoint_before = scenario["checkpoints"].load(
        "task-1", "run-007"
    )
    resolution_before = scenario["store"].get_resolution("approval-1")

    scenario["service"].apply("task-1", "run-007", "approval-1")

    assert scenario["store"].get("approval-1") == request_before
    assert (
        scenario["checkpoints"].load("task-1", "run-007")
        == checkpoint_before
    )
    assert (
        scenario["store"].get_resolution("approval-1")
        == resolution_before
    )


# --- concurrency ----------------------------------------------------------


def test_concurrent_apply_produces_exactly_one_dispatch(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    _resolve(scenario, ApprovalDecision.APPROVE)

    barrier = threading.Barrier(2)
    results: list[Any] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        try:
            outcome = scenario["service"].apply(
                "task-1", "run-007", "approval-1"
            )
            with lock:
                results.append(outcome)
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(scenario["handler"].calls) == 1
    assert len(results) + len(errors) == 2
    assert len(results) >= 1
    for error in errors:
        assert isinstance(error, ApprovalApplicationBlockedError)
    for outcome in results:
        assert outcome.tool_result.success is True


# --- secrecy --------------------------------------------------------------


def test_secret_absent_from_outcome_repr(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path)
    _resolve(scenario, ApprovalDecision.APPROVE)

    outcome = scenario["service"].apply(
        "task-1", "run-007", "approval-1"
    )

    assert SECRET not in repr(outcome)


def test_secret_absent_from_validation_errors(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path, run_status="completed")
    _resolve(scenario, ApprovalDecision.APPROVE)

    with pytest.raises(
        ApprovalRunNotWaitingForApprovalError
    ) as excinfo:
        scenario["service"].apply("task-1", "run-007", "approval-1")

    assert SECRET not in str(excinfo.value)


def test_secret_absent_from_events(tmp_path: Path) -> None:
    sink = InMemoryRunEventSink()
    scenario = _build_scenario(tmp_path, event_sink=sink)
    _resolve(scenario, ApprovalDecision.APPROVE)

    scenario["service"].apply("task-1", "run-007", "approval-1")

    applied_events = [
        event
        for event in sink.events
        if event["type"] == "approval_applied"
    ]
    assert len(applied_events) == 1
    for event in sink.events:
        assert SECRET not in repr(event)
        assert "output" not in event
        assert "tool_input" not in event
