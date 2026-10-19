from __future__ import annotations

from pathlib import Path

import pytest

from src.approval_decision import ApprovalDecision
from src.approval_errors import (
    ApprovalAlreadyResolvedError,
    ApprovalRequestNotFoundError,
    DuplicateApprovalRequestError,
    InvalidApprovalIdError,
    MismatchedApprovalResolutionError,
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
from src.run_events import InMemoryRunEventSink


def _request(
    approval_id: str = "approval-1", run_id: str = "run-007"
) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=approval_id,
        run_id=run_id,
        proposed_action=ToolCall(
            id="toolu_1",
            name="write_file",
            input={"path": "sandbox/hello.py", "content": "secret-token"},
        ),
        reason="write_file targets a path outside the sandbox",
        risk_level=RiskLevel.MEDIUM,
        input_preview="write sandbox/hello.py (12 bytes)",
        created_at="2026-01-01T00:00:00Z",
    )


def _store(
    tmp_path: Path, event_sink: InMemoryRunEventSink | None = None
) -> ApprovalStore:
    return ApprovalStore(
        ApprovalRequestRepository(tmp_path),
        ApprovalResolutionRepository(tmp_path),
        event_sink=event_sink,
    )


# --- create / get -----------------------------------------------------


def test_create_and_get_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    request = _request()

    created = store.create(request)

    assert created == request
    assert store.get("approval-1") == request


def test_persistence_survives_store_reinstantiation(
    tmp_path: Path,
) -> None:
    _store(tmp_path).create(_request())

    reloaded_store = _store(tmp_path)

    assert reloaded_store.get("approval-1") == _request()


def test_get_unknown_approval_id_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ApprovalRequestNotFoundError):
        store.get("unknown")


def test_duplicate_create_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_request())

    with pytest.raises(DuplicateApprovalRequestError):
        store.create(_request())


def test_duplicate_create_does_not_overwrite_the_original(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.create(_request())

    conflicting = ApprovalRequest(
        approval_id="approval-1",
        run_id="run-999",
        proposed_action=ToolCall(
            id="toolu_2", name="patch_file", input={}
        ),
        reason="a different reason",
        risk_level=RiskLevel.HIGH,
        input_preview="a different preview",
    )

    with pytest.raises(DuplicateApprovalRequestError):
        store.create(conflicting)

    assert store.get("approval-1").reason == (
        "write_file targets a path outside the sandbox"
    )


# --- listing ------------------------------------------------------------


def test_list_pending_is_empty_for_a_fresh_store(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert store.list_pending() == []


def test_list_pending_returns_unresolved_requests(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.create(_request("approval-1"))
    store.create(_request("approval-2"))

    store.resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.APPROVE
        ),
    )

    pending = store.list_pending()

    assert [request.approval_id for request in pending] == [
        "approval-2"
    ]


def test_list_pending_can_filter_by_run_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_request("approval-1", run_id="run-001"))
    store.create(_request("approval-2", run_id="run-002"))

    pending = store.list_pending(run_id="run-001")

    assert [request.approval_id for request in pending] == [
        "approval-1"
    ]


# --- resolve --------------------------------------------------------------


def test_resolving_a_pending_request_succeeds(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_request())
    resolution = ApprovalResolution(
        approval_id="approval-1", decision=ApprovalDecision.APPROVE
    )

    result = store.resolve("approval-1", resolution)

    assert result == resolution


def test_resolved_status_is_projected_on_get(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_request())

    assert store.get("approval-1").status is ApprovalStatus.PENDING

    store.resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.REJECT
        ),
    )

    assert store.get("approval-1").status is ApprovalStatus.RESOLVED


def test_resolving_does_not_rewrite_the_stored_request(
    tmp_path: Path,
) -> None:
    request_repository = ApprovalRequestRepository(tmp_path)
    store = ApprovalStore(
        request_repository, ApprovalResolutionRepository(tmp_path)
    )
    store.create(_request())

    store.resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.APPROVE
        ),
    )

    raw_stored_request = request_repository.load("approval-1")
    assert raw_stored_request.status is ApprovalStatus.PENDING


def test_get_resolution_returns_none_before_resolution(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.create(_request())

    assert store.get_resolution("approval-1") is None


def test_get_resolution_returns_the_saved_resolution(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.create(_request())
    resolution = ApprovalResolution(
        approval_id="approval-1",
        decision=ApprovalDecision.MODIFY,
        modified_input={"path": "sandbox/safe.py"},
    )

    store.resolve("approval-1", resolution)

    assert store.get_resolution("approval-1") == resolution


def test_resolving_unknown_approval_id_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ApprovalRequestNotFoundError):
        store.resolve(
            "unknown",
            ApprovalResolution(
                approval_id="unknown", decision=ApprovalDecision.APPROVE
            ),
        )


def test_mismatched_resolution_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_request("approval-1"))

    mismatched = ApprovalResolution(
        approval_id="approval-2", decision=ApprovalDecision.APPROVE
    )

    with pytest.raises(MismatchedApprovalResolutionError):
        store.resolve("approval-1", mismatched)


def test_double_resolution_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_request())
    store.resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.APPROVE
        ),
    )

    with pytest.raises(ApprovalAlreadyResolvedError):
        store.resolve(
            "approval-1",
            ApprovalResolution(
                approval_id="approval-1",
                decision=ApprovalDecision.REJECT,
            ),
        )


def test_failed_resolution_leaves_state_unchanged(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.create(_request())
    original = ApprovalResolution(
        approval_id="approval-1", decision=ApprovalDecision.APPROVE
    )
    store.resolve("approval-1", original)

    with pytest.raises(ApprovalAlreadyResolvedError):
        store.resolve(
            "approval-1",
            ApprovalResolution(
                approval_id="approval-1",
                decision=ApprovalDecision.REJECT,
            ),
        )

    assert store.get_resolution("approval-1") == original
    assert store.get("approval-1").status is ApprovalStatus.RESOLVED


# --- audit events -----------------------------------------------------


def test_create_emits_approval_requested_event(tmp_path: Path) -> None:
    sink = InMemoryRunEventSink()
    store = _store(tmp_path, event_sink=sink)

    store.create(_request())

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event["type"] == "approval_requested"
    assert event["approval_id"] == "approval-1"
    assert event["run_id"] == "run-007"
    assert event["tool_name"] == "write_file"
    assert event["reason"] == (
        "write_file targets a path outside the sandbox"
    )
    assert event["risk_level"] == "medium"
    assert event["input_preview"] == "write sandbox/hello.py (12 bytes)"
    assert event["created_at"] == "2026-01-01T00:00:00Z"


def test_resolve_emits_approval_resolved_event(tmp_path: Path) -> None:
    sink = InMemoryRunEventSink()
    store = _store(tmp_path, event_sink=sink)
    store.create(_request())

    store.resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1",
            decision=ApprovalDecision.MODIFY,
            modified_input={"path": "sandbox/safe.py"},
            explanation="redirected to a safe path",
            resolved_at="2026-01-02T00:00:00Z",
        ),
    )

    resolved_events = [
        event
        for event in sink.events
        if event["type"] == "approval_resolved"
    ]
    assert len(resolved_events) == 1
    event = resolved_events[0]
    assert event["approval_id"] == "approval-1"
    assert event["run_id"] == "run-007"
    assert event["decision"] == "modify"
    assert event["input_modified"] is True
    assert event["explanation"] == "redirected to a safe path"
    assert event["resolved_at"] == "2026-01-02T00:00:00Z"


def test_requested_event_does_not_include_raw_proposed_input(
    tmp_path: Path,
) -> None:
    sink = InMemoryRunEventSink()
    store = _store(tmp_path, event_sink=sink)

    store.create(_request())

    event = sink.events[0]
    assert "input" not in event
    assert "proposed_action" not in event
    serialized = repr(event)
    assert "secret-token" not in serialized


def test_resolved_event_does_not_include_raw_modified_input(
    tmp_path: Path,
) -> None:
    sink = InMemoryRunEventSink()
    store = _store(tmp_path, event_sink=sink)
    store.create(_request())

    store.resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1",
            decision=ApprovalDecision.MODIFY,
            modified_input={"token": "another-secret"},
        ),
    )

    resolved_event = sink.events[-1]
    assert "modified_input" not in resolved_event
    serialized = repr(resolved_event)
    assert "another-secret" not in serialized


def test_failed_create_does_not_emit_an_event(tmp_path: Path) -> None:
    sink = InMemoryRunEventSink()
    store = _store(tmp_path, event_sink=sink)
    store.create(_request())
    sink.events.clear()

    with pytest.raises(DuplicateApprovalRequestError):
        store.create(_request())

    assert sink.events == []


def test_default_event_sink_drops_events_silently(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    store.create(_request())
    store.resolve(
        "approval-1",
        ApprovalResolution(
            approval_id="approval-1", decision=ApprovalDecision.APPROVE
        ),
    )


# --- path-traversal protection (5E-5D-4A-1) ------------------------------


@pytest.mark.parametrize(
    "unsafe_id",
    ["../outside", "../../task", "/absolute/path", "a/b", "..", "."],
)
def test_create_rejects_unsafe_approval_id(
    tmp_path: Path, unsafe_id: str
) -> None:
    store = _store(tmp_path)

    with pytest.raises(InvalidApprovalIdError):
        store.create(_request(unsafe_id))

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "unsafe_id",
    ["../outside", "../../task", "/absolute/path", "a/b", "..", "."],
)
def test_get_rejects_unsafe_approval_id(
    tmp_path: Path, unsafe_id: str
) -> None:
    store = _store(tmp_path)

    with pytest.raises(InvalidApprovalIdError):
        store.get(unsafe_id)


@pytest.mark.parametrize(
    "unsafe_id",
    ["../outside", "../../task", "/absolute/path", "a/b", "..", "."],
)
def test_resolve_rejects_unsafe_approval_id_and_mutates_nothing(
    tmp_path: Path, unsafe_id: str
) -> None:
    store = _store(tmp_path)

    with pytest.raises(InvalidApprovalIdError):
        store.resolve(
            unsafe_id,
            ApprovalResolution(
                approval_id=unsafe_id, decision=ApprovalDecision.APPROVE
            ),
        )

    assert list(tmp_path.iterdir()) == []
