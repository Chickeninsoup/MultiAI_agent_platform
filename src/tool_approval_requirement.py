from __future__ import annotations

from enum import Enum


class ToolApprovalRequirement(Enum):
    """Whether an already-authorized ToolCall needs a human's blessing
    before it executes (5E-5D-3) - a pure, pre-execution
    classification, produced by ToolApprovalPolicy.evaluate().

    Not ApprovalDecision (src/approval_decision.py): that enum is the
    human's *later* response to a specific ApprovalRequest (APPROVE/
    REJECT/MODIFY/CANCEL) - a decision made once, about one request,
    after it was raised. This one is the policy's classification of a
    ToolCall *before* anything has been raised at all - "does this
    even need to ask," not "what did the human say." A ToolCall
    classified REQUIRES_APPROVAL doesn't yet have an ApprovalRequest,
    a run_id, or a preview; producing one from this classification is
    later-stage wiring, out of scope here.

    DOES_NOT_REQUIRE_APPROVAL - the ToolCall may proceed straight to
    execution once ordinary tool authorization (ToolPolicy) has
    already allowed it.

    REQUIRES_APPROVAL - execution must pause for a human decision
    before this ToolCall is allowed to run, in whatever later stage
    wires that pause in. This classification itself does not pause,
    execute, or record anything.
    """

    DOES_NOT_REQUIRE_APPROVAL = "does_not_require_approval"
    REQUIRES_APPROVAL = "requires_approval"
