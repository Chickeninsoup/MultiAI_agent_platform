from __future__ import annotations

import hashlib
from typing import Callable

from src.approval_request import ApprovalRequest
from src.approval_store import ApprovalStore
from src.domain.tools.tool_call import ToolCall
from src.tool_approval_gate_outcome import ToolApprovalGateOutcome
from src.tool_approval_gate_result import ToolApprovalGateResult
from src.tool_approval_policy import ToolApprovalPolicy
from src.tool_approval_requirement import ToolApprovalRequirement
from src.tool_input_previewer import ToolInputPreviewer

_ID_FIELD_SEPARATOR = "\x1f"
"""ASCII Unit Separator - a control character no run_id or
ToolCall.id in this codebase is ever expected to contain, used only
as a human-readable delimiter between the two encoded fields below.
The actual unambiguity guarantee comes from length-prefixing
run_id (see _default_approval_id), not from this character alone -
a separator that could itself appear inside either input would make
the encoding ambiguous no matter how "safe" it looks."""


def _default_approval_id(run_id: str, tool_call: ToolCall) -> str:
    """approval-<sha256 hex digest of (run_id, tool_call.id)> -
    scoped by *both* identifiers (5E-5D-4A-1), not tool_call.id alone.

    ToolCall.id (the provider's stable tool-use identifier, e.g.
    Anthropic's "toolu_..."; see src/llm_executor.py, which already
    uses tool_use.id as tool_call_id everywhere else in this
    codebase) is stable *within one execution*, but ApprovalStore
    persists requests in a single global tasks_dir/approvals/<id>/
    tree (src/approval_request_repository.py), not one scoped per
    run - stability within a run does not imply global uniqueness
    across separate runs, so tool_call.id alone was an insufficient
    key once approval_id is used as a shared directory name.

    Neither raw run_id nor raw tool_call.id is placed into the
    resulting id or, by extension, into any filesystem path - only
    their hash is. The encoding hashed is
    f"{len(run_id)}{SEP}{run_id}{SEP}{tool_call.id}": length-prefixing
    run_id makes the run_id/tool_call.id boundary unambiguous by
    construction, regardless of what characters either string
    contains (two different (run_id, tool_call.id) pairs can never
    produce the same encoded bytes) - the separator character adds
    readability but the length prefix is what actually guarantees
    injectivity. sha256 then gives a fixed-length, filesystem-safe
    (hex digest: only [0-9a-f]) digest that is deterministic for the
    same pair and changes if either run_id or tool_call.id changes.

    Prefixed with "approval-" rather than used bare so an approval_id
    is recognizable as one at a glance (matching the
    "<scope>-approval-<n>" shape RuntimeApprovalService already
    uses).
    """

    encoded = (
        f"{len(run_id)}{_ID_FIELD_SEPARATOR}{run_id}"
        f"{_ID_FIELD_SEPARATOR}{tool_call.id}"
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()

    return f"approval-{digest}"


class ToolApprovalGate:
    """The application-layer seam between "does this ToolCall need
    approval" and "an ApprovalRequest now exists for it" (5E-5D-4A) -
    combines ToolApprovalPolicy, a ToolInputPreviewer, approval-id
    creation, and ApprovalStore into one operation, check(). Unwired:
    nothing in this codebase calls this class yet.

    Not RuntimeApprovalRequest/RecoveryExecutor's REQUEST_APPROVAL
    path (src/runtime_approval_service.py, src/recovery_executor.py) -
    deliberately not reused or touched. Those answer "may recovery
    continue after a BLOCKED plan-level failure," resolved by
    RecoveryPlanner from an ExecutionFailure. This gate answers
    "should this specific ToolCall be allowed to run right now,"
    resolved by ToolApprovalPolicy from the call itself, before
    execution has even been attempted - a check, not a recovery. Two
    independent "approval" axes continue to coexist on purpose (see
    ApprovalRequest's own docstring); nothing about wiring either of
    them into a runtime is decided here.

    check()'s two branches:

    - DOES_NOT_REQUIRE_APPROVAL: returns PROCEED immediately. Calls
      nothing else - not the previewer, not the id factory, not the
      store. A tool with no configured ApprovalRule costs this gate
      nothing beyond one ToolApprovalPolicy.evaluate() call.

    - REQUIRES_APPROVAL: computes an approval_id, then a preview,
      validates the preview is non-empty, constructs an ApprovalRequest
      (which independently re-validates via its own __post_init__),
      and only then calls ApprovalStore.create() - the one point with
      an observable side effect. Any failure before that call
      (empty run_id, previewer raising, an empty preview, ApprovalRequest's
      own invariants rejecting something) means create() is never
      called, so the store is left exactly as it was. ApprovalStore
      remains the only thing that ever emits approval_requested; this
      class never touches an event sink.

    ToolPolicy authorization (src/services/tools/tool_policy.py) is
    completely outside this gate's reach - it never receives one, so
    it structurally cannot grant, upgrade, or otherwise affect
    whether a ToolCall is authorized to execute. It also never
    executes a ToolCall itself, under any branch or failure path.

    policy/previewer/store are required, not optional-with-a-default:
    there is no safe default previewer (any default risks becoming
    exactly the repr()/str()/json.dumps() fallback this stage
    explicitly forbids), so construction fails fast rather than
    silently picking an unsafe one. approval_id_factory is the one
    collaborator with a safe default (_default_approval_id above) -
    deriving a digest from (run_id, ToolCall.id) has no
    security-sensitive failure mode the way a preview does, so a
    default is safe to offer.

    approval_id_factory takes (run_id, tool_call), not tool_call
    alone (5E-5D-4A-1) - the old one-argument shape didn't carry
    enough information to scope an id across runs, and was changed
    outright rather than kept alongside a new signature "for
    compatibility": nothing in this codebase calls this class yet, so
    there was no real caller to preserve compatibility for, and a
    single-argument factory would still let a caller reintroduce the
    exact under-scoping bug this revision exists to close.
    """

    def __init__(
        self,
        policy: ToolApprovalPolicy,
        previewer: ToolInputPreviewer,
        store: ApprovalStore,
        approval_id_factory: (
            Callable[[str, ToolCall], str] | None
        ) = None,
    ) -> None:
        self._policy = policy
        self._previewer = previewer
        self._store = store
        self._approval_id_factory = (
            approval_id_factory
            if approval_id_factory is not None
            else _default_approval_id
        )

    def check(
        self, run_id: str, tool_call: ToolCall
    ) -> ToolApprovalGateResult:
        if not run_id or not run_id.strip():
            raise ValueError(
                "ToolApprovalGate.check() requires a non-empty run_id"
            )

        policy_result = self._policy.evaluate(tool_call)

        if (
            policy_result.requirement
            is ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL
        ):
            return ToolApprovalGateResult(
                outcome=ToolApprovalGateOutcome.PROCEED
            )

        approval_id = self._approval_id_factory(run_id, tool_call)

        preview = self._previewer.preview(tool_call)

        if not preview or not preview.strip():
            raise ValueError(
                "ToolInputPreviewer returned an empty preview for "
                f"tool {tool_call.name!r}"
            )

        request = ApprovalRequest(
            approval_id=approval_id,
            run_id=run_id,
            proposed_action=tool_call,
            reason=policy_result.reason,
            risk_level=policy_result.risk_level,
            input_preview=preview,
        )

        created = self._store.create(request)

        return ToolApprovalGateResult(
            outcome=ToolApprovalGateOutcome.WAITING_FOR_APPROVAL,
            approval_request=created,
        )
