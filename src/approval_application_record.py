from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.approval_application_outcome import ApprovalApplicationOutcome
from src.approval_application_status import ApprovalApplicationStatus
from src.approval_decision import ApprovalDecision
from src.clock import utc_now
from src.continuation_next_action import (
    ContinuationNextAction,
    next_action_for,
)

APPLICATION_RECORD_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ApprovalApplicationRecord:
    """The durable claim-and-outcome record for one approval_id
    (5E-5D-6B) - the single file ApprovalApplicationRepository
    exclusively creates to stake a claim, then later overwrites
    (ordinary save(), not another exclusive create - see the
    repository's own docstring for why that second write needs no
    further race protection) to attach an ApprovalApplicationOutcome.

    Deliberately keyed by approval_id alone, matching
    ApprovalRequestRepository/ApprovalResolutionRepository's own
    tasks_dir/approvals/<approval_id>/ convention (this record lives
    in that same per-approval directory, as application.json) -
    task_id/run_id/pending_tool_call_id are carried as *content*
    fields for identity cross-checking, not as path components, the
    same split ApprovalRequest/ApprovalResolution already use.

    decision/next_action/effective_input_digest are the binding this
    record stakes a claim on - captured once, at claim time, from
    whatever ApprovalContinuationPreparationService.prepare() returned
    then. ApprovalApplicationService re-validates a freshly re-read
    preparation against exactly these three fields immediately after
    winning the claim and before dispatching anything (see that
    service's own docstring) - this record is what "before" is
    compared against. next_action is redundant with
    next_action_for(decision) (same single-source-of-truth mapping
    ApprovalContinuationPreparation itself enforces) - stored anyway,
    not re-derived, so a record read back from disk is self-describing
    without importing the mapping function, and __post_init__ below
    still cross-checks the two agree.

    effective_input_digest is a digest (sha256 of a canonical
    id/name/input encoding), not a second embedded copy of the real
    effective input - this record only needs to answer "does the
    currently re-prepared effective action match what was claimed",
    which a digest answers exactly as well as a full copy would,
    without duplicating raw tool input (potentially carrying secrets)
    into a third persisted file beyond request.json/resolution.json.
    None exactly when next_action is not EXECUTE_PENDING_TOOL - REJECT/
    CANCEL have no effective ToolCall to bind at all.

    status/outcome/completed_at describe the record's own lifecycle
    (ApprovalApplicationStatus) - outcome is None and completed_at is
    None for CLAIMED, both are set together for COMPLETED, enforced by
    __post_init__ below exactly like RunContinuationCheckpoint enforces
    its own structural invariants.
    """

    schema_version: int
    approval_id: str
    task_id: str
    run_id: str
    pending_tool_call_id: str
    decision: ApprovalDecision
    next_action: ContinuationNextAction
    effective_input_digest: str | None
    status: ApprovalApplicationStatus
    claimed_at: str = field(default_factory=utc_now)
    outcome: ApprovalApplicationOutcome | None = None
    completed_at: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != APPLICATION_RECORD_SCHEMA_VERSION:
            raise ValueError(
                "Unsupported ApprovalApplicationRecord schema "
                f"version: {self.schema_version!r} (expected "
                f"{APPLICATION_RECORD_SCHEMA_VERSION!r})"
            )

        for field_name in (
            "approval_id",
            "task_id",
            "run_id",
            "pending_tool_call_id",
        ):
            value = getattr(self, field_name)
            if not value or not value.strip():
                raise ValueError(
                    "ApprovalApplicationRecord field "
                    f"'{field_name}' must be a non-empty string"
                )

        if self.next_action is not next_action_for(self.decision):
            raise ValueError(
                "ApprovalApplicationRecord next_action "
                f"{self.next_action!r} does not match the action "
                f"implied by decision {self.decision!r}"
            )

        has_digest = self.effective_input_digest is not None
        expects_digest = (
            self.next_action is ContinuationNextAction.EXECUTE_PENDING_TOOL
        )

        if has_digest != expects_digest:
            raise ValueError(
                "ApprovalApplicationRecord effective_input_digest "
                f"must be set only when next_action is "
                "EXECUTE_PENDING_TOOL"
            )

        if self.status is ApprovalApplicationStatus.CLAIMED:
            if self.outcome is not None or self.completed_at is not None:
                raise ValueError(
                    "ApprovalApplicationRecord must not carry an "
                    "outcome or completed_at while status is CLAIMED"
                )
        elif self.status is ApprovalApplicationStatus.COMPLETED:
            if self.outcome is None or self.completed_at is None:
                raise ValueError(
                    "ApprovalApplicationRecord requires both outcome "
                    "and completed_at when status is COMPLETED"
                )

            if self.outcome.next_action is not self.next_action:
                raise ValueError(
                    "ApprovalApplicationRecord outcome.next_action "
                    f"{self.outcome.next_action!r} does not match "
                    f"record next_action {self.next_action!r}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "approval_id": self.approval_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "pending_tool_call_id": self.pending_tool_call_id,
            "decision": self.decision.value,
            "next_action": self.next_action.value,
            "effective_input_digest": self.effective_input_digest,
            "status": self.status.value,
            "claimed_at": self.claimed_at,
            "outcome": (
                self.outcome.to_dict()
                if self.outcome is not None
                else None
            ),
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalApplicationRecord":
        outcome_data = data.get("outcome")

        return cls(
            schema_version=data["schema_version"],
            approval_id=data["approval_id"],
            task_id=data["task_id"],
            run_id=data["run_id"],
            pending_tool_call_id=data["pending_tool_call_id"],
            decision=ApprovalDecision(data["decision"]),
            next_action=ContinuationNextAction(data["next_action"]),
            effective_input_digest=data.get("effective_input_digest"),
            status=ApprovalApplicationStatus(data["status"]),
            claimed_at=data["claimed_at"],
            outcome=(
                ApprovalApplicationOutcome.from_dict(outcome_data)
                if outcome_data is not None
                else None
            ),
            completed_at=data.get("completed_at"),
        )
