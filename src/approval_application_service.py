from __future__ import annotations

import copy
import hashlib
import json

from src.approval_application_errors import (
    ApprovalApplicationBlockedError,
    ApprovalApplicationDispatchError,
    ApprovalApplicationMismatchError,
    ApprovalApplicationPersistenceError,
)
from src.approval_application_outcome import ApprovalApplicationOutcome
from src.approval_application_record import (
    APPLICATION_RECORD_SCHEMA_VERSION,
    ApprovalApplicationRecord,
)
from src.approval_application_repository import (
    ApprovalApplicationRepository,
)
from src.approval_application_status import ApprovalApplicationStatus
from src.approval_continuation_preparation import (
    ApprovalContinuationPreparation,
)
from src.approval_continuation_preparation_service import (
    ApprovalContinuationPreparationService,
)
from src.continuation_next_action import ContinuationNextAction
from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_result import ToolResult
from src.run_events import NullRunEventSink, RunEventSink
from src.services.tools.tool_executor import ToolExecutor

_REJECTION_OUTPUT = (
    "Tool call was rejected by human approval decision."
)


def _digest_for(tool_call: ToolCall | None) -> str | None:
    """A deterministic fingerprint of exactly the fields that matter
    for "is this the same effective action" (id, name, input) - not a
    second persisted copy of the raw input itself (see
    ApprovalApplicationRecord's own docstring for why a digest, not a
    snapshot, was chosen). sort_keys=True makes the encoding
    independent of dict insertion order, so semantically identical
    input never produces two different digests."""

    if tool_call is None:
        return None

    canonical = json.dumps(
        {
            "id": tool_call.id,
            "name": tool_call.name,
            "input": tool_call.input,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _isolated_copy(tool_call: ToolCall) -> ToolCall:
    """A ToolCall with a deep-copied input dict, independent of
    whatever checkpoint/resolution object effective_tool_call was
    read from - so a handler mutating tool_input in place (ToolCall is
    frozen, but .input is a plain mutable dict nothing stops a handler
    from writing into) can never reach back into
    ApprovalContinuationPreparation.checkpoint's own pending call or
    ApprovalResolution.modified_input. Used for both the digest bound
    into the claim and the actual ToolExecutor.execute() call, so the
    two always observe exactly the same input."""

    return ToolCall(
        id=tool_call.id,
        name=tool_call.name,
        input=copy.deepcopy(tool_call.input),
    )


def _binding_matches(
    preparation: ApprovalContinuationPreparation,
    record: ApprovalApplicationRecord,
    effective_digest: str | None,
) -> bool:
    return (
        preparation.approval_id == record.approval_id
        and preparation.checkpoint.pending_tool_call_id
        == record.pending_tool_call_id
        and preparation.decision == record.decision
        and preparation.next_action == record.next_action
        and effective_digest == record.effective_input_digest
    )


class ApprovalApplicationService:
    """Durably applies one already-resolved pending approval decision
    to its single pending ToolCall (5E-5D-6B) - the stage between
    ApprovalContinuationPreparationService (read-only description) and
    a not-yet-built Run-continuation stage (advances the checkpoint,
    resumes the LLM loop). This class executes exactly one call (or
    exactly zero, for REJECT/CANCEL), persists exactly one outcome, and
    stops - it does not advance pending_tool_call_index, does not touch
    later calls, does not resume the Run, and never calls an LLMProvider.

    apply(task_id, run_id, approval_id) takes identifiers, not a
    caller-supplied ApprovalContinuationPreparation, as the authority -
    a caller cannot hand this service a preparation it built or cached
    itself and have that substitute for this service's own fresh read.
    For a fresh application (no existing ApprovalApplicationRecord),
    prepare() is called internally and its approval_id is checked
    against the requested one before anything else happens.

    Claim lifecycle (ApprovalApplicationRepository/
    ApprovalApplicationRecord/ApprovalApplicationStatus):

    1. No record exists - prepare() fresh, build a CLAIMED record
       binding (approval_id, task_id, run_id, pending_tool_call_id,
       decision, next_action, a digest of the effective action), and
       attempt create_exclusive(). create_exclusive() uses
       JsonRepository.create_exclusive() (O_CREAT|O_EXCL) - this is
       the one atomic-across-processes step; "fresh application" and
       "I am now the sole owner of this approval_id's application"
       become true in the same syscall.

    2. If create_exclusive() returns False, another caller already won
       (or an earlier attempt already exists) - load whatever is
       there: COMPLETED returns its stored outcome (after the same
       identity-binding check retries always get, see below);
       CLAIMED (someone else's, or a crashed earlier attempt - this
       service cannot and does not try to tell those apart) raises
       ApprovalApplicationBlockedError. No dispatch happens on this
       path, ever.

    3. If create_exclusive() returns True, this call owns the claim.
       It re-reads preparation (prepare() again) and verifies the
       binding still matches what was just claimed - closing the race
       between "decide what to claim" and "win the claim" - raising
       ApprovalApplicationMismatchError on any disagreement, with the
       claim left CLAIMED (requiring manual reconciliation, same as
       every other post-claim failure path here; see point 5).

    4. Only the claim owner ever reaches dispatch, and only once: for
       EXECUTE_PENDING_TOOL, an isolated copy of effective_tool_call
       goes through the *normal* ToolExecutor.execute() path - no
       bypassed authorization, no re-run ToolApprovalGate check (the
       human already decided this exact call; re-raising a *new*
       ApprovalRequest for it would be wrong, but ToolExecutor's own
       unknown-tool/disabled-tool checks are untouched and still run).
       For REJECT_PENDING_TOOL, no handler runs; a fixed-text rejection
       ToolResult is synthesized for the pending call's id. For
       CANCEL_RUN, nothing runs and no ToolResult is produced at all -
       only an outcome recording that next_action.

    5. The resulting ApprovalApplicationOutcome is persisted via
       ApprovalApplicationRepository.complete() (an ordinary,
       non-exclusive save - only the claim owner's single call stack
       ever reaches this line, so no further race protection is
       needed). If dispatch itself raises unexpectedly (not a normal
       ToolExecutor failure ToolResult - those are a success path for
       this service, persisted as-is), the claim stays CLAIMED and
       ApprovalApplicationDispatchError is raised. If dispatch
       succeeds but complete() raises, the claim *also* stays CLAIMED
       (JsonRepository.save()'s tmp-file-then-replace means a failed
       write can never leave a half-written COMPLETED record) and
       ApprovalApplicationPersistenceError is raised - documenting
       exactly the case where a tool side effect may have already
       happened and this service cannot prove it was recorded. Neither
       failure is auto-retried by anything in this class; a CLAIMED
       record left behind by either requires manual reconciliation,
       by design (see ApprovalApplicationStatus's own docstring).

    Event emission (if event_sink is configured) happens only after
    complete() has already durably persisted the COMPLETED record -
    emitting is deliberately the very last thing this method does, and
    a failure raised by event_sink.emit() is allowed to propagate
    (nothing here swallows it), but it changes nothing about whether a
    later retry re-dispatches: by the time emit() is even reached, the
    on-disk record is already COMPLETED, so every retry path above
    short-circuits to the stored outcome regardless of whether the
    event was ever recorded. This is a known, accepted receipt/event
    gap (an event can be silently lost if the process dies between
    complete() returning and emit() finishing) - the same gap
    ApprovalStore.create()/resolve() already have between their own
    write-then-emit calls, not a new one introduced here. Only raw
    tool input/output never appears in the emitted event - decision,
    next_action, and (for EXECUTE/REJECT) whether the ToolResult
    succeeded are the only tool-shaped fields included.
    """

    def __init__(
        self,
        preparation_service: ApprovalContinuationPreparationService,
        application_repository: ApprovalApplicationRepository,
        tool_executor: ToolExecutor,
        event_sink: RunEventSink | None = None,
    ) -> None:
        self._preparation_service = preparation_service
        self._application_repository = application_repository
        self._tool_executor = tool_executor
        self._event_sink = (
            event_sink
            if event_sink is not None
            else NullRunEventSink()
        )

    def _try_load_or_block(
        self, approval_id: str
    ) -> ApprovalApplicationRecord | None:
        """try_load(), with a malformed/unreadable record treated as
        "blocked" rather than letting a raw parsing exception escape
        (5E-5D-6B hardening) - create_exclusive() makes a claim file
        exist and only *then* writes its content, so a reader landing
        in that narrow window (another process mid-write, not yet
        flushed) can see a transiently empty/partial file. This is the
        same case this class's own docstring already names
        ("incomplete/malformed claim records also block dispatch") -
        converting the parse failure into ApprovalApplicationBlockedError
        here makes that documented behavior actually hold under a real
        concurrent write, not just for a permanently corrupted file."""

        try:
            return self._application_repository.try_load(approval_id)
        except Exception as exc:
            raise ApprovalApplicationBlockedError(
                f"Approval {approval_id!r} has a malformed or "
                "unreadable application record - refusing to "
                "dispatch until this is manually reconciled"
            ) from exc

    def apply(
        self, task_id: str, run_id: str, approval_id: str
    ) -> ApprovalApplicationOutcome:
        existing = self._try_load_or_block(approval_id)

        if existing is not None:
            self._verify_identity(existing, task_id, run_id, approval_id)

            if existing.status is ApprovalApplicationStatus.COMPLETED:
                assert existing.outcome is not None
                return existing.outcome

            raise ApprovalApplicationBlockedError(
                f"Approval {approval_id!r} already has an incomplete "
                "application claim - refusing to dispatch again until "
                "this is manually reconciled"
            )

        preparation = self._preparation_service.prepare(task_id, run_id)
        self._verify_approval_id(preparation, approval_id)

        effective_digest = _digest_for(preparation.effective_tool_call)

        claim = ApprovalApplicationRecord(
            schema_version=APPLICATION_RECORD_SCHEMA_VERSION,
            approval_id=approval_id,
            task_id=task_id,
            run_id=run_id,
            pending_tool_call_id=preparation.checkpoint.pending_tool_call_id,
            decision=preparation.decision,
            next_action=preparation.next_action,
            effective_input_digest=effective_digest,
            status=ApprovalApplicationStatus.CLAIMED,
        )

        try:
            created = self._application_repository.create_exclusive(
                claim
            )
        except Exception as exc:
            raise ApprovalApplicationPersistenceError(
                f"Failed to persist an application claim for "
                f"approval {approval_id!r} - no tool was dispatched"
            ) from exc

        if not created:
            lost_race = self._try_load_or_block(approval_id)
            assert lost_race is not None
            self._verify_identity(
                lost_race, task_id, run_id, approval_id
            )

            if lost_race.status is ApprovalApplicationStatus.COMPLETED:
                assert lost_race.outcome is not None
                return lost_race.outcome

            raise ApprovalApplicationBlockedError(
                f"Approval {approval_id!r} already has an incomplete "
                "application claim - refusing to dispatch again until "
                "this is manually reconciled"
            )

        # This call now exclusively owns the fresh claim. Re-read
        # preparation before dispatching anything - state may have
        # changed between the prepare() call above and winning the
        # claim.
        revalidated = self._preparation_service.prepare(task_id, run_id)

        if not _binding_matches(revalidated, claim, effective_digest):
            raise ApprovalApplicationMismatchError(
                f"Re-validated preparation for approval {approval_id!r} "
                "no longer matches the action bound to the claim just "
                "acquired - refusing to dispatch"
            )

        try:
            outcome = self._dispatch(revalidated)
        except Exception as exc:
            raise ApprovalApplicationDispatchError(
                f"Dispatching the pending call for approval "
                f"{approval_id!r} raised unexpectedly - the claim is "
                "preserved and will not be auto-retried"
            ) from exc

        try:
            self._application_repository.complete(approval_id, outcome)
        except Exception as exc:
            raise ApprovalApplicationPersistenceError(
                f"Dispatch for approval {approval_id!r} completed but "
                "persisting its outcome failed - the claim is "
                "preserved and will not be auto-retried"
            ) from exc

        self._event_sink.emit(_applied_event(claim, outcome))

        return outcome

    def _dispatch(
        self, preparation: ApprovalContinuationPreparation
    ) -> ApprovalApplicationOutcome:
        if (
            preparation.next_action
            is ContinuationNextAction.EXECUTE_PENDING_TOOL
        ):
            assert preparation.effective_tool_call is not None
            isolated_call = _isolated_copy(
                preparation.effective_tool_call
            )
            tool_result = self._tool_executor.execute(isolated_call)

            return ApprovalApplicationOutcome(
                next_action=preparation.next_action,
                tool_result=tool_result,
            )

        if (
            preparation.next_action
            is ContinuationNextAction.REJECT_PENDING_TOOL
        ):
            pending_call = preparation.pending_tool_call

            return ApprovalApplicationOutcome(
                next_action=preparation.next_action,
                tool_result=ToolResult(
                    tool_call_id=pending_call.id,
                    tool_name=pending_call.name,
                    success=False,
                    output=_REJECTION_OUTPUT,
                    error_code="APPROVAL_REJECTED",
                ),
            )

        return ApprovalApplicationOutcome(
            next_action=ContinuationNextAction.CANCEL_RUN,
            tool_result=None,
        )

    @staticmethod
    def _verify_approval_id(
        preparation: ApprovalContinuationPreparation, approval_id: str
    ) -> None:
        if preparation.approval_id != approval_id:
            raise ApprovalApplicationMismatchError(
                f"Prepared approval_id {preparation.approval_id!r} "
                f"does not match requested {approval_id!r}"
            )

    @staticmethod
    def _verify_identity(
        record: ApprovalApplicationRecord,
        task_id: str,
        run_id: str,
        approval_id: str,
    ) -> None:
        if (
            record.approval_id != approval_id
            or record.task_id != task_id
            or record.run_id != run_id
        ):
            raise ApprovalApplicationMismatchError(
                "Existing ApprovalApplicationRecord identity "
                f"(approval_id={record.approval_id!r}, "
                f"task_id={record.task_id!r}, run_id={record.run_id!r}) "
                "does not match requested "
                f"(approval_id={approval_id!r}, task_id={task_id!r}, "
                f"run_id={run_id!r})"
            )


def _applied_event(
    claim: ApprovalApplicationRecord,
    outcome: ApprovalApplicationOutcome,
) -> dict[str, object]:
    tool_result = outcome.tool_result

    return {
        "type": "approval_applied",
        "approval_id": claim.approval_id,
        "run_id": claim.run_id,
        "task_id": claim.task_id,
        "pending_tool_call_id": claim.pending_tool_call_id,
        "decision": claim.decision.value,
        "next_action": outcome.next_action.value,
        "tool_success": (
            tool_result.success if tool_result is not None else None
        ),
    }
