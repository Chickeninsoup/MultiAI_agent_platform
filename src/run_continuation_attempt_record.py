from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.clock import utc_now
from src.run_continuation_transition import RunContinuationTransition
from src.run_continuation_attempt_status import (
    RunContinuationAttemptStatus,
)

ATTEMPT_RECORD_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RunContinuationAttemptRecord:
    """The durable claim-and-transition record for one *chapter* of a
    Run's continuation (5E-5D-6C) - keyed by approval_id
    (RunContinuationAttemptRepository stores one file per approval_id,
    not one mutable record per run_id), because a Run's continuation
    can have several sequential chapters (B's attempt, then - if a
    later call also needs approval - C's own attempt), each
    independently, atomically claimable. task_id/run_id are carried as
    *content* fields for defensive identity cross-checking against the
    path they were loaded from, the same split ApprovalRequest/
    ApprovalResolution/ApprovalApplicationRecord already use for their
    own approval_id-keyed storage.

    This does not replace ApprovalApplicationRecord
    (src/approval_application_record.py) - applying B's decision still
    goes through that exact machinery, with its own independent claim,
    one layer down. This record coordinates the *whole* chapter
    (applying the decision, finishing the round, driving the LLM loop,
    reaching a terminal transition), not just the one pending ToolCall.

    approval_id is both this record's key and the *source* approval
    this chapter was asked to resume with. Because lookup is already
    keyed by it, a caller asking about a different approval_id than
    the one a chapter actually resolved simply finds no record at that
    key at all (see RunService.resume_after_approval() - "a retry for
    approval B cannot silently resume a later approval C" is
    structural here, not a field comparison to get right).

    new_approval_id is populated only when transition is
    RUN_WAITING_FOR_APPROVAL - the approval_id of the *new* pending
    call a later caller would need to resolve and resume with next.
    None for RUN_COMPLETED/RUN_CANCELLED, which have no new pending
    approval at all.

    Deliberately does not duplicate RunServiceResult's own output/
    summary/events paths or token counts - those are cheap to
    recompute from the Run's own current on-disk state
    (RunRepository) at retry time, and persisting a second copy here
    would just be one more place they could drift from what
    RunRepository/events.jsonl already say happened.
    """

    schema_version: int
    task_id: str
    run_id: str
    approval_id: str
    status: RunContinuationAttemptStatus
    claimed_at: str = field(default_factory=utc_now)
    transition: RunContinuationTransition | None = None
    new_approval_id: str | None = None
    completed_at: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != ATTEMPT_RECORD_SCHEMA_VERSION:
            raise ValueError(
                "Unsupported RunContinuationAttemptRecord schema "
                f"version: {self.schema_version!r} (expected "
                f"{ATTEMPT_RECORD_SCHEMA_VERSION!r})"
            )

        for field_name in ("task_id", "run_id", "approval_id"):
            value = getattr(self, field_name)
            if not value or not value.strip():
                raise ValueError(
                    "RunContinuationAttemptRecord field "
                    f"'{field_name}' must be a non-empty string"
                )

        if self.status is RunContinuationAttemptStatus.CLAIMED:
            if (
                self.transition is not None
                or self.new_approval_id is not None
                or self.completed_at is not None
            ):
                raise ValueError(
                    "RunContinuationAttemptRecord must not carry a "
                    "transition, new_approval_id, or completed_at "
                    "while status is CLAIMED"
                )
        elif self.status is RunContinuationAttemptStatus.COMPLETED:
            if self.transition is None or self.completed_at is None:
                raise ValueError(
                    "RunContinuationAttemptRecord requires both "
                    "transition and completed_at when status is "
                    "COMPLETED"
                )

            has_new_approval = self.new_approval_id is not None
            expects_new_approval = (
                self.transition
                is RunContinuationTransition.RUN_WAITING_FOR_APPROVAL
            )

            if has_new_approval != expects_new_approval:
                raise ValueError(
                    "RunContinuationAttemptRecord new_approval_id "
                    "must be set only when transition is "
                    "RUN_WAITING_FOR_APPROVAL"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "approval_id": self.approval_id,
            "status": self.status.value,
            "claimed_at": self.claimed_at,
            "transition": (
                self.transition.value
                if self.transition is not None
                else None
            ),
            "new_approval_id": self.new_approval_id,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any]
    ) -> "RunContinuationAttemptRecord":
        transition_value = data.get("transition")

        return cls(
            schema_version=data["schema_version"],
            task_id=data["task_id"],
            run_id=data["run_id"],
            approval_id=data["approval_id"],
            status=RunContinuationAttemptStatus(data["status"]),
            claimed_at=data["claimed_at"],
            transition=(
                RunContinuationTransition(transition_value)
                if transition_value is not None
                else None
            ),
            new_approval_id=data.get("new_approval_id"),
            completed_at=data.get("completed_at"),
        )
