from __future__ import annotations

from pathlib import Path

from src.approval_id import validate_approval_id
from src.approval_resolution import ApprovalResolution
from src.repositories import JsonRepository


class ApprovalResolutionRepository:
    """Persists ApprovalResolutions under
    tasks_dir/approvals/<approval_id>/resolution.json (5E-5D-2) -
    deliberately a separate file from request.json, in the same
    per-approval directory ApprovalRequestRepository already uses.

    Same reasoning ApprovalRepository (Plan Approval, src/planning/)
    gives for splitting PlanRecord/ApprovalRecord into two files: a
    request is written once, by whatever proposes the action; a
    resolution is written later, by a human, possibly in a different
    process or session entirely. Splitting them means resolving never
    requires re-reading or re-writing the request (which embeds a
    full ToolCall.input payload) alongside it.

    get() returns None for an unresolved approval_id rather than
    raising - matching PlanRepository/ApprovalRepository's
    get()-returns-None convention (which fits "has this been decided
    yet," a legitimately common "not yet" case), not
    ExecutionCheckpointRepository/RuntimeApprovalRepository's raising
    load(). This is also the exact mechanism ApprovalStore reads to
    derive ApprovalStatus.PENDING vs RESOLVED: "no resolution file
    yet" and "still pending" are the same fact, so there is only one
    place this model's lifecycle is actually stored on disk.

    get_resolution_file() validates approval_id (src/approval_id.py)
    before building a Path from it (5E-5D-4A-1), same as
    ApprovalRequestRepository.get_approval_dir() - both save() and
    get() funnel through it here, so an invalid id raises
    InvalidApprovalIdError immediately rather than get() silently
    returning None (which would look identical to a normal "not
    resolved yet" result and could mask a path-traversal attempt as
    an ordinary miss).
    """

    def __init__(self, tasks_dir: Path) -> None:
        self._tasks_dir = tasks_dir

    def get_resolution_file(self, approval_id: str) -> Path:
        validate_approval_id(approval_id)

        return (
            self._tasks_dir
            / "approvals"
            / approval_id
            / "resolution.json"
        )

    def save(self, resolution: ApprovalResolution) -> None:
        JsonRepository.save(
            self.get_resolution_file(resolution.approval_id),
            resolution.to_dict(),
        )

    def get(self, approval_id: str) -> ApprovalResolution | None:
        resolution_file = self.get_resolution_file(approval_id)

        if not resolution_file.exists():
            return None

        data = JsonRepository.load(resolution_file)

        return ApprovalResolution.from_dict(data)
