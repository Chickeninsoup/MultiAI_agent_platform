from __future__ import annotations

from pathlib import Path

from src.repositories import JsonRepository
from src.runtime_approval_request import RuntimeApprovalRequest


class RuntimeApprovalRepository:
    """Persists RuntimeApprovalRequests under
    tasks/<task_id>/runtime_approval.json (5E-5C-8D-3) - a distinct
    file from approval.json (Plan Approval's ApprovalRecord), so a
    runtime recovery approval can never collide with or overwrite the
    plan-approval record for the same task (5E-5C-8D-1 audit finding).

    save() overwrites whatever runtime approval already exists for
    that task - first version supports exactly one active recovery
    approval per Task, same simplification ExecutionCheckpointRepository
    makes for checkpoints; multi-approval history is a later concern,
    not this stage's.

    load() raises FileNotFoundError for an unknown task_id, matching
    ExecutionCheckpointRepository's convention (not PlanRepository/
    ApprovalRepository's get()-returns-None) - a missing runtime
    approval is not a normal query result the way "has this task ever
    been approved" is.
    """

    def __init__(self, tasks_dir: Path) -> None:
        self._tasks_dir = tasks_dir

    def get_runtime_approval_file(self, task_id: str) -> Path:
        return self._tasks_dir / task_id / "runtime_approval.json"

    def save(self, request: RuntimeApprovalRequest) -> None:
        JsonRepository.save(
            self.get_runtime_approval_file(request.task_id),
            request.to_dict(),
        )

    def load(self, task_id: str) -> RuntimeApprovalRequest:
        data = JsonRepository.load(
            self.get_runtime_approval_file(task_id)
        )

        return RuntimeApprovalRequest.from_dict(data)

    def delete(self, task_id: str) -> None:
        self.get_runtime_approval_file(task_id).unlink(missing_ok=True)
