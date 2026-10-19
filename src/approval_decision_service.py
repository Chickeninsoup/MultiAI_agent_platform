from __future__ import annotations

from typing import Any

from src.approval_decision import ApprovalDecision
from src.approval_decision_errors import (
    ApprovalCheckpointMismatchError,
    ApprovalRunNotFoundError,
    ApprovalRunNotWaitingForApprovalError,
    OrphanedApprovalRequestError,
)
from src.approval_errors import (
    ApprovalAlreadyResolvedError,
    MismatchedApprovalResolutionError,
)
from src.approval_resolution import ApprovalResolution
from src.approval_status import ApprovalStatus
from src.approval_store import ApprovalStore
from src.repositories import RunRepository, TaskRepository
from src.run_continuation_checkpoint_errors import (
    MismatchedCheckpointError,
)
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)

_WAITING_STATUS = "waiting_for_approval"


class ApprovalDecisionService:
    """Safely records one human APPROVE/REJECT/MODIFY/CANCEL decision
    on a pending ApprovalRequest (5E-5D-5A) - records only. Does not
    execute the pending ToolCall, does not touch RunStatus, does not
    resume anything. Turning a recorded decision into continued
    execution is a later stage's job, kept separate the same way
    RuntimeApprovalService (approve/reject) stays split from
    RecoveryContinuationService (act on the decision) - this class is
    this feature's equivalent of the former, not the latter.

    Decision semantics for that future stage (documented here, not
    implemented here):

    - APPROVE: execute the original pending ToolCall exactly as
      checkpointed (checkpoint.pending_round_tool_calls
      [checkpoint.pending_tool_call_index]) - no input changes.
    - MODIFY: execute the *same* tool (same name, same id) using
      resolution.modified_input in place of the checkpointed
      ToolCall's input. Nothing about MODIFY ever changes which tool
      runs or what its id is - ApprovalResolution has no fields that
      could carry a different name/id in the first place, so this is
      a structural guarantee, not just a documented rule.
    - REJECT: do not execute the pending ToolCall. The future resume
      phase must synthesize a protocol-valid human-rejection
      ToolResult (paired with the checkpointed ToolCall's id) so the
      conversation the model sees remains valid, then let the model
      continue from there. Not built here.
    - CANCEL: the future resume phase cancels the entire Run. Not
      applied here - this step only records that a human chose
      CANCEL.

    Three collaborators, each already independently responsible for
    part of the picture, none re-implemented here: ApprovalStore
    (request/resolution persistence + approval_requested/
    approval_resolved events), RunRepository (Run identity/status),
    RunContinuationCheckpointRepository (pending ToolCall position).
    task_repository + the run_id -> task_id scan in
    _find_task_id_for_run() deliberately duplicate RunService.
    _find_task_for_run()'s exact logic rather than depending on
    RunService itself - the same reasoning RunQueryService already
    documents for doing the same thing (query/decision-recording
    side should not depend on the command side that owns Run
    execution), and ApprovalRequest was deliberately not given a
    task_id field just to shortcut this lookup (5E-5D-5A scope).

    Cross-checks (see resolve()) exist because three independently
    persisted records - ApprovalRequest, RunDefinition,
    RunContinuationCheckpoint - all describe the same pending moment
    from different angles, and nothing has verified until now that
    they still agree. A checkpoint with no matching request could
    never reach this class (loaded by request.run_id, not
    discovered independently), but a request with no matching
    checkpoint (the orphan case documented in
    RunContinuationCheckpoint's own module, and in
    run_continuation_checkpoint_repository's known crash window) is
    real and must not be silently approvable.

    Those cross-checks - and the Run/checkpoint lookups they depend
    on - only ever run once per approval, for whichever call first
    finds the request PENDING (5E-5D-5A-1). ApprovalStore's own
    RESOLVED/PENDING projection is checked immediately after loading
    the request, before any Run or checkpoint lookup: once an
    ApprovalRequest is RESOLVED, ApprovalStore is the sole
    authoritative answer to "what was decided," and re-deriving that
    answer by re-validating Run status and checkpoint identity on
    every retry would make idempotency only *temporarily* true - a
    later resume phase moving the Run off waiting_for_approval, or
    archiving the checkpoint, must not turn a retry of an
    already-committed decision into a spurious failure.
    """

    def __init__(
        self,
        approval_store: ApprovalStore,
        task_repository: TaskRepository,
        run_repository: RunRepository,
        continuation_checkpoint_repository: (
            RunContinuationCheckpointRepository
        ),
    ) -> None:
        self._approval_store = approval_store
        self._task_repository = task_repository
        self._run_repository = run_repository
        self._continuation_checkpoint_repository = (
            continuation_checkpoint_repository
        )

    def resolve(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        modified_input: dict[str, Any] | None = None,
        explanation: str | None = None,
    ) -> ApprovalResolution:
        if not isinstance(decision, ApprovalDecision):
            raise ValueError(
                "ApprovalDecisionService.resolve() requires an "
                f"ApprovalDecision, got {decision!r}"
            )

        # Constructing this immediately reuses ApprovalResolution's
        # own domain validation (5E-5D-1: non-empty approval_id,
        # MODIFY<=>modified_input in both directions, non-empty-if-
        # present explanation) instead of duplicating those rules
        # here. Built once, reused as the actual persisted object
        # below if every check passes - never rebuilt.
        candidate = ApprovalResolution(
            approval_id=approval_id,
            decision=decision,
            modified_input=modified_input,
            explanation=explanation,
        )

        # ApprovalStore.get() raises ApprovalRequestNotFoundError for
        # an unknown id and projects live RESOLVED/PENDING status
        # (5E-5D-2) - reused as-is, not re-derived.
        request = self._approval_store.get(approval_id)

        if request.approval_id != approval_id:
            # Defensive: repository lookup keys by approval_id, so
            # this can only fire on a corrupted store - still checked
            # explicitly rather than assumed.
            raise MismatchedApprovalResolutionError(
                f"Loaded request approval_id {request.approval_id!r} "
                f"does not match requested {approval_id!r}"
            )

        # RESOLVED fast path (5E-5D-5A-1) - checked immediately after
        # loading the request, before *any* Run/checkpoint lookup.
        # ApprovalStore is the sole authority on whether a decision
        # has already been recorded (5E-5D-2); once it says RESOLVED,
        # that fact alone is enough to answer this call - the Run may
        # have since moved on (a future resume phase is free to change
        # its status) and the checkpoint may have since been archived
        # or removed, and neither should turn a legitimate retry of an
        # already-committed decision into a spurious
        # ApprovalRunNotWaitingForApprovalError/OrphanedApprovalRequestError.
        # This is why the identity/status/checkpoint cross-checks
        # below only ever run for a still-PENDING request - they exist
        # to protect the *first* resolution, not to be re-verified on
        # every subsequent read of an already-decided one.
        if request.status is ApprovalStatus.RESOLVED:
            existing = self._approval_store.get_resolution(
                approval_id
            )
            assert existing is not None  # implied by RESOLVED

            if (
                existing.decision == candidate.decision
                and existing.modified_input == candidate.modified_input
                and existing.explanation == candidate.explanation
            ):
                # Idempotent retry of the exact same semantic
                # decision - the original resolved_at is
                # authoritative, no new file write, no second
                # approval_resolved event (ApprovalStore.resolve() is
                # never called), and no task/run scan or checkpoint
                # load ever happens for this call.
                return existing

            raise ApprovalAlreadyResolvedError(
                f"Approval request already resolved: {approval_id!r}"
            )

        # Everything from here down only ever runs for a still-PENDING
        # request - the first (and only) resolution attempt.
        task_id = self._find_task_id_for_run(request.run_id)

        if task_id is None:
            raise ApprovalRunNotFoundError(
                f"No task owns run {request.run_id!r} referenced by "
                f"approval {approval_id!r}"
            )

        try:
            run = self._run_repository.load(task_id, request.run_id)
        except FileNotFoundError as exc:
            raise ApprovalRunNotFoundError(
                f"Run {request.run_id!r} referenced by approval "
                f"{approval_id!r} could not be loaded"
            ) from exc

        if run.id != request.run_id:
            raise ApprovalRunNotFoundError(
                f"Loaded run id {run.id!r} does not match requested "
                f"run_id {request.run_id!r}"
            )

        if run.status != _WAITING_STATUS:
            raise ApprovalRunNotWaitingForApprovalError(
                f"Run {run.id!r} has status {run.status!r}, not "
                f"{_WAITING_STATUS!r} - approval {approval_id!r} "
                "cannot be resolved"
            )

        try:
            checkpoint = (
                self._continuation_checkpoint_repository.load(
                    task_id, request.run_id
                )
            )
        except FileNotFoundError as exc:
            raise OrphanedApprovalRequestError(
                f"Approval {approval_id!r} is pending but run "
                f"{request.run_id!r} has no continuation checkpoint "
                "- cannot be approved, modified, rejected, or "
                "cancelled until this orphan is reconciled"
            ) from exc
        except MismatchedCheckpointError as exc:
            # RunContinuationCheckpointRepository.load() (5E-5D-4C)
            # already refuses to return a checkpoint whose own
            # task_id/run_id disagree with the location it was read
            # from - re-raised under this service's own error
            # vocabulary so every checkpoint-related failure a caller
            # of resolve() can catch is one of this module's types,
            # not a mix of this module's and the repository's.
            raise ApprovalCheckpointMismatchError(
                f"Continuation checkpoint for run {request.run_id!r} "
                f"is corrupted: {exc}"
            ) from exc

        if checkpoint.approval_id != request.approval_id:
            raise ApprovalCheckpointMismatchError(
                f"Checkpoint approval_id {checkpoint.approval_id!r} "
                f"does not match request approval_id "
                f"{request.approval_id!r}"
            )

        if checkpoint.run_id != request.run_id:
            # In practice unreachable as a *distinct* failure path -
            # RunContinuationCheckpointRepository.load() above already
            # guarantees checkpoint.run_id == request.run_id (the
            # exact run_id it was loaded by) whenever it returns
            # successfully, and raises MismatchedCheckpointError
            # (caught above) otherwise. Kept as an explicit, cheap
            # defense-in-depth check rather than relying entirely on
            # the repository's own invariant - same reasoning as the
            # "request.approval_id != approval_id" and
            # "run.id != request.run_id" checks above.
            raise ApprovalCheckpointMismatchError(
                f"Checkpoint run_id {checkpoint.run_id!r} does not "
                f"match request run_id {request.run_id!r}"
            )

        if checkpoint.pending_tool_call_id != request.proposed_action.id:
            raise ApprovalCheckpointMismatchError(
                "Checkpoint pending_tool_call_id "
                f"{checkpoint.pending_tool_call_id!r} does not match "
                f"request proposed_action.id "
                f"{request.proposed_action.id!r}"
            )

        # RunContinuationCheckpoint.__post_init__ (5E-5D-4C) already
        # guarantees pending_tool_call_index points at an entry whose
        # .id equals pending_tool_call_id - not re-checked here. What
        # is checked: that the *entire* pending ToolCall (name, input,
        # not just id) still matches what the request itself proposed.
        pending_call = checkpoint.pending_round_tool_calls[
            checkpoint.pending_tool_call_index
        ]

        if pending_call != request.proposed_action:
            raise ApprovalCheckpointMismatchError(
                "Checkpoint's pending ToolCall does not match "
                f"approval {approval_id!r}'s proposed_action"
            )

        # request.status is guaranteed PENDING here - the RESOLVED
        # case already returned or raised above, before any of the
        # Run/checkpoint work above this line ever ran.
        return self._approval_store.resolve(approval_id, candidate)

    def _find_task_id_for_run(self, run_id: str) -> str | None:
        for task in self._task_repository.list_all():
            if run_id in self._run_repository.list_run_ids(task.id):
                return task.id

        return None
