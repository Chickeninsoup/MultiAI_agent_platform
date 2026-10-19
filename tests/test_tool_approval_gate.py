from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

from src.approval_errors import (
    DuplicateApprovalRequestError,
    InvalidApprovalIdError,
)
from src.approval_request import RiskLevel
from src.approval_request_repository import ApprovalRequestRepository
from src.approval_resolution_repository import (
    ApprovalResolutionRepository,
)
from src.approval_rule import ApprovalRule
from src.approval_store import ApprovalStore
from src.domain.tools.tool_call import ToolCall
from src.rule_based_tool_approval_policy import (
    RuleBasedToolApprovalPolicy,
)
from src.run_events import InMemoryRunEventSink
from src.tool_approval_gate import ToolApprovalGate
from src.tool_approval_gate_outcome import ToolApprovalGateOutcome


class _CountingPreviewer:
    def __init__(self, text: str = "generic preview") -> None:
        self.calls = 0
        self._text = text

    def preview(self, tool_call: ToolCall) -> str:
        self.calls += 1
        return self._text


class _EmptyPreviewer:
    def preview(self, tool_call: ToolCall) -> str:
        return "   "


class _RaisingPreviewer:
    def preview(self, tool_call: ToolCall) -> str:
        raise RuntimeError("previewer exploded")


class _CountingIdFactory:
    def __init__(self) -> None:
        self.calls = 0
        self.received: list[tuple[str, ToolCall]] = []

    def __call__(self, run_id: str, tool_call: ToolCall) -> str:
        self.calls += 1
        self.received.append((run_id, tool_call))
        return f"approval-{run_id}-{tool_call.id}"


def _raising_id_factory(run_id: str, tool_call: ToolCall) -> str:
    raise RuntimeError("id factory exploded")


def _fixed_id_factory(fixed_id: str):
    def factory(run_id: str, tool_call: ToolCall) -> str:
        return fixed_id

    return factory


def _policy_requiring(tool_name: str) -> RuleBasedToolApprovalPolicy:
    return RuleBasedToolApprovalPolicy(
        [
            ApprovalRule(
                tool_name=tool_name,
                risk_level=RiskLevel.MEDIUM,
                reason="writes files outside the sandbox",
            )
        ]
    )


def _tool_call(
    name: str = "write_file",
    id_: str = "toolu_1",
    input_: dict | None = None,
) -> ToolCall:
    return ToolCall(
        id=id_, name=name, input=input_ or {"path": "a.py"}
    )


def _gate(
    tmp_path: Path,
    *,
    policy=None,
    previewer=None,
    approval_id_factory=None,
    event_sink=None,
) -> ToolApprovalGate:
    store = ApprovalStore(
        ApprovalRequestRepository(tmp_path),
        ApprovalResolutionRepository(tmp_path),
        event_sink=event_sink,
    )

    return ToolApprovalGate(
        policy if policy is not None else _policy_requiring("write_file"),
        previewer if previewer is not None else _CountingPreviewer(),
        store,
        approval_id_factory,
    )


# --- PROCEED branch -----------------------------------------------------


def test_unconfigured_tool_returns_proceed(tmp_path: Path) -> None:
    gate = _gate(tmp_path)

    result = gate.check("run-007", _tool_call(name="read_file"))

    assert result.outcome is ToolApprovalGateOutcome.PROCEED


def test_proceed_result_contains_no_request(tmp_path: Path) -> None:
    gate = _gate(tmp_path)

    result = gate.check("run-007", _tool_call(name="read_file"))

    assert result.approval_request is None


def test_proceed_branch_never_calls_previewer_id_factory_or_store(
    tmp_path: Path,
) -> None:
    previewer = _CountingPreviewer()
    id_factory = _CountingIdFactory()
    sink = InMemoryRunEventSink()
    gate = _gate(
        tmp_path,
        previewer=previewer,
        approval_id_factory=id_factory,
        event_sink=sink,
    )

    gate.check("run-007", _tool_call(name="read_file"))

    assert previewer.calls == 0
    assert id_factory.calls == 0
    assert sink.events == []
    assert ApprovalRequestRepository(tmp_path).list_all() == []


# --- WAITING_FOR_APPROVAL branch ----------------------------------------


def test_configured_tool_creates_exactly_one_request(
    tmp_path: Path,
) -> None:
    gate = _gate(tmp_path)

    gate.check("run-007", _tool_call())

    assert len(ApprovalRequestRepository(tmp_path).list_all()) == 1


def test_policy_risk_level_and_reason_are_copied(tmp_path: Path) -> None:
    policy = RuleBasedToolApprovalPolicy(
        [
            ApprovalRule(
                tool_name="write_file",
                risk_level=RiskLevel.HIGH,
                reason="overwrites production config",
            )
        ]
    )
    gate = _gate(tmp_path, policy=policy)

    result = gate.check("run-007", _tool_call())

    assert result.approval_request.risk_level is RiskLevel.HIGH
    assert (
        result.approval_request.reason
        == "overwrites production config"
    )


def test_original_tool_call_is_preserved(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    tool_call = _tool_call(input_={"path": "a.py", "content": "x"})

    result = gate.check("run-007", tool_call)

    assert result.approval_request.proposed_action == tool_call


def test_preview_comes_only_from_the_previewer(tmp_path: Path) -> None:
    previewer = _CountingPreviewer(text="a distinctive preview string")
    gate = _gate(tmp_path, previewer=previewer)

    result = gate.check("run-007", _tool_call())

    assert previewer.calls == 1
    assert (
        result.approval_request.input_preview
        == "a distinctive preview string"
    )


def test_waiting_result_contains_the_persisted_request(
    tmp_path: Path,
) -> None:
    gate = _gate(tmp_path)

    result = gate.check("run-007", _tool_call())

    stored = ApprovalRequestRepository(tmp_path).load(
        result.approval_request.approval_id
    )
    assert stored == result.approval_request


def test_waiting_outcome_and_invariants_hold(tmp_path: Path) -> None:
    gate = _gate(tmp_path)

    result = gate.check("run-007", _tool_call())

    assert (
        result.outcome is ToolApprovalGateOutcome.WAITING_FOR_APPROVAL
    )
    assert result.approval_request is not None


# --- validation failures -------------------------------------------------


def test_empty_run_id_is_rejected_before_collaborators_are_called(
    tmp_path: Path,
) -> None:
    previewer = _CountingPreviewer()
    id_factory = _CountingIdFactory()
    gate = _gate(
        tmp_path, previewer=previewer, approval_id_factory=id_factory
    )

    with pytest.raises(ValueError):
        gate.check("", _tool_call())

    assert previewer.calls == 0
    assert id_factory.calls == 0
    assert ApprovalRequestRepository(tmp_path).list_all() == []


def test_whitespace_only_run_id_is_rejected(tmp_path: Path) -> None:
    gate = _gate(tmp_path)

    with pytest.raises(ValueError):
        gate.check("   ", _tool_call())


def test_empty_preview_is_rejected_before_store_mutation(
    tmp_path: Path,
) -> None:
    gate = _gate(tmp_path, previewer=_EmptyPreviewer())

    with pytest.raises(ValueError):
        gate.check("run-007", _tool_call())

    assert ApprovalRequestRepository(tmp_path).list_all() == []


def test_id_factory_failure_leaves_store_unchanged(
    tmp_path: Path,
) -> None:
    gate = _gate(tmp_path, approval_id_factory=_raising_id_factory)

    with pytest.raises(RuntimeError):
        gate.check("run-007", _tool_call())

    assert ApprovalRequestRepository(tmp_path).list_all() == []


def test_previewer_failure_leaves_store_unchanged(
    tmp_path: Path,
) -> None:
    gate = _gate(tmp_path, previewer=_RaisingPreviewer())

    with pytest.raises(RuntimeError):
        gate.check("run-007", _tool_call())

    assert ApprovalRequestRepository(tmp_path).list_all() == []


def test_store_failure_propagates(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    tool_call = _tool_call()

    gate.check("run-007", tool_call)

    with pytest.raises(DuplicateApprovalRequestError):
        gate.check("run-007", tool_call)


# --- security / side-effect boundaries ------------------------------------


def test_tool_call_is_not_mutated_by_check(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    tool_call = _tool_call()
    original = copy.deepcopy(tool_call)

    gate.check("run-007", tool_call)

    assert tool_call == original


def test_planted_secret_is_absent_from_the_preview(
    tmp_path: Path,
) -> None:
    previewer = _CountingPreviewer(text="write a file")
    gate = _gate(tmp_path, previewer=previewer)
    tool_call = _tool_call(
        input_={"path": "a.py", "content": "super-secret-token"}
    )

    result = gate.check("run-007", tool_call)

    assert "super-secret-token" not in result.approval_request.input_preview


def test_planted_secret_is_absent_from_approval_request_repr(
    tmp_path: Path,
) -> None:
    previewer = _CountingPreviewer(text="write a file")
    gate = _gate(tmp_path, previewer=previewer)
    tool_call = _tool_call(
        input_={"path": "a.py", "content": "super-secret-token"}
    )

    result = gate.check("run-007", tool_call)

    assert "super-secret-token" not in repr(result.approval_request)


def test_planted_secret_is_absent_from_gate_result_repr(
    tmp_path: Path,
) -> None:
    previewer = _CountingPreviewer(text="write a file")
    gate = _gate(tmp_path, previewer=previewer)
    tool_call = _tool_call(
        input_={"path": "a.py", "content": "super-secret-token"}
    )

    result = gate.check("run-007", tool_call)

    assert "super-secret-token" not in repr(result)


_APPROVAL_ID_FORMAT = re.compile(r"^approval-[0-9a-f]{64}$")


def test_default_id_derivation_is_deterministic_across_gates(
    tmp_path: Path,
) -> None:
    tool_call = _tool_call(id_="toolu_shared")
    gate_a = _gate(tmp_path / "store-a")
    gate_b = _gate(tmp_path / "store-b")

    result_a = gate_a.check("run-007", tool_call)
    result_b = gate_b.check("run-007", tool_call)

    assert (
        result_a.approval_request.approval_id
        == result_b.approval_request.approval_id
    )


def test_different_run_ids_with_the_same_tool_call_id_differ(
    tmp_path: Path,
) -> None:
    tool_call = _tool_call(id_="toolu_shared")
    gate_a = _gate(tmp_path / "store-a")
    gate_b = _gate(tmp_path / "store-b")

    result_a = gate_a.check("run-001", tool_call)
    result_b = gate_b.check("run-002", tool_call)

    assert (
        result_a.approval_request.approval_id
        != result_b.approval_request.approval_id
    )


def test_different_tool_call_ids_in_the_same_run_differ(
    tmp_path: Path,
) -> None:
    gate = _gate(tmp_path)

    result_a = gate.check("run-007", _tool_call(id_="toolu_a"))
    result_b = gate.check("run-007", _tool_call(id_="toolu_b"))

    assert (
        result_a.approval_request.approval_id
        != result_b.approval_request.approval_id
    )


def test_default_approval_id_matches_the_safe_character_format(
    tmp_path: Path,
) -> None:
    gate = _gate(tmp_path)

    result = gate.check("run-007", _tool_call())

    assert _APPROVAL_ID_FORMAT.fullmatch(
        result.approval_request.approval_id
    )


def test_injected_id_factory_receives_run_id_and_tool_call(
    tmp_path: Path,
) -> None:
    id_factory = _CountingIdFactory()
    gate = _gate(tmp_path, approval_id_factory=id_factory)
    tool_call = _tool_call()

    gate.check("run-007", tool_call)

    assert id_factory.received == [("run-007", tool_call)]


@pytest.mark.parametrize(
    "unsafe_id",
    [
        "",
        "   ",
        "../outside",
        "../../task",
        "/absolute/path",
        "a/b",
        "a\\b",
        ".",
        "..",
    ],
)
def test_injected_unsafe_id_is_rejected_before_store_mutation(
    tmp_path: Path, unsafe_id: str
) -> None:
    gate = _gate(
        tmp_path, approval_id_factory=_fixed_id_factory(unsafe_id)
    )

    with pytest.raises((ValueError, InvalidApprovalIdError)):
        gate.check("run-007", _tool_call())

    assert list(tmp_path.iterdir()) == []
