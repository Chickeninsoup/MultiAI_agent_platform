from __future__ import annotations

from dataclasses import dataclass

from src.approval_request import RiskLevel
from src.tool_approval_requirement import ToolApprovalRequirement


@dataclass(frozen=True)
class ToolApprovalPolicyResult:
    """The outcome of evaluating one ToolCall against a
    ToolApprovalPolicy (5E-5D-3, frozen in 5E-5D-3A).

    Frozen, matching ApprovalRule and every other approval domain
    value object (ApprovalRequest, ApprovalResolution): a security-
    relevant classification - whether a ToolCall needs a human's
    blessing, at what risk, and why - must not be mutable after
    construction. A mutable result could be silently downgraded from
    REQUIRES_APPROVAL to DOES_NOT_REQUIRE_APPROVAL (or have its
    risk_level/reason edited) by any code holding a reference to it,
    after __post_init__ already validated the object it was handed -
    __post_init__ only ever runs once, at construction, so a plain
    dataclass's invariants protect nothing after that point. Freezing
    closes that gap the same way it already does for every other
    domain type in src/ that callers are expected to trust.

    risk_level/reason are only meaningful alongside REQUIRES_APPROVAL
    - see __post_init__. Deliberately excludes the ToolCall's input:
    this result exists to answer "does this need approval, at what
    risk, and why," not to carry a redacted/previewable copy of what
    was called with - building an input preview belongs to whatever
    later stage turns this into an ApprovalRequest (src/approval_request.py
    already has its own input_preview field for exactly that), not to
    this policy layer.
    """

    requirement: ToolApprovalRequirement
    risk_level: RiskLevel | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.requirement is ToolApprovalRequirement.REQUIRES_APPROVAL:
            if self.risk_level is None:
                raise ValueError(
                    "ToolApprovalPolicyResult requires risk_level "
                    "when requirement is REQUIRES_APPROVAL"
                )

            if self.reason is None or not self.reason.strip():
                raise ValueError(
                    "ToolApprovalPolicyResult requires a non-empty "
                    "reason when requirement is REQUIRES_APPROVAL"
                )
        else:
            if self.risk_level is not None:
                raise ValueError(
                    "ToolApprovalPolicyResult must not carry "
                    "risk_level when requirement is "
                    "DOES_NOT_REQUIRE_APPROVAL"
                )

            if self.reason is not None:
                raise ValueError(
                    "ToolApprovalPolicyResult must not carry reason "
                    "when requirement is DOES_NOT_REQUIRE_APPROVAL"
                )
