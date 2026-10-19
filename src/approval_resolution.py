from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.approval_decision import ApprovalDecision
from src.clock import utc_now


@dataclass(frozen=True)
class ApprovalResolution:
    """The terminal record of a human resolving one ApprovalRequest
    (5E-5D-1) - the ApprovalRequest identifies what was asked; this
    identifies what was answered, when, and (for MODIFY) with what
    different input.

    Kept as a separate object rather than fields bolted onto
    ApprovalRequest, matching PlanReview/PlanApproval's split in this
    codebase (a review is proposed, an approval is a separate later
    decision about it): an ApprovalRequest can exist for a while in
    PENDING with no ApprovalResolution at all, and once resolved, the
    request's own fields (what was proposed, why, its risk) shouldn't
    need to change just because a decision was recorded.

    approval_id links this resolution back to the ApprovalRequest it
    resolves - deliberately just the id, not the whole ApprovalRequest
    embedded, matching how ExecutionFailure/ValidationError carry
    identifiers (step_id, code) rather than the objects they describe;
    whatever persists/looks these up can join them by id.

    decision is the terminal human choice (ApprovalDecision) - always
    required, never optional, since a resolution that doesn't actually
    decide anything isn't a resolution.

    modified_input only makes sense for MODIFY (the human is proposing
    a *different* input for the same action) - see __post_init__: any
    other decision carrying a modified_input, or MODIFY without one,
    is rejected at construction rather than left for a caller to
    misinterpret later. Typed dict[str, Any], matching ToolCall.input,
    since a modified input is still ultimately a tool input.

    resolver identity (who made this decision) is deliberately not a
    field here: no user/actor/identity concept exists anywhere else in
    this codebase - this is a single-operator local platform, and even
    the existing `review` CLI's approve/reject records no "who", only
    a status and a timestamp (src/review/). Inventing an identity
    convention here, unused by anything else in the codebase, would be
    a new convention this task's scope doesn't call for; if an
    identity model is ever added elsewhere, resolver identity belongs
    on ApprovalResolution then, not now.

    modified_input is excluded from the auto-generated __repr__
    (field(repr=False), 5E-5D-4A-1) - for the same reason
    ApprovalRequest.proposed_action is: it's the one field on this
    class that can carry raw, unredacted tool input (a human's
    proposed replacement for the original), and repr() is what
    ordinary debug output/logging/test-failure messages go through.
    Equality (==) and to_dict()/from_dict() persistence are untouched -
    only str(resolution)/repr(resolution) change.
    """

    approval_id: str
    decision: ApprovalDecision
    modified_input: dict[str, Any] | None = field(
        default=None, repr=False
    )
    explanation: str | None = None
    resolved_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.approval_id or not self.approval_id.strip():
            raise ValueError(
                "ApprovalResolution field 'approval_id' must be a "
                "non-empty string"
            )

        if (
            self.explanation is not None
            and not self.explanation.strip()
        ):
            raise ValueError(
                "ApprovalResolution field 'explanation' must not be "
                "an empty string when provided"
            )

        if (
            self.decision is ApprovalDecision.MODIFY
            and self.modified_input is None
        ):
            raise ValueError(
                "ApprovalResolution decision MODIFY requires "
                "modified_input"
            )

        if (
            self.decision is not ApprovalDecision.MODIFY
            and self.modified_input is not None
        ):
            raise ValueError(
                "ApprovalResolution modified_input is only valid "
                "when decision is MODIFY"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "decision": self.decision.value,
            "modified_input": self.modified_input,
            "explanation": self.explanation,
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalResolution":
        return cls(
            approval_id=data["approval_id"],
            decision=ApprovalDecision(data["decision"]),
            modified_input=data.get("modified_input"),
            explanation=data.get("explanation"),
            resolved_at=data["resolved_at"],
        )
