from __future__ import annotations

import dataclasses
from typing import Any

from src.approval_errors import (
    ApprovalAlreadyResolvedError,
    ApprovalRequestNotFoundError,
    DuplicateApprovalRequestError,
    MismatchedApprovalResolutionError,
)
from src.approval_request import ApprovalRequest
from src.approval_request_repository import ApprovalRequestRepository
from src.approval_resolution import ApprovalResolution
from src.approval_resolution_repository import (
    ApprovalResolutionRepository,
)
from src.approval_status import ApprovalStatus
from src.run_events import NullRunEventSink, RunEventSink


class ApprovalStore:
    """Owns the ApprovalRequest/ApprovalResolution persisted lifecycle
    and its audit trail (5E-5D-2) - create, look up, list pending,
    resolve, and nothing past that. Does not touch RecoveryExecutor,
    does not run/execute a proposed_action, does not resume anything -
    "a human decided" is the entire scope, matching how
    RuntimeApprovalService and RecoveryContinuationService stay split
    for the same reason (src/runtime_approval_service.py,
    src/recovery_continuation_service.py).

    Status projection (Option A, not Option B - see 5E-5D-2 task
    framing): RESOLVED is derived from whether an ApprovalResolution
    exists for an approval_id, not persisted as a rewritten
    ApprovalRequest snapshot. request.json is written exactly once, at
    create(), and this class never rewrites it afterward - "do not
    mutate the original frozen ApprovalRequest in place" holds at the
    storage layer too, not just in memory. get()/list_pending()
    compute the returned ApprovalRequest.status live
    (dataclasses.replace, never file-persisted) by checking
    ApprovalResolutionRepository.get(). This was chosen over the
    alternative - replacing and re-saving the request on resolve(),
    which is what RuntimeApprovalService does for its own status field
    - specifically because it leaves exactly one place this model's
    lifecycle is actually stored on disk: whether resolution.json
    exists. Two files that both encode status (a rewritten request
    plus a resolution) could disagree if a resolve() were ever
    interrupted partway between writing them; a single derived source
    of truth cannot.

    Every method that takes an approval_id and finds nothing wraps the
    repository's FileNotFoundError into ApprovalRequestNotFoundError,
    matching TaskCompletionService's wrap of TaskRepository.load()
    (src/planning/task_completion_service.py) - a caller of this Store
    never needs to catch a raw filesystem exception to handle "no such
    approval."

    event_sink defaults to NullRunEventSink(), matching
    LLMRunExecutor's own default (src/llm_executor.py) - a Store built
    without one behaves exactly as if it emitted nothing, so tests/
    callers that don't care about the audit trail don't need to wire a
    sink just to construct this class. Reuses the existing
    RunEventSink protocol/JsonlRunEventSink implementation
    (src/run_events.py) rather than a new event-writing mechanism -
    which physical events.jsonl file a real JsonlRunEventSink instance
    points at is entirely the caller's concern. ApprovalRequest carries
    run_id but not task_id (5E-5D-1), and resolving task_id from a
    run_id is the same lookup RunService.resume()/RunQueryService.
    inspect_run() already do elsewhere in this codebase - not
    reimplemented here; this class only ever calls event_sink.emit().
    """

    def __init__(
        self,
        request_repository: ApprovalRequestRepository,
        resolution_repository: ApprovalResolutionRepository,
        event_sink: RunEventSink | None = None,
    ) -> None:
        self._request_repository = request_repository
        self._resolution_repository = resolution_repository
        self._event_sink = (
            event_sink
            if event_sink is not None
            else NullRunEventSink()
        )

    def create(self, request: ApprovalRequest) -> ApprovalRequest:
        if self._request_repository.exists(request.approval_id):
            raise DuplicateApprovalRequestError(
                "Approval request already exists: "
                f"{request.approval_id!r}"
            )

        self._request_repository.save(request)
        self._event_sink.emit(_requested_event(request))

        return request

    def get(self, approval_id: str) -> ApprovalRequest:
        request = self._load_request(approval_id)

        if self._resolution_repository.get(approval_id) is not None:
            return dataclasses.replace(
                request, status=ApprovalStatus.RESOLVED
            )

        return request

    def get_resolution(
        self, approval_id: str
    ) -> ApprovalResolution | None:
        return self._resolution_repository.get(approval_id)

    def list_pending(
        self, run_id: str | None = None
    ) -> list[ApprovalRequest]:
        pending: list[ApprovalRequest] = []

        for request in self._request_repository.list_all():
            if (
                self._resolution_repository.get(request.approval_id)
                is not None
            ):
                continue

            if run_id is not None and request.run_id != run_id:
                continue

            pending.append(request)

        return pending

    def resolve(
        self, approval_id: str, resolution: ApprovalResolution
    ) -> ApprovalResolution:
        if resolution.approval_id != approval_id:
            raise MismatchedApprovalResolutionError(
                f"Resolution approval_id {resolution.approval_id!r} "
                f"does not match approval_id {approval_id!r}"
            )

        request = self._load_request(approval_id)

        if self._resolution_repository.get(approval_id) is not None:
            raise ApprovalAlreadyResolvedError(
                f"Approval request already resolved: {approval_id!r}"
            )

        self._resolution_repository.save(resolution)
        self._event_sink.emit(_resolved_event(request, resolution))

        return resolution

    def _load_request(self, approval_id: str) -> ApprovalRequest:
        try:
            return self._request_repository.load(approval_id)
        except FileNotFoundError as exc:
            raise ApprovalRequestNotFoundError(
                f"Approval request not found: {approval_id!r}"
            ) from exc


def _requested_event(request: ApprovalRequest) -> dict[str, Any]:
    return {
        "type": "approval_requested",
        "approval_id": request.approval_id,
        "run_id": request.run_id,
        "tool_name": request.proposed_action.name,
        "reason": request.reason,
        "risk_level": request.risk_level.value,
        "input_preview": request.input_preview,
        "created_at": request.created_at,
    }


def _resolved_event(
    request: ApprovalRequest, resolution: ApprovalResolution
) -> dict[str, Any]:
    return {
        "type": "approval_resolved",
        "approval_id": resolution.approval_id,
        "run_id": request.run_id,
        "decision": resolution.decision.value,
        "input_modified": resolution.modified_input is not None,
        "explanation": resolution.explanation,
        "resolved_at": resolution.resolved_at,
    }
