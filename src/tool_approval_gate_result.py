from __future__ import annotations

from dataclasses import dataclass

from src.approval_request import ApprovalRequest
from src.tool_approval_gate_outcome import ToolApprovalGateOutcome


@dataclass(frozen=True)
class ToolApprovalGateResult:
    """The outcome of ToolApprovalGate.check() for one ToolCall
    (5E-5D-4A).

    Frozen, matching every persisted-or-passed-around approval domain
    value object (ApprovalRequest, ApprovalResolution, ApprovalRule) -
    unlike ToolApprovalPolicyResult before 5E-5D-3A, there was never a
    "plain, inspect-and-discard" argument to make for this one: this
    result carries an ApprovalRequest that may already be persisted in
    ApprovalStore, so silently mutating a caller's copy of it could
    make in-memory state disagree with what's on disk.

    Deliberately carries only outcome + approval_request - no separate
    raw-input field of its own. When outcome is WAITING_FOR_APPROVAL,
    the real ToolCall (including its raw input) is already reachable
    via approval_request.proposed_action, exactly as ApprovalRequest
    was designed in 5E-5D-1 (proposed_action carries the real input
    because whatever executes it after approval needs it;
    input_preview is the separate, human-safe summary). Adding a
    second raw-input field here would just duplicate that, not add
    anything - so no such field exists.
    """

    outcome: ToolApprovalGateOutcome
    approval_request: ApprovalRequest | None = None

    def __post_init__(self) -> None:
        if self.outcome is ToolApprovalGateOutcome.WAITING_FOR_APPROVAL:
            if self.approval_request is None:
                raise ValueError(
                    "ToolApprovalGateResult requires approval_request "
                    "when outcome is WAITING_FOR_APPROVAL"
                )
        else:
            if self.approval_request is not None:
                raise ValueError(
                    "ToolApprovalGateResult must not carry "
                    "approval_request when outcome is PROCEED"
                )
