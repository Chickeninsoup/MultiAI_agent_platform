from __future__ import annotations

from pathlib import Path

from src.approval_id import validate_approval_id
from src.approval_request import ApprovalRequest
from src.repositories import JsonRepository


class ApprovalRequestRepository:
    """Persists ApprovalRequests under
    tasks_dir/approvals/<approval_id>/request.json (5E-5D-2).

    Keyed by approval_id, not task_id - ApprovalRequest (5E-5D-1)
    carries run_id, not task_id, and approval_id is the one
    identifier this model guarantees is unique (ApprovalStore enforces
    that uniqueness on create(), this repository does not). Still
    rooted at tasks_dir, the same directory every other repository in
    this codebase takes, rather than an entirely separate top-level
    tree - "approvals" just sits alongside the task-* directories
    tasks_dir already holds (task directories are always named
    task-YYYYMMDD-NNN, so there's no collision risk).

    Written once at creation and never rewritten afterward - resolving
    an ApprovalRequest never touches this file. RESOLVED is derived by
    ApprovalStore from whether a resolution exists
    (ApprovalResolutionRepository), not persisted here - see
    ApprovalStore's docstring for why. save() therefore has exactly
    one caller in this codebase's current code: ApprovalStore.create().

    load() raises FileNotFoundError for an unknown approval_id -
    matching ExecutionCheckpointRepository/RuntimeApprovalRepository's
    convention (a requested-by-id lookup that fails is a caller error
    worth surfacing - ApprovalStore wraps this into
    ApprovalRequestNotFoundError one layer up), not PlanRepository/
    ApprovalRepository's get()-returns-None convention.

    get_approval_dir() validates approval_id (src/approval_id.py)
    before building a Path from it (5E-5D-4A-1) - every other method
    here (save/load/exists/list_all) funnels through it, so this is
    the single choke point that protects all of them; a caller cannot
    reach save()/load()/exists() with a validated Path built from an
    unvalidated id. This matters even for load()/exists() (read-only
    lookups), not only save() - ApprovalStore.get()/resolve() pass a
    caller-supplied approval_id straight through to load(), so an
    unvalidated read path is just as real an escape route as an
    unvalidated write path.
    """

    def __init__(self, tasks_dir: Path) -> None:
        self._tasks_dir = tasks_dir

    def get_approval_dir(self, approval_id: str) -> Path:
        validate_approval_id(approval_id)

        return self._tasks_dir / "approvals" / approval_id

    def get_request_file(self, approval_id: str) -> Path:
        return self.get_approval_dir(approval_id) / "request.json"

    def exists(self, approval_id: str) -> bool:
        return self.get_request_file(approval_id).exists()

    def save(self, request: ApprovalRequest) -> None:
        JsonRepository.save(
            self.get_request_file(request.approval_id),
            request.to_dict(),
        )

    def load(self, approval_id: str) -> ApprovalRequest:
        data = JsonRepository.load(self.get_request_file(approval_id))

        return ApprovalRequest.from_dict(data)

    def list_all(self) -> list[ApprovalRequest]:
        approvals_dir = self._tasks_dir / "approvals"

        if not approvals_dir.exists():
            return []

        return [
            self.load(approval_dir.name)
            for approval_dir in sorted(approvals_dir.iterdir())
            if approval_dir.is_dir()
            and self.get_request_file(approval_dir.name).exists()
        ]
