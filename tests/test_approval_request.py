from __future__ import annotations

import dataclasses

import pytest

from src.approval_request import ApprovalRequest, RiskLevel
from src.approval_status import ApprovalStatus
from src.domain.tools.tool_call import ToolCall


def _tool_call() -> ToolCall:
    return ToolCall(
        id="toolu_1",
        name="write_file",
        input={"path": "sandbox/hello.py", "content": "print('hi')"},
    )


def _request(**overrides: object) -> ApprovalRequest:
    defaults: dict[str, object] = {
        "approval_id": "approval-1",
        "run_id": "run-007",
        "proposed_action": _tool_call(),
        "reason": "write_file targets a path outside the sandbox",
        "risk_level": RiskLevel.MEDIUM,
        "input_preview": "write sandbox/hello.py (44 bytes)",
    }
    defaults.update(overrides)

    return ApprovalRequest(**defaults)  # type: ignore[arg-type]


def test_basic_construction() -> None:
    action = _tool_call()
    request = _request(proposed_action=action)

    assert request.approval_id == "approval-1"
    assert request.run_id == "run-007"
    assert request.proposed_action is action
    assert request.reason == "write_file targets a path outside the sandbox"
    assert request.risk_level is RiskLevel.MEDIUM
    assert request.input_preview == "write sandbox/hello.py (44 bytes)"


def test_status_defaults_to_pending() -> None:
    request = _request()

    assert request.status is ApprovalStatus.PENDING


def test_created_at_defaults_to_a_non_empty_string() -> None:
    request = _request()

    assert isinstance(request.created_at, str)
    assert request.created_at != ""


def test_request_is_immutable() -> None:
    request = _request()

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.status = ApprovalStatus.RESOLVED  # type: ignore[misc]


@pytest.mark.parametrize(
    "field_name",
    ["approval_id", "run_id", "reason", "input_preview"],
)
def test_empty_required_string_fields_are_rejected(
    field_name: str,
) -> None:
    with pytest.raises(ValueError):
        _request(**{field_name: ""})


@pytest.mark.parametrize(
    "field_name",
    ["approval_id", "run_id", "reason", "input_preview"],
)
def test_whitespace_only_required_string_fields_are_rejected(
    field_name: str,
) -> None:
    with pytest.raises(ValueError):
        _request(**{field_name: "   "})


def test_all_three_risk_levels_exist() -> None:
    assert RiskLevel.LOW
    assert RiskLevel.MEDIUM
    assert RiskLevel.HIGH


def test_risk_levels_are_distinct() -> None:
    assert len(set(RiskLevel)) == 3


def test_to_dict_and_from_dict_roundtrip() -> None:
    request = _request(created_at="2026-01-01T00:00:00Z")

    assert ApprovalRequest.from_dict(request.to_dict()) == request


def test_to_dict_and_from_dict_roundtrip_when_resolved() -> None:
    request = _request(
        created_at="2026-01-01T00:00:00Z",
        status=ApprovalStatus.RESOLVED,
    )

    assert ApprovalRequest.from_dict(request.to_dict()) == request


def test_proposed_action_is_preserved_in_full() -> None:
    action = _tool_call()
    request = _request(proposed_action=action)

    assert request.proposed_action.id == "toolu_1"
    assert request.proposed_action.name == "write_file"
    assert request.proposed_action.input == {
        "path": "sandbox/hello.py",
        "content": "print('hi')",
    }


def test_repr_excludes_proposed_action() -> None:
    secret_call = ToolCall(
        id="toolu_2",
        name="write_file",
        input={"path": "a.py", "content": "super-secret-token"},
    )
    request = _request(proposed_action=secret_call)

    serialized = repr(request)

    assert "proposed_action" not in serialized
    assert "super-secret-token" not in serialized


def test_repr_still_shows_safe_metadata() -> None:
    request = _request()

    serialized = repr(request)

    assert "approval-1" in serialized
    assert "run-007" in serialized
    assert "write sandbox/hello.py (44 bytes)" in serialized


def test_persistence_still_retains_the_real_proposed_action_input() -> (
    None
):
    secret_call = ToolCall(
        id="toolu_2",
        name="write_file",
        input={"path": "a.py", "content": "super-secret-token"},
    )
    request = _request(proposed_action=secret_call)

    round_tripped = ApprovalRequest.from_dict(request.to_dict())

    assert round_tripped.proposed_action.input == {
        "path": "a.py",
        "content": "super-secret-token",
    }
    assert request.to_dict()["proposed_action"]["input"] == {
        "path": "a.py",
        "content": "super-secret-token",
    }
