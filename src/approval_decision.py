from __future__ import annotations

from enum import Enum


class ApprovalDecision(Enum):
    """The terminal choice a human makes when resolving an
    ApprovalRequest (5E-5D-1).

    A pure domain value, same as RecoveryAction/FailureCategory: this
    enum doesn't execute anything, doesn't touch RecoveryExecutor,
    doesn't touch persistence. Whatever eventually resolves an
    ApprovalRequest (a later stage, not this one) is what actually
    acts on a decision.

    APPROVE - the proposed action may run exactly as proposed.

    REJECT - the proposed action must not run; nothing is executed.

    MODIFY - the proposed action may run, but only with a different
    input than what was proposed - see ApprovalResolution.modified_input.

    CANCEL - the human declines to judge the proposed action at all;
    it's withdrawn without being explicitly approved or rejected (e.g.
    it's no longer relevant, or the human wants to stop the flow
    rather than decide on this specific action).
    """

    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"
    CANCEL = "cancel"
