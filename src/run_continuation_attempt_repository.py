from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.approval_id import validate_approval_id
from src.clock import utc_now
from src.process_file_lock import ProcessFileLockBusyError, process_file_lock
from src.repositories import JsonRepository
from src.run_continuation_attempt_errors import (
    RunContinuationBlockedError,
    RunContinuationError,
)
from src.run_continuation_attempt_record import (
    RunContinuationAttemptRecord,
)
from src.run_continuation_attempt_status import (
    RunContinuationAttemptStatus,
)
from src.run_continuation_transition import RunContinuationTransition


class RunContinuationAttemptRepository:
    """Persists RunContinuationAttemptRecords under
    tasks/<task_id>/runs/<run_id>/continuation_attempts/<approval_id>.json
    (5E-5D-6C) - one file per *chapter* (one resume_after_approval()
    attempt, scoped to the one source approval_id it was asked to
    resolve), all living in a dedicated subdirectory of the same
    tasks/<task_id>/runs/<run_id>/ directory
    RunContinuationCheckpointRepository already owns.

    Why per-approval_id files, not one mutable record per run_id:
    a Run's continuation genuinely has multiple sequential chapters
    (B's attempt, then - if a later call also needs approval - C's
    attempt, and so on). Each chapter is independently, atomically
    claimable via create_exclusive() at its own path - the same
    create_exclusive()-based design ApprovalApplicationRepository
    already uses, applied one layer up. A single mutable "the attempt
    for this run" record cannot support this: once chapter B
    completes (even with transition RUN_WAITING_FOR_APPROVAL, meaning
    "a new chapter for a new approval_id now exists"), a single record
    would need an atomic compare-and-replace to move on to chapter C -
    a primitive this codebase has no equivalent of, and one this stage
    does not need to invent given the simpler per-chapter-file shape
    read the same conservative way.

    find_incomplete() is the one method that *does* need to see across
    chapters - "an unfinished previous attempt must not be hidden by a
    newly written waiting checkpoint" (5E-5D-6C) means a stuck CLAIMED
    chapter for approval_id_B must still block a fresh, otherwise
    entirely valid-looking request to continue with a *different*,
    newer approval_id_C for the same Run. It scans this run's
    continuation_attempts/ directory (cheap - at most a handful of
    chapters ever exist per Run) for any CLAIMED record, rather than
    requiring a caller to know every approval_id a Run has ever
    produced.

    try_load()/create_exclusive()/complete() otherwise mirror
    ApprovalApplicationRepository's own methods exactly - same
    reasoning for each, see that class's docstring.

    run_guard() (5E-5D-6C-1) is a different kind of protection,
    layered on top of everything above rather than replacing any of
    it: find_incomplete()/create_exclusive() alone leave a residual
    race between two *live* concurrent callers for the same run_id but
    different approval_ids - each could find_incomplete()==None and
    create_exclusive() its own distinct per-chapter file before the
    other ever looks. run_guard() closes that by giving every
    continuation attempt for one run_id (regardless of approval_id) a
    single OS-backed, cross-process, cross-thread exclusive section to
    run inside - acquired before any attempt-repository read, held
    through applying the decision, driving the LLM loop, finalizing
    the Run, and persisting the completed chapter.

    The two mechanisms answer different questions and neither
    replaces the other: run_guard() excludes *live* competing
    operations (an OS lock, released automatically the instant its
    owning process dies, by the kernel, with zero cleanup code). The
    persisted CLAIMED chapter record is what still blocks a *later*,
    non-overlapping caller after the lock has already been released by
    a crashed owner - run_guard() being free again says nothing about
    whether the Run was left in a known-good state.
    """

    DIRECTORY_NAME = "continuation_attempts"
    LOCK_FILE_NAME = "continuation.lock"

    def __init__(self, tasks_dir: Path) -> None:
        self._tasks_dir = tasks_dir

    def get_run_lock_file(self, task_id: str, run_id: str) -> Path:
        return (
            self._tasks_dir
            / task_id
            / "runs"
            / run_id
            / self.LOCK_FILE_NAME
        )

    @contextmanager
    def run_guard(self, task_id: str, run_id: str) -> Iterator[None]:
        """Exclusive ownership of *all* continuation activity for one
        (task_id, run_id), regardless of approval_id (5E-5D-6C-1) -
        see this class's own docstring for why this exists alongside,
        not instead of, find_incomplete()/create_exclusive().

        Nonblocking: a contender finding the lock already held (by
        another thread or another process) gets
        RunContinuationBlockedError immediately, the same error
        vocabulary a stuck CLAIMED attempt record already raises
        elsewhere in this stack - from a caller's perspective, "the
        Run is busy" and "the Run has an incomplete attempt" are both
        just "try again later, or reconcile manually," not two
        different concepts to handle differently.
        """

        lock_path = self.get_run_lock_file(task_id, run_id)

        try:
            with process_file_lock(lock_path):
                yield
        except ProcessFileLockBusyError as exc:
            raise RunContinuationBlockedError(
                f"Run {run_id!r} continuation is already owned "
                "elsewhere (another process or thread is inside its "
                "guarded section) - refusing to start a competing "
                "attempt"
            ) from exc

    def _attempts_dir(self, task_id: str, run_id: str) -> Path:
        return (
            self._tasks_dir
            / task_id
            / "runs"
            / run_id
            / self.DIRECTORY_NAME
        )

    def get_attempt_file(
        self, task_id: str, run_id: str, approval_id: str
    ) -> Path:
        validate_approval_id(approval_id)

        return self._attempts_dir(task_id, run_id) / f"{approval_id}.json"

    def try_load(
        self, task_id: str, run_id: str, approval_id: str
    ) -> RunContinuationAttemptRecord | None:
        attempt_file = self.get_attempt_file(
            task_id, run_id, approval_id
        )

        if not attempt_file.exists():
            return None

        data = JsonRepository.load(attempt_file)

        return RunContinuationAttemptRecord.from_dict(data)

    def find_incomplete(
        self, task_id: str, run_id: str
    ) -> RunContinuationAttemptRecord | None:
        directory = self._attempts_dir(task_id, run_id)

        if not directory.exists():
            return None

        for entry in sorted(directory.iterdir()):
            if not entry.is_file() or entry.suffix != ".json":
                continue

            record = RunContinuationAttemptRecord.from_dict(
                JsonRepository.load(entry)
            )

            if record.status is RunContinuationAttemptStatus.CLAIMED:
                return record

        return None

    def create_exclusive(
        self, record: RunContinuationAttemptRecord
    ) -> bool:
        if record.status is not RunContinuationAttemptStatus.CLAIMED:
            raise ValueError(
                "RunContinuationAttemptRepository.create_exclusive() "
                "requires a CLAIMED record - use complete() to attach "
                "a transition to an already-claimed chapter"
            )

        return JsonRepository.create_exclusive(
            self.get_attempt_file(
                record.task_id, record.run_id, record.approval_id
            ),
            record.to_dict(),
        )

    def complete(
        self,
        task_id: str,
        run_id: str,
        approval_id: str,
        *,
        transition: RunContinuationTransition,
        new_approval_id: str | None = None,
    ) -> RunContinuationAttemptRecord:
        existing = self.try_load(task_id, run_id, approval_id)

        if existing is None:
            raise RunContinuationError(
                "RunContinuationAttemptRepository.complete() requires "
                f"an existing claimed chapter for task_id={task_id!r}, "
                f"run_id={run_id!r}, approval_id={approval_id!r}"
            )

        if existing.status is not RunContinuationAttemptStatus.CLAIMED:
            raise RunContinuationError(
                "RunContinuationAttemptRecord for "
                f"approval_id={approval_id!r} is not CLAIMED "
                f"(status={existing.status!r}) - refusing to "
                "overwrite its transition"
            )

        completed = dataclasses.replace(
            existing,
            status=RunContinuationAttemptStatus.COMPLETED,
            transition=transition,
            new_approval_id=new_approval_id,
            completed_at=utc_now(),
        )

        JsonRepository.save(
            self.get_attempt_file(task_id, run_id, approval_id),
            completed.to_dict(),
        )

        return completed
