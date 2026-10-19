from __future__ import annotations

import copy

from src.approval_continuation_preparation import (
    ApprovalContinuationPreparation,
)
from src.approval_continuation_preparation_errors import (
    ApprovalResolutionPendingError,
)
from src.approval_decision import ApprovalDecision
from src.approval_decision_errors import (
    ApprovalCheckpointMismatchError,
    ApprovalRunNotFoundError,
    ApprovalRunNotWaitingForApprovalError,
    OrphanedApprovalRequestError,
)
from src.approval_store import ApprovalStore
from src.continuation_next_action import next_action_for
from src.domain.tools.tool_call import ToolCall
from src.repositories import RunRepository
from src.run_continuation_checkpoint_errors import (
    MismatchedCheckpointError,
)
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)

_WAITING_STATUS = "waiting_for_approval"


class ApprovalContinuationPreparationService:
    """Read-only preparation layer between a recorded ApprovalResolution
    and actually continuing a paused Run (5E-5D-6A) - validates that a
    Run, its continuation checkpoint, the approval request it
    references, and a recorded resolution all still agree, then
    describes the next action precisely. Does not execute the pending
    ToolCall, does not touch ToolExecutor/any provider, does not
    mutate the Run, does not write or delete the checkpoint, does not
    create or resolve an approval, and emits no audit event - the same
    split ApprovalDecisionService (records a decision) already draws
    against whatever eventually acts on it, continued one stage
    further: that class records; this class only reads and describes;
    a later stage not built here is the one that actually executes.

    prepare(task_id, run_id) takes an explicit task_id rather than
    resolving it from run_id (contrast
    ApprovalDecisionService._find_task_id_for_run()) because this
    service's caller already knows which Run it is resuming - picking
    a specific Run to continue is naturally task_id-scoped, the same
    way RunRepository/RunContinuationCheckpointRepository themselves
    are keyed. ApprovalRequest is deliberately not given a task_id
    field to shortcut this (same reasoning ApprovalDecisionService's
    own docstring already gives) - this service reaches the approval
    request through checkpoint.approval_id instead, never from a
    task_id/run_id pair directly.

    Validation order mirrors how these four records actually chain
    together, not an arbitrary checklist: Run (has a status, and *is*
    the thing a checkpoint/approval concern) -> its
    RunContinuationCheckpoint (named by task_id/run_id, carries
    approval_id) -> the ApprovalRequest that approval_id names (carries
    run_id and the real proposed_action, cross-checked against the
    checkpoint) -> the ApprovalResolution for that same approval_id
    (the one thing that can be legitimately absent - PENDING is a
    valid state, just not one prepare() can act on).

    Every failure before "a resolution exists" is a corruption/identity
    problem, reusing ApprovalDecisionService's own error vocabulary
    where the exact same meaning applies (ApprovalRunNotFoundError,
    ApprovalRunNotWaitingForApprovalError, OrphanedApprovalRequestError,
    ApprovalCheckpointMismatchError) rather than inventing parallel
    types for facts those errors already name correctly. Only "no
    resolution yet" is new (ApprovalResolutionPendingError) - nothing
    in ApprovalDecisionService's vocabulary means "not decided yet,"
    because that class never needed to say so; it only ever acts on a
    decision once one is being recorded. ApprovalRequestNotFoundError
    (src/approval_errors.py) is reused unwrapped for the one case that
    is neither "corrupted" nor "not yet decided": a checkpoint pointing
    at an approval_id ApprovalStore has never heard of.

    Does not assume the cross-checks ApprovalDecisionService already
    ran when the resolution was first recorded remain valid now - runs
    its own full set every call, against whatever RunRepository/
    RunContinuationCheckpointRepository/ApprovalStore currently
    contain. A Run or checkpoint can change between "a human resolved
    this" and "something tries to continue it"; this class treats the
    resolution as settled (ApprovalStore is the sole authority on
    *what* was decided - re-deciding is not this class's job) but
    never treats the Run/checkpoint's current agreement with it as
    settled.
    """

    def __init__(
        self,
        run_repository: RunRepository,
        continuation_checkpoint_repository: (
            RunContinuationCheckpointRepository
        ),
        approval_store: ApprovalStore,
    ) -> None:
        self._run_repository = run_repository
        self._continuation_checkpoint_repository = (
            continuation_checkpoint_repository
        )
        self._approval_store = approval_store

    def prepare(
        self, task_id: str, run_id: str
    ) -> ApprovalContinuationPreparation:
        try:
            run = self._run_repository.load(task_id, run_id)
        except FileNotFoundError as exc:
            raise ApprovalRunNotFoundError(
                f"Run {run_id!r} not found for task {task_id!r}"
            ) from exc

        if run.id != run_id or run.task_id != task_id:
            raise ApprovalRunNotFoundError(
                f"Loaded run (id={run.id!r}, task_id={run.task_id!r}) "
                f"does not match requested (run_id={run_id!r}, "
                f"task_id={task_id!r})"
            )

        if run.status != _WAITING_STATUS:
            raise ApprovalRunNotWaitingForApprovalError(
                f"Run {run_id!r} has status {run.status!r}, not "
                f"{_WAITING_STATUS!r} - continuation cannot be "
                "prepared"
            )

        try:
            checkpoint = (
                self._continuation_checkpoint_repository.load(
                    task_id, run_id
                )
            )
        except FileNotFoundError as exc:
            raise OrphanedApprovalRequestError(
                f"Run {run_id!r} is {_WAITING_STATUS!r} but has no "
                "continuation checkpoint - cannot prepare "
                "continuation until this orphan is reconciled"
            ) from exc
        except MismatchedCheckpointError as exc:
            raise ApprovalCheckpointMismatchError(
                f"Continuation checkpoint for run {run_id!r} is "
                f"corrupted: {exc}"
            ) from exc

        # ApprovalStore.get() raises ApprovalRequestNotFoundError
        # (reused as-is) for a checkpoint pointing at an approval_id
        # the store has never heard of.
        request = self._approval_store.get(checkpoint.approval_id)

        if request.approval_id != checkpoint.approval_id:
            # Defensive: ApprovalStore.get() looks up by approval_id,
            # so this can only fire on a corrupted store.
            raise ApprovalCheckpointMismatchError(
                f"Approval request approval_id {request.approval_id!r} "
                "does not match checkpoint approval_id "
                f"{checkpoint.approval_id!r}"
            )

        if request.run_id != run_id:
            raise ApprovalCheckpointMismatchError(
                f"Approval request run_id {request.run_id!r} does not "
                f"match requested run_id {run_id!r}"
            )

        pending_call = checkpoint.pending_round_tool_calls[
            checkpoint.pending_tool_call_index
        ]

        if pending_call != request.proposed_action:
            raise ApprovalCheckpointMismatchError(
                "Checkpoint's pending ToolCall does not match the "
                "approval request's proposed_action"
            )

        resolution = self._approval_store.get_resolution(
            checkpoint.approval_id
        )

        if resolution is None:
            raise ApprovalResolutionPendingError(
                f"Approval {checkpoint.approval_id!r} has not been "
                "resolved yet - continuation cannot be prepared"
            )

        if resolution.approval_id != checkpoint.approval_id:
            # Defensive: ApprovalResolutionRepository.get() looks up by
            # approval_id, so this can only fire on a corrupted store.
            raise ApprovalCheckpointMismatchError(
                f"Resolution approval_id {resolution.approval_id!r} "
                "does not match checkpoint approval_id "
                f"{checkpoint.approval_id!r}"
            )

        # ApprovalResolution.__post_init__ already enforces the
        # MODIFY<=>modified_input invariant at construction/
        # deserialization time - not re-validated here.
        next_action = next_action_for(resolution.decision)
        effective_tool_call: ToolCall | None = None

        if resolution.decision is ApprovalDecision.APPROVE:
            effective_tool_call = pending_call
        elif resolution.decision is ApprovalDecision.MODIFY:
            effective_tool_call = ToolCall(
                id=pending_call.id,
                name=pending_call.name,
                input=copy.deepcopy(resolution.modified_input),
            )

        return ApprovalContinuationPreparation(
            task_id=task_id,
            run_id=run_id,
            checkpoint=checkpoint,
            resolution=resolution,
            next_action=next_action,
            effective_tool_call=effective_tool_call,
        )
