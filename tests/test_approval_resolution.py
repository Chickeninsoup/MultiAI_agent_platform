from __future__ import annotations

import dataclasses

import pytest

from src.approval_decision import ApprovalDecision
from src.approval_resolution import ApprovalResolution


def test_approve_can_be_constructed_without_modified_input() -> None:
    resolution = ApprovalResolution(
        approval_id="approval-1",
        decision=ApprovalDecision.APPROVE,
    )

    assert resolution.decision is ApprovalDecision.APPROVE
    assert resolution.modified_input is None


def test_reject_can_be_constructed_without_modified_input() -> None:
    resolution = ApprovalResolution(
        approval_id="approval-1",
        decision=ApprovalDecision.REJECT,
        explanation="destructive and unnecessary",
    )

    assert resolution.decision is ApprovalDecision.REJECT
    assert resolution.modified_input is None
    assert resolution.explanation == "destructive and unnecessary"


def test_cancel_can_be_constructed_without_modified_input() -> None:
    resolution = ApprovalResolution(
        approval_id="approval-1",
        decision=ApprovalDecision.CANCEL,
    )

    assert resolution.decision is ApprovalDecision.CANCEL
    assert resolution.modified_input is None


def test_modify_can_be_constructed_with_modified_input() -> None:
    resolution = ApprovalResolution(
        approval_id="approval-1",
        decision=ApprovalDecision.MODIFY,
        modified_input={"path": "sandbox/hello.py", "content": "safe"},
    )

    assert resolution.decision is ApprovalDecision.MODIFY
    assert resolution.modified_input == {
        "path": "sandbox/hello.py",
        "content": "safe",
    }


def test_modify_without_modified_input_is_rejected() -> None:
    with pytest.raises(ValueError):
        ApprovalResolution(
            approval_id="approval-1",
            decision=ApprovalDecision.MODIFY,
        )


@pytest.mark.parametrize(
    "decision",
    [
        ApprovalDecision.APPROVE,
        ApprovalDecision.REJECT,
        ApprovalDecision.CANCEL,
    ],
)
def test_non_modify_decisions_with_modified_input_are_rejected(
    decision: ApprovalDecision,
) -> None:
    with pytest.raises(ValueError):
        ApprovalResolution(
            approval_id="approval-1",
            decision=decision,
            modified_input={"path": "sandbox/hello.py"},
        )


def test_empty_approval_id_is_rejected() -> None:
    with pytest.raises(ValueError):
        ApprovalResolution(
            approval_id="",
            decision=ApprovalDecision.APPROVE,
        )


def test_whitespace_only_approval_id_is_rejected() -> None:
    with pytest.raises(ValueError):
        ApprovalResolution(
            approval_id="   ",
            decision=ApprovalDecision.APPROVE,
        )


def test_empty_explanation_is_rejected_when_provided() -> None:
    with pytest.raises(ValueError):
        ApprovalResolution(
            approval_id="approval-1",
            decision=ApprovalDecision.APPROVE,
            explanation="",
        )


def test_explanation_defaults_to_none() -> None:
    resolution = ApprovalResolution(
        approval_id="approval-1",
        decision=ApprovalDecision.APPROVE,
    )

    assert resolution.explanation is None


def test_resolved_at_defaults_to_a_non_empty_string() -> None:
    resolution = ApprovalResolution(
        approval_id="approval-1",
        decision=ApprovalDecision.APPROVE,
    )

    assert isinstance(resolution.resolved_at, str)
    assert resolution.resolved_at != ""


def test_resolution_is_immutable() -> None:
    resolution = ApprovalResolution(
        approval_id="approval-1",
        decision=ApprovalDecision.APPROVE,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        resolution.decision = ApprovalDecision.REJECT  # type: ignore[misc]


def test_to_dict_and_from_dict_roundtrip_for_approve() -> None:
    resolution = ApprovalResolution(
        approval_id="approval-1",
        decision=ApprovalDecision.APPROVE,
        resolved_at="2026-01-01T00:00:00Z",
    )

    assert ApprovalResolution.from_dict(resolution.to_dict()) == resolution


def test_to_dict_and_from_dict_roundtrip_for_modify() -> None:
    resolution = ApprovalResolution(
        approval_id="approval-1",
        decision=ApprovalDecision.MODIFY,
        modified_input={"path": "sandbox/hello.py", "content": "safe"},
        explanation="redirected to a safe path",
        resolved_at="2026-01-01T00:00:00Z",
    )

    assert ApprovalResolution.from_dict(resolution.to_dict()) == resolution


def test_repr_excludes_modified_input() -> None:
    resolution = ApprovalResolution(
        approval_id="approval-1",
        decision=ApprovalDecision.MODIFY,
        modified_input={"path": "a.py", "content": "another-secret"},
    )

    serialized = repr(resolution)

    assert "modified_input" not in serialized
    assert "another-secret" not in serialized


def test_repr_still_shows_safe_metadata() -> None:
    resolution = ApprovalResolution(
        approval_id="approval-1",
        decision=ApprovalDecision.REJECT,
        explanation="too risky",
    )

    serialized = repr(resolution)

    assert "approval-1" in serialized
    assert "REJECT" in serialized
    assert "too risky" in serialized


def test_persistence_still_retains_the_real_modified_input() -> None:
    resolution = ApprovalResolution(
        approval_id="approval-1",
        decision=ApprovalDecision.MODIFY,
        modified_input={"path": "a.py", "content": "another-secret"},
    )

    round_tripped = ApprovalResolution.from_dict(resolution.to_dict())

    assert round_tripped.modified_input == {
        "path": "a.py",
        "content": "another-secret",
    }
    assert resolution.to_dict()["modified_input"] == {
        "path": "a.py",
        "content": "another-secret",
    }
