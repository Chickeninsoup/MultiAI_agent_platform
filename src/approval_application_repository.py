from __future__ import annotations

import dataclasses
from pathlib import Path

from src.approval_application_errors import (
    ApprovalApplicationError,
)
from src.approval_application_outcome import ApprovalApplicationOutcome
from src.approval_application_record import ApprovalApplicationRecord
from src.approval_application_status import ApprovalApplicationStatus
from src.approval_id import validate_approval_id
from src.clock import utc_now
from src.repositories import JsonRepository


class ApprovalApplicationRepository:
    """Persists ApprovalApplicationRecords under
    tasks_dir/approvals/<approval_id>/application.json (5E-5D-6B) -
    the same per-approval directory ApprovalRequestRepository/
    ApprovalResolutionRepository already own, one more file alongside
    request.json/resolution.json rather than a new top-level tree.

    create_exclusive() is the one method in this class with a hard
    safety requirement: it must be impossible for two concurrent
    callers (different processes or threads) to both believe they
    created a fresh claim. It delegates entirely to
    JsonRepository.create_exclusive() (O_CREAT | O_EXCL) rather than
    an exists()-check-then-save() here - see that method's own
    docstring for why the latter is unsafe.

    try_load() returns None only for "no file at this path" - a
    present-but-corrupt/malformed file (bad JSON, or JSON that fails
    ApprovalApplicationRecord's own __post_init__ invariants) is
    deliberately *not* folded into that None case and propagates
    instead. A malformed claim file still means a claim exists; silently
    treating it as "no claim" would let a caller re-attempt dispatch
    over a record that might already describe real, completed work -
    exactly the kind of claim this class exists to make impossible to
    ignore. ApprovalApplicationService.apply() uses this to also
    block automatic retry over a malformed-but-present record.

    get_application_file() validates approval_id (src/approval_id.py)
    before building a Path, the same choke-point convention
    ApprovalRequestRepository/ApprovalResolutionRepository already
    use for every one of their own path-building methods.
    """

    def __init__(self, tasks_dir: Path) -> None:
        self._tasks_dir = tasks_dir

    def get_application_file(self, approval_id: str) -> Path:
        validate_approval_id(approval_id)

        return (
            self._tasks_dir
            / "approvals"
            / approval_id
            / "application.json"
        )

    def try_load(
        self, approval_id: str
    ) -> ApprovalApplicationRecord | None:
        application_file = self.get_application_file(approval_id)

        if not application_file.exists():
            return None

        data = JsonRepository.load(application_file)

        return ApprovalApplicationRecord.from_dict(data)

    def create_exclusive(
        self, record: ApprovalApplicationRecord
    ) -> bool:
        if record.status is not ApprovalApplicationStatus.CLAIMED:
            raise ValueError(
                "ApprovalApplicationRepository.create_exclusive() "
                "requires a CLAIMED record - use complete() to attach "
                "an outcome to an already-claimed record"
            )

        return JsonRepository.create_exclusive(
            self.get_application_file(record.approval_id),
            record.to_dict(),
        )

    def complete(
        self,
        approval_id: str,
        outcome: ApprovalApplicationOutcome,
    ) -> ApprovalApplicationRecord:
        existing = self.try_load(approval_id)

        if existing is None:
            raise ApprovalApplicationError(
                "ApprovalApplicationRepository.complete() requires an "
                f"existing claimed record for {approval_id!r}"
            )

        if existing.status is not ApprovalApplicationStatus.CLAIMED:
            raise ApprovalApplicationError(
                f"ApprovalApplicationRecord {approval_id!r} is not "
                f"CLAIMED (status={existing.status!r}) - refusing to "
                "overwrite its outcome"
            )

        completed = dataclasses.replace(
            existing,
            status=ApprovalApplicationStatus.COMPLETED,
            outcome=outcome,
            completed_at=utc_now(),
        )

        JsonRepository.save(
            self.get_application_file(approval_id),
            completed.to_dict(),
        )

        return completed
