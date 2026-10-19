from __future__ import annotations

import dataclasses

import pytest

from src.approval_request import ApprovalRequest, RiskLevel
from src.domain.tools.tool_call import ToolCall
from src.tool_approval_gate_outcome import ToolApprovalGateOutcome
from src.tool_approval_gate_result import ToolApprovalGateResult


def _request() -> ApprovalRequest:
    return ApprovalRequest(
        approval_id="approval-toolu_1",
        run_id="run-007",
        proposed_action=ToolCall(
            id="toolu_1", name="write_file", input={"path": "a.py"}
        ),
        reason="writes files outside the sandbox",
        risk_level=RiskLevel.MEDIUM,
        input_preview="write a.py",
    )


def test_proceed_without_a_request() -> None:
    result = ToolApprovalGateResult(
        outcome=ToolApprovalGateOutcome.PROCEED
    )

    assert result.outcome is ToolApprovalGateOutcome.PROCEED
    assert result.approval_request is None


def test_waiting_with_a_request() -> None:
    request = _request()
    result = ToolApprovalGateResult(
        outcome=ToolApprovalGateOutcome.WAITING_FOR_APPROVAL,
        approval_request=request,
    )

    assert (
        result.outcome is ToolApprovalGateOutcome.WAITING_FOR_APPROVAL
    )
    assert result.approval_request is request


def test_waiting_without_a_request_is_rejected() -> None:
    with pytest.raises(ValueError):
        ToolApprovalGateResult(
            outcome=ToolApprovalGateOutcome.WAITING_FOR_APPROVAL,
        )


def test_proceed_with_a_request_is_rejected() -> None:
    with pytest.raises(ValueError):
        ToolApprovalGateResult(
            outcome=ToolApprovalGateOutcome.PROCEED,
            approval_request=_request(),
        )


def test_result_is_frozen() -> None:
    result = ToolApprovalGateResult(
        outcome=ToolApprovalGateOutcome.PROCEED
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.outcome = (  # type: ignore[misc]
            ToolApprovalGateOutcome.WAITING_FOR_APPROVAL
        )

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.approval_request = _request()  # type: ignore[misc]
