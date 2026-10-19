from dataclasses import dataclass, replace
from pathlib import Path

from src.approval_application_service import ApprovalApplicationService
from src.approval_continuation_preparation_service import (
    ApprovalContinuationPreparationService,
)
from src.clock import utc_now
from src.context_builder import RunContextBuilder
from src.execution import ApprovalContinuationCapableExecutor, RunExecutor
from src.models import RunDefinition, RunExecutionResult, TaskDefinition
from src.repositories import (
    AgentRepository,
    RunRepository,
    TaskRepository,
)
from src.review.change_snapshot_builder import ChangeSnapshotBuilder
from src.review.review_policy import requires_review
from src.review.snapshot_repository import SnapshotRepository
from src.run_continuation_attempt_errors import (
    RunContinuationBlockedError,
    RunContinuationFailedError,
    RunContinuationMismatchError,
    RunContinuationNotConfiguredError,
    RunContinuationPersistenceError,
)
from src.run_continuation_attempt_record import (
    ATTEMPT_RECORD_SCHEMA_VERSION,
    RunContinuationAttemptRecord,
)
from src.run_continuation_attempt_repository import (
    RunContinuationAttemptRepository,
)
from src.run_continuation_attempt_status import (
    RunContinuationAttemptStatus,
)
from src.run_continuation_checkpoint import RunContinuationCheckpoint
from src.run_continuation_transition import RunContinuationTransition
from src.run_errors import RunErrorCategory, classify_error, is_retryable

RESUMABLE_STATUSES = {"in_progress", "interrupted"}
# waiting_for_approval (5E-5D-4B) is deliberately not included here.
# It genuinely is "a resumable, expected pause" conceptually, but the
# generic resume() below (crash recovery: mark interrupted, create a
# brand-new Run with the same input, re-execute from scratch) is the
# wrong resume semantics for it - it would just re-propose the same
# gated action under a new run_id and hit approval again, orphaning
# the original ApprovalRequest. Approval-aware resume (continue this
# same Run once a human has resolved the ApprovalRequest) is real
# remaining work for a later stage, not something resume() does today.


@dataclass(frozen=True)
class RunServiceResult:
    task_id: str
    run_id: str
    agent_id: str
    status: str
    output_path: Path
    summary_path: Path
    events_path: Path
    llm_rounds: int | None = None
    tool_rounds: int | None = None
    tool_calls: int | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    # Populated only when status == "waiting_for_approval" (5E-5D-4B) -
    # None for every other status, matching the existing optional-field
    # convention every other field here already uses. Never carries
    # proposed_action.input or any other raw ToolCall data - just the
    # id a human needs to look the pending ApprovalRequest up by.
    approval_id: str | None = None


class RunExecutionFailedError(RuntimeError):
    """Raised when the underlying executor fails mid-run.

    Carries enough context (run/agent id, the run's new persisted
    status, its error category/retryability, and where its partial
    event log lives) for the caller to report a useful failure summary
    and decide whether `resume` is worth trying.
    """

    def __init__(
        self,
        *,
        task_id: str,
        run_id: str,
        agent_id: str,
        status: str,
        category: RunErrorCategory,
        retryable: bool,
        events_path: Path,
        original_error: Exception,
    ) -> None:
        super().__init__(str(original_error))
        self.task_id = task_id
        self.run_id = run_id
        self.agent_id = agent_id
        self.status = status
        self.category = category
        self.retryable = retryable
        self.events_path = events_path
        self.original_error = original_error


class RunService:
    """Coordinate validation, execution, and persistence."""

    def __init__(
        self,
        task_repository: TaskRepository,
        run_repository: RunRepository,
        agent_repository: AgentRepository,
        context_builder: RunContextBuilder,
        executor: RunExecutor,
        project_root: Path,
        *,
        approval_continuation_preparation_service: (
            ApprovalContinuationPreparationService | None
        ) = None,
        approval_application_service: (
            ApprovalApplicationService | None
        ) = None,
        run_continuation_attempt_repository: (
            RunContinuationAttemptRepository | None
        ) = None,
    ) -> None:
        self._task_repository = task_repository
        self._run_repository = run_repository
        self._agent_repository = agent_repository
        self._context_builder = context_builder
        self._executor = executor
        self._project_root = project_root
        self._change_snapshot_builder = ChangeSnapshotBuilder()
        self._snapshot_repository = SnapshotRepository()
        # All three optional, defaulting to None - "approval
        # continuation is not configured" (5E-5D-6C), matching
        # LLMRunExecutor's own approval_gate convention: every
        # existing caller/test that builds a RunService without them
        # keeps identical behavior (execute()/resume()/get_run()/
        # decide_review() never touch these), and
        # resume_after_approval() itself refuses outright
        # (RunContinuationNotConfiguredError) rather than silently
        # degrading to some partially-gated behavior if any one of
        # them is missing. No separate
        # run_continuation_checkpoint_repository field here -
        # ApprovalContinuationPreparationService's own constructor
        # already requires one (non-optional), so requiring a valid
        # approval_continuation_preparation_service transitively
        # guarantees checkpoint-repository wiring without RunService
        # holding a second, redundant reference to it.
        self._approval_continuation_preparation_service = (
            approval_continuation_preparation_service
        )
        self._approval_application_service = (
            approval_application_service
        )
        self._run_continuation_attempt_repository = (
            run_continuation_attempt_repository
        )

    def execute(self, task_id: str) -> RunServiceResult:
        task = self._task_repository.load(task_id)
        run_id = task.current_run_id

        if not run_id:
            raise ValueError(
                f"Task {task_id} has no current_run_id"
            )

        run = self._run_repository.load(task.id, run_id)

        if run.status != "in_progress":
            if run.is_completed():
                raise ValueError(
                    f"Run {run.id} has already been completed"
                )

            raise ValueError(
                f"Run {run.id} has status '{run.status}' and cannot "
                f"be executed directly; use `resume {run.id}` to "
                "retry it as a new run."
            )

        if run.task_id != task.id:
            raise ValueError(
                f"Run {run.id} belongs to task "
                f"{run.task_id}, not {task.id}"
            )

        if not task.is_agent_assigned(run.agent_id):
            raise ValueError(
                f"Agent {run.agent_id} is not assigned "
                f"to task {task.id}"
            )

        agent = self._agent_repository.load(run.agent_id)

        if agent.status != "ready":
            raise ValueError(
                f"Agent {agent.id} is not ready"
            )

        context = self._context_builder.build(
            task=task,
            run=run,
            agent=agent,
        )

        try:
            result = self._executor.execute(context)
        except Exception as error:
            raise self._fail_run(
                task=task,
                run=run,
                error=error,
            ) from error

        self._run_repository.write_output(
            task.id,
            run.id,
            result.output_markdown,
        )

        self._run_repository.write_summary(
            task.id,
            run.id,
            result.summary_markdown,
        )

        if result.metadata.get("waiting_for_approval"):
            return self._pause_run(
                task=task, run=run, result=result
            )

        return self._complete_run(task=task, run=run, result=result)

    def resume(self, run_id: str) -> RunServiceResult:
        """Retry a run that never reached a terminal state.

        Each Run represents a single execution attempt: resuming does
        not reuse the old run_id, it marks the old run `interrupted`
        (if a crashed process left it stuck on `in_progress`) and
        creates a brand new Run (`retry_of` pointing at the old one,
        reusing the same input.md) which is then actually executed.

        Guarded against approval continuation (5E-5D-6C-1) only when
        run_continuation_attempt_repository is configured - a
        RunService built without any approval-continuation awareness
        at all (most existing callers/tests) gets exactly its prior
        behavior, unchanged, since there is nothing here for it to
        check against. When it *is* configured, the eligibility check
        and the old-run/new-run transition both run inside the same
        run_guard() resume_after_approval() itself uses, scoped to
        run_id - the read-only "is this Run resumable" check happens
        under the identical lock a concurrent resume_after_approval()
        call would be holding, so the two can never interleave:
        either this sees the Run mid-continuation and is correctly
        blocked, or it is not and genuinely owns the decision.
        Finally, find_incomplete() is consulted explicitly, not left
        to RESUMABLE_STATUSES alone - belt-and-suspenders, since every
        status resume_after_approval()'s own code paths can currently
        produce is already excluded from RESUMABLE_STATUSES, but nothing
        prevents a future status or entry path from changing that
        silently.
        """

        task = self._find_task_for_run(run_id)

        if task is None:
            raise ValueError(f"No task owns run {run_id}")

        if self._run_continuation_attempt_repository is not None:
            with self._run_continuation_attempt_repository.run_guard(
                task.id, run_id
            ):
                self._transition_resume_locked(task, run_id)
        else:
            self._transition_resume_locked(task, run_id)

        return self.execute(task.id)

    def _transition_resume_locked(
        self, task: TaskDefinition, run_id: str
    ) -> None:
        if self._run_continuation_attempt_repository is not None:
            incomplete = self._find_incomplete_attempt_or_block(
                task.id, run_id
            )

            if incomplete is not None:
                raise RunContinuationBlockedError(
                    f"Run {run_id!r} has an incomplete continuation "
                    f"attempt (approval_id={incomplete.approval_id!r}) "
                    "- refusing to create a generic retry until this "
                    "is manually reconciled"
                )

        old_run = self._run_repository.load(task.id, run_id)

        if old_run.status not in RESUMABLE_STATUSES:
            raise ValueError(
                f"Run {run_id} has status '{old_run.status}' and "
                "cannot be resumed"
            )

        if old_run.status == "in_progress":
            # Still in_progress at resume time with no process
            # actually running it means execution was cut short
            # (crash / kill) before it could persist a terminal
            # status. Record that before creating the retry attempt.
            old_run = replace(
                old_run,
                status="interrupted",
                updated_at=utc_now(),
            )
            self._run_repository.save(old_run)

        new_run_id = self._next_run_id(task.id)
        created_at = utc_now()

        new_run = RunDefinition(
            id=new_run_id,
            task_id=task.id,
            agent_id=old_run.agent_id,
            status="in_progress",
            created_at=created_at,
            updated_at=created_at,
            started_at=created_at,
            completed_at=None,
            metadata={"retry_of": old_run.id},
        )
        self._run_repository.save(new_run)

        self._run_repository.write_input(
            task.id,
            new_run_id,
            self._run_repository.read_input(task.id, old_run.id),
        )

        updated_task = replace(
            task,
            current_run_id=new_run_id,
            run_count=task.run_count + 1,
            updated_at=created_at,
        )
        self._task_repository.save(updated_task)

    def get_run(
        self,
        run_id: str,
    ) -> tuple[TaskDefinition, RunDefinition]:
        task = self._find_task_for_run(run_id)

        if task is None:
            raise ValueError(f"No task owns run {run_id}")

        run = self._run_repository.load(task.id, run_id)

        return task, run

    def decide_review(
        self,
        run_id: str,
        *,
        approved: bool,
    ) -> RunDefinition:
        _task, run = self.get_run(run_id)

        if run.status != "awaiting_review":
            raise ValueError(
                f"Run {run_id} has status '{run.status}' and is "
                "not awaiting review."
            )

        decided_run = replace(
            run,
            status="approved" if approved else "rejected",
            updated_at=utc_now(),
        )
        self._run_repository.save(decided_run)

        return decided_run

    def resume_after_approval(
        self, run_id: str, approval_id: str
    ) -> RunServiceResult:
        """Continues the SAME Run from its approval checkpoint
        (5E-5D-6C) - the run_id passed in is the run being continued,
        never replaced with a new one (contrast resume(), which always
        creates a brand-new Run). approval_id is the source approval
        the caller expects this attempt to resolve - required so a
        retry for approval B can never silently resume a later
        approval C for the same Run. RunContinuationAttemptRecord is
        itself keyed by approval_id (one file per chapter - see that
        repository's own docstring), so this is structural, not a
        field comparison that could be gotten wrong: asking about C
        when only B's chapter exists simply finds no record at all
        and proceeds to validate C fresh against prepare(); only a
        found record's task_id/run_id/approval_id are still
        cross-checked against the path they were loaded from
        (defensive, matching every other approval_id-keyed repository
        in this codebase).

        Requires every collaborator this depends on to be configured
        (RunContinuationNotConfiguredError otherwise) - this never
        silently falls back to generic resume() semantics or to an
        executor with approval gating disabled; a misconfigured
        RunService fails loudly here rather than quietly resuming
        without the guarantees this method exists to provide.

        Run-wide exclusivity (5E-5D-6C-1): before any of the steps
        below, RunContinuationAttemptRepository.run_guard() acquires an
        OS-backed, nonblocking, cross-process *and* cross-thread lock
        scoped to (task_id, run_id) alone - not approval_id. This is
        what actually closes the race two *live* callers asking about
        *different* approval_ids for the same Run would otherwise have
        (find_incomplete() followed by create_exclusive() is not, by
        itself, atomic across two different per-approval-id files).
        The lock is released automatically by the kernel the instant
        its owning process dies, so it alone cannot protect a Run
        whose previous owner crashed - that is still the CLAIMED
        attempt record's job, step 0 below, which the lock does not
        replace.

        Write ordering and crash windows (5E-5D-6C) - there is no
        multi-file transaction across any of this; each step below runs
        *inside* that guard, as a separate, already-durable write on
        its own, and a crash between any two of them is possible
        (the guard's OS lock is released the moment the process dies,
        but every persisted fact already written stays exactly as it
        was - this never half-undoes a prior step):

        0. RunContinuationAttemptRepository.find_incomplete() - a
           read-only scan for a *different*, still-CLAIMED chapter
           (a different approval_id) of this same Run. If one exists,
           this attempt is refused before anything else runs, however
           ready this approval_id's own checkpoint/request look.
        1. RunContinuationAttemptRepository.create_exclusive() - the
           one atomic-across-processes step for *this* chapter.
           Exactly one caller can ever win a fresh claim for this
           (run_id, approval_id) pair.
        2. ApprovalApplicationService.apply() - applies the pending
           decision to its one pending ToolCall, under its own
           independent atomic claim (application.json) scoped to
           approval_id. A crash here leaves this chapter's own attempt
           record CLAIMED (and apply()'s own claim in whatever state
           its own write ordering left it in - see that service's
           docstring).
        3. self._executor.resume_after_approval() - finishes the
           interrupted round and continues the LLM loop. May itself
           persist a *new* checkpoint.json and a *new* ApprovalRequest
           (if a later call also needs approval - a new chapter, with
           its own approval_id and its own future attempt record) and
           append any number of new events.jsonl lines and tool side
           effects, none of it undone if a later step fails.
        4. self._pause_run()/_complete_run()/_cancel_run() - persists
           the Run's new terminal/paused run.json (and, for
           completion, change_snapshot.json/task.json).
        5. RunContinuationAttemptRepository.complete() - marks this
           chapter's own record COMPLETED with its transition (and,
           for RUN_WAITING_FOR_APPROVAL, the new approval_id the next
           chapter will be keyed by).

        A crash at any point before step 5 finishes leaves this
        chapter's attempt record CLAIMED. Nothing in this class - or
        in generic resume(), which never touches a Run outside
        RESUMABLE_STATUSES={"in_progress","interrupted"}, none of
        which this method ever produces - will treat that Run's
        continuation as runnable again automatically: a later call
        asking about *this* approval_id finds the CLAIMED record
        directly, and a later call asking about a *new* approval_id
        (from a checkpoint/request that step 3 may have already
        written) is still caught by step 0's find_incomplete() scan,
        even though by step 3 or 4 the Run may already show that brand
        new checkpoint, a new waiting_for_approval approval_id, or a
        terminal status on disk. Only a human, reconciling manually,
        can move it forward. This is the same conservative,
        no-auto-expiry stance ApprovalApplicationService already
        established one layer down - extended here to the whole
        continuation, not just the one pending ToolCall.

        This method itself calls only JsonRepository-backed writes
        (via the repositories above) - none of them fsync, so, same as
        every other durability claim in this codebase, what is
        guaranteed is surviving a killed/crashed *process*, not a
        power loss at the storage layer mid-write.
        """

        if (
            self._approval_continuation_preparation_service is None
            or self._approval_application_service is None
            or self._run_continuation_attempt_repository is None
        ):
            raise RunContinuationNotConfiguredError(
                "RunService.resume_after_approval() requires "
                "approval_continuation_preparation_service, "
                "approval_application_service, and "
                "run_continuation_attempt_repository to all be "
                "configured"
            )

        task = self._find_task_for_run(run_id)

        if task is None:
            raise ValueError(f"No task owns run {run_id}")

        # 5E-5D-6C-1: acquired before any attempt-repository read,
        # held through applying the decision, driving the remaining
        # tool/LLM loop, finalizing the Run, and persisting the
        # completed chapter - see RunContinuationAttemptRepository.
        # run_guard()'s own docstring for why this exists alongside,
        # not instead of, the CLAIMED-record protection below.
        with self._run_continuation_attempt_repository.run_guard(
            task.id, run_id
        ):
            return self._resume_after_approval_locked(
                task, run_id, approval_id
            )

    def _resume_after_approval_locked(
        self,
        task: TaskDefinition,
        run_id: str,
        approval_id: str,
    ) -> RunServiceResult:
        existing_attempt = self._try_load_attempt_or_block(
            task.id, run_id, approval_id
        )

        if existing_attempt is not None:
            return self._resolve_existing_attempt(
                task=task,
                run_id=run_id,
                approval_id=approval_id,
                attempt=existing_attempt,
            )

        # No chapter exists yet for *this* approval_id - but a
        # different, earlier chapter for the same Run (a different
        # approval_id) might still be incomplete. That must block a
        # fresh attempt here too, regardless of how ready this
        # approval_id's own checkpoint/request look (5E-5D-6C: "a
        # newly written waiting checkpoint must not hide an unfinished
        # previous attempt").
        incomplete = self._find_incomplete_attempt_or_block(
            task.id, run_id
        )

        if incomplete is not None:
            raise RunContinuationBlockedError(
                f"Run {run_id!r} already has an incomplete "
                f"continuation attempt (approval_id="
                f"{incomplete.approval_id!r}) - refusing to continue "
                "automatically until this is manually reconciled"
            )

        # Cheap, read-only validation before any claim is attempted -
        # mirrors ApprovalApplicationService.apply()'s own ordering,
        # so an ordinary wrong-approval-id/wrong-status call never
        # leaves a stuck CLAIMED attempt record behind.
        preparation = (
            self._approval_continuation_preparation_service.prepare(
                task.id, run_id
            )
        )

        if preparation.approval_id != approval_id:
            raise RunContinuationMismatchError(
                f"Prepared approval_id {preparation.approval_id!r} "
                f"does not match requested {approval_id!r}"
            )

        claim = RunContinuationAttemptRecord(
            schema_version=ATTEMPT_RECORD_SCHEMA_VERSION,
            task_id=task.id,
            run_id=run_id,
            approval_id=approval_id,
            status=RunContinuationAttemptStatus.CLAIMED,
        )

        try:
            created = (
                self._run_continuation_attempt_repository
                .create_exclusive(claim)
            )
        except Exception as exc:
            raise RunContinuationPersistenceError(
                "Failed to persist a continuation attempt claim for "
                f"run {run_id!r} - no decision was applied"
            ) from exc

        if not created:
            lost_race = self._try_load_attempt_or_block(
                task.id, run_id, approval_id
            )
            assert lost_race is not None

            return self._resolve_existing_attempt(
                task=task,
                run_id=run_id,
                approval_id=approval_id,
                attempt=lost_race,
            )

        # This call now exclusively owns this Run's continuation.
        # Re-validate before applying anything - state may have
        # changed between the prepare() call above and winning the
        # claim.
        revalidated = (
            self._approval_continuation_preparation_service.prepare(
                task.id, run_id
            )
        )

        if revalidated.approval_id != approval_id:
            raise RunContinuationMismatchError(
                "Re-validated preparation for run "
                f"{run_id!r} no longer matches the approval "
                f"{approval_id!r} this attempt was claimed for - "
                "refusing to continue"
            )

        try:
            service_result, transition, new_approval_id = (
                self._drive_continuation(
                    task=task,
                    run_id=run_id,
                    approval_id=approval_id,
                    checkpoint=revalidated.checkpoint,
                )
            )
        except Exception as exc:
            raise RunContinuationFailedError(
                f"Continuing run {run_id!r} raised unexpectedly - "
                "the attempt is preserved and will not be "
                "auto-retried"
            ) from exc

        try:
            self._run_continuation_attempt_repository.complete(
                task.id,
                run_id,
                approval_id,
                transition=transition,
                new_approval_id=new_approval_id,
            )
        except Exception as exc:
            raise RunContinuationPersistenceError(
                f"Run {run_id!r} was continued to transition "
                f"{transition!r} but persisting the attempt's own "
                "completion failed - the claim is preserved and will "
                "not be auto-retried"
            ) from exc

        return service_result

    def _try_load_attempt_or_block(
        self, task_id: str, run_id: str, approval_id: str
    ) -> RunContinuationAttemptRecord | None:
        """try_load(), with a malformed/unreadable chapter file treated
        as "blocked" rather than letting a raw parsing exception escape
        (5E-5D-6C hardening) - create_exclusive() makes a claim file
        exist and only *then* writes its content, so a reader landing
        in that narrow window (another process mid-write, not yet
        flushed) can see a transiently empty/partial file. This is the
        same case this method's own docstring already names
        ("incomplete/malformed claim records also block dispatch") -
        converting the parse failure into RunContinuationBlockedError
        here makes that documented behavior actually hold under a real
        concurrent write, not just for a permanently corrupted file."""

        try:
            return (
                self._run_continuation_attempt_repository.try_load(
                    task_id, run_id, approval_id
                )
            )
        except Exception as exc:
            raise RunContinuationBlockedError(
                f"Run {run_id!r} has a malformed or unreadable "
                f"continuation attempt record for approval_id="
                f"{approval_id!r} - refusing to continue until this "
                "is manually reconciled"
            ) from exc

    def _find_incomplete_attempt_or_block(
        self, task_id: str, run_id: str
    ) -> RunContinuationAttemptRecord | None:
        try:
            return (
                self._run_continuation_attempt_repository
                .find_incomplete(task_id, run_id)
            )
        except Exception as exc:
            raise RunContinuationBlockedError(
                f"Run {run_id!r} has a malformed or unreadable "
                "continuation attempt record - refusing to continue "
                "until this is manually reconciled"
            ) from exc

    def _resolve_existing_attempt(
        self,
        *,
        task: TaskDefinition,
        run_id: str,
        approval_id: str,
        attempt: RunContinuationAttemptRecord,
    ) -> RunServiceResult:
        # Defensive only - try_load()/create_exclusive() already key
        # this record by (task_id, run_id, approval_id), so a mismatch
        # here can only mean a corrupted file, not a caller asking
        # about the wrong chapter (that case simply finds no record at
        # all - see resume_after_approval()).
        if (
            attempt.task_id != task.id
            or attempt.run_id != run_id
            or attempt.approval_id != approval_id
        ):
            raise RunContinuationMismatchError(
                "Existing RunContinuationAttemptRecord identity "
                f"(task_id={attempt.task_id!r}, "
                f"run_id={attempt.run_id!r}, "
                f"approval_id={attempt.approval_id!r}) does not "
                f"match requested (task_id={task.id!r}, "
                f"run_id={run_id!r}, approval_id={approval_id!r})"
            )

        if attempt.status is RunContinuationAttemptStatus.COMPLETED:
            return self._result_from_completed_attempt(task, attempt)

        raise RunContinuationBlockedError(
            f"Run {run_id!r} already has an incomplete continuation "
            "attempt - refusing to continue automatically until this "
            "is manually reconciled"
        )

    def _drive_continuation(
        self,
        *,
        task: TaskDefinition,
        run_id: str,
        approval_id: str,
        checkpoint: RunContinuationCheckpoint,
    ) -> tuple[
        RunServiceResult, RunContinuationTransition, str | None
    ]:
        outcome = self._approval_application_service.apply(
            task.id, run_id, approval_id
        )

        # Still "waiting_for_approval" - resume_after_approval() never
        # flips a Run's status to anything else before this point, so
        # ApprovalApplicationService.apply()'s own internal
        # preparation (requiring exactly that status) remains valid
        # throughout steps 1-3 of this method's own docstring.
        run = self._run_repository.load(task.id, run_id)
        agent = self._agent_repository.load(run.agent_id)
        context = self._context_builder.build(
            task=task, run=run, agent=agent
        )

        if not isinstance(
            self._executor, ApprovalContinuationCapableExecutor
        ):
            raise RunContinuationNotConfiguredError(
                "The configured RunExecutor does not implement "
                "approval-aware continuation "
                "(ApprovalContinuationCapableExecutor) - refusing to "
                "fall back to a generic or ungated resume"
            )

        result = self._executor.resume_after_approval(
            context, checkpoint, outcome
        )

        self._run_repository.write_output(
            task.id, run_id, result.output_markdown
        )
        self._run_repository.write_summary(
            task.id, run_id, result.summary_markdown
        )

        if result.metadata.get("cancelled"):
            service_result = self._cancel_run(
                task=task, run=run, result=result
            )
            return (
                service_result,
                RunContinuationTransition.RUN_CANCELLED,
                None,
            )

        if result.metadata.get("waiting_for_approval"):
            service_result = self._pause_run(
                task=task, run=run, result=result
            )
            return (
                service_result,
                RunContinuationTransition.RUN_WAITING_FOR_APPROVAL,
                service_result.approval_id,
            )

        service_result = self._complete_run(
            task=task, run=run, result=result
        )
        return (
            service_result,
            RunContinuationTransition.RUN_COMPLETED,
            None,
        )

    def _result_from_completed_attempt(
        self,
        task: TaskDefinition,
        attempt: RunContinuationAttemptRecord,
    ) -> RunServiceResult:
        run = self._run_repository.load(task.id, attempt.run_id)

        return RunServiceResult(
            task_id=task.id,
            run_id=attempt.run_id,
            agent_id=run.agent_id,
            status=run.status,
            output_path=self._run_repository.get_output_file(
                task.id, attempt.run_id
            ),
            summary_path=self._run_repository.get_summary_file(
                task.id, attempt.run_id
            ),
            events_path=self._run_repository.get_events_file(
                task.id, attempt.run_id
            ),
            approval_id=attempt.new_approval_id,
        )

    def _complete_run(
        self,
        *,
        task: TaskDefinition,
        run: RunDefinition,
        result: RunExecutionResult,
    ) -> RunServiceResult:
        run_directory = self._run_repository.get_run_dir(
            task.id,
            run.id,
        )
        snapshot = self._change_snapshot_builder.build(
            run_id=run.id,
            run_directory=run_directory,
            repository_root=self._project_root,
        )
        # Persisted so `review` later shows the state as it was right
        # after this Run finished, not a live recomputation against
        # whatever the repository looks like at review time.
        #
        # Built from this Run's full events.jsonl (ChangeSnapshotBuilder
        # reads file_mutation/tool_result events from it directly, not
        # from any separately-tracked "before" baseline) - so a Run
        # that paused for approval mid-execution and was later
        # continued via resume_after_approval() still gets a snapshot
        # covering its *entire* history, pre-pause and post-resume
        # alike, as long as nothing in between truncated that file.
        # resume_after_approval()'s own event sink deliberately opens
        # events.jsonl with truncate_existing=False for exactly this
        # reason (see LLMAgentRunExecutor.resume_after_approval()).
        self._snapshot_repository.save(run_directory, snapshot)

        review_required = requires_review(
            agent_id=run.agent_id,
            snapshot=snapshot,
        )

        completed_at = utc_now()

        finished_run = replace(
            run,
            status=(
                "awaiting_review"
                if review_required
                else "completed"
            ),
            updated_at=completed_at,
            completed_at=completed_at,
            metadata={
                **run.metadata,
                "review_required": review_required,
                "changed_files": snapshot.changed_files,
            },
        )

        updated_task = replace(
            task,
            updated_at=completed_at,
        )

        self._run_repository.save(finished_run)
        self._task_repository.save(updated_task)

        return RunServiceResult(
            task_id=task.id,
            run_id=run.id,
            agent_id=run.agent_id,
            status=finished_run.status,
            output_path=self._run_repository.get_output_file(
                task.id,
                run.id,
            ),
            summary_path=self._run_repository.get_summary_file(
                task.id,
                run.id,
            ),
            events_path=self._run_repository.get_events_file(
                task.id,
                run.id,
            ),
            llm_rounds=result.metadata.get("llm_rounds"),
            tool_rounds=result.metadata.get("tool_rounds"),
            tool_calls=result.metadata.get("tool_calls"),
            total_input_tokens=result.metadata.get(
                "total_input_tokens"
            ),
            total_output_tokens=result.metadata.get(
                "total_output_tokens"
            ),
        )

    def _cancel_run(
        self,
        *,
        task: TaskDefinition,
        run: RunDefinition,
        result: RunExecutionResult,
    ) -> RunServiceResult:
        """Persists a terminal "cancelled" RunStatus (5E-5D-6C) - a new
        status this codebase had no prior convention for (CANCEL was
        previously only a recorded ApprovalDecision, never something
        that reached RunStatus at all). Modeled as a close sibling of
        _fail_run's interrupted/failed and _pause_run's
        waiting_for_approval: one more replace(run, status=..., ...)
        persisted through the same RunRepository, nothing more exotic.

        Deliberately not resumable - "cancelled" is not in
        RESUMABLE_STATUSES, so generic resume() already refuses it
        with its own plain ValueError, the same way it already refuses
        "completed"/"awaiting_review"/"waiting_for_approval". No
        ChangeSnapshot/review runs for a cancelled Run in this stage -
        whatever tool effects happened before the pause remain on disk
        untouched (nothing here reverts them), but judging them is left
        to a later stage, not fabricated here.
        """

        cancelled_at = utc_now()

        cancelled_run = replace(
            run,
            status="cancelled",
            updated_at=cancelled_at,
            completed_at=cancelled_at,
        )
        self._run_repository.save(cancelled_run)

        return RunServiceResult(
            task_id=task.id,
            run_id=run.id,
            agent_id=run.agent_id,
            status=cancelled_run.status,
            output_path=self._run_repository.get_output_file(
                task.id,
                run.id,
            ),
            summary_path=self._run_repository.get_summary_file(
                task.id,
                run.id,
            ),
            events_path=self._run_repository.get_events_file(
                task.id,
                run.id,
            ),
            llm_rounds=result.metadata.get("llm_rounds"),
            tool_rounds=result.metadata.get("tool_rounds"),
            tool_calls=result.metadata.get("tool_calls"),
            total_input_tokens=result.metadata.get(
                "total_input_tokens"
            ),
            total_output_tokens=result.metadata.get(
                "total_output_tokens"
            ),
        )

    def _pause_run(
        self,
        *,
        task: TaskDefinition,
        run: RunDefinition,
        result: RunExecutionResult,
    ) -> RunServiceResult:
        """Persists RunStatus.WAITING_FOR_APPROVAL (5E-5D-4B) - not a
        failure (no RunExecutionFailedError, no classify_error()) and
        not a completion (no ChangeSnapshot/review, since nothing
        this run did has been judged finished yet - a later stage
        decides how review interacts with a partially-executed,
        paused run). completed_at is deliberately left unset, same as
        _fail_run's interrupted/failed - this is not a terminal
        state.
        """

        approval_id = result.metadata.get("approval_id")
        tool_call_id = result.metadata.get("tool_call_id")
        paused_at = utc_now()

        paused_run = replace(
            run,
            status="waiting_for_approval",
            updated_at=paused_at,
            metadata={
                **run.metadata,
                "approval_id": approval_id,
                "tool_call_id": tool_call_id,
            },
        )
        self._run_repository.save(paused_run)

        return RunServiceResult(
            task_id=task.id,
            run_id=run.id,
            agent_id=run.agent_id,
            status=paused_run.status,
            output_path=self._run_repository.get_output_file(
                task.id,
                run.id,
            ),
            summary_path=self._run_repository.get_summary_file(
                task.id,
                run.id,
            ),
            events_path=self._run_repository.get_events_file(
                task.id,
                run.id,
            ),
            llm_rounds=result.metadata.get("llm_rounds"),
            tool_rounds=result.metadata.get("tool_rounds"),
            tool_calls=result.metadata.get("tool_calls"),
            total_input_tokens=result.metadata.get(
                "total_input_tokens"
            ),
            total_output_tokens=result.metadata.get(
                "total_output_tokens"
            ),
            approval_id=approval_id,
        )

    def _fail_run(
        self,
        *,
        task: TaskDefinition,
        run: RunDefinition,
        error: Exception,
    ) -> RunExecutionFailedError:
        category = classify_error(error)
        retryable = is_retryable(category)
        new_status = "interrupted" if retryable else "failed"
        failed_at = utc_now()

        failed_run = replace(
            run,
            status=new_status,
            updated_at=failed_at,
            metadata={
                **run.metadata,
                "error_category": category,
                "error_message": str(error),
                "retryable": retryable,
            },
        )
        self._run_repository.save(failed_run)

        return RunExecutionFailedError(
            task_id=task.id,
            run_id=run.id,
            agent_id=run.agent_id,
            status=new_status,
            category=category,
            retryable=retryable,
            events_path=self._run_repository.get_events_file(
                task.id,
                run.id,
            ),
            original_error=error,
        )

    def _find_task_for_run(
        self,
        run_id: str,
    ) -> TaskDefinition | None:
        for task in self._task_repository.list_all():
            if run_id in self._run_repository.list_run_ids(task.id):
                return task

        return None

    def _next_run_id(self, task_id: str) -> str:
        max_index = 0

        for existing_run_id in self._run_repository.list_run_ids(
            task_id
        ):
            prefix = "run-"

            if not existing_run_id.startswith(prefix):
                continue

            suffix = existing_run_id[len(prefix):]

            if suffix.isdigit():
                max_index = max(max_index, int(suffix))

        return f"run-{max_index + 1:03d}"
