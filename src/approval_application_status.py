from __future__ import annotations

from enum import Enum


class ApprovalApplicationStatus(Enum):
    """Where one ApprovalApplicationRecord is in its lifecycle
    (5E-5D-6B) - deliberately only two states, not three.

    CLAIMED - a process has exclusively created this record (won the
    create_exclusive() race for this approval_id) but has not yet
    persisted an outcome. This single state covers *both* "a process
    is actively dispatching right now" and "a process claimed this and
    then crashed/was killed before finishing" - ApprovalApplicationService
    has no heartbeat, lease, or owner-liveness mechanism, so it cannot
    and does not try to tell those two situations apart. Either way,
    the meaning to every other caller is identical: automatic
    redispatch is not safe, full stop. Resolving which of the two
    actually happened - and whether it is safe to proceed - is left to
    a human or a later, explicitly-manual reconciliation path; nothing
    in this stage ever moves a record out of CLAIMED except the one
    call that created it succeeding at completion (see COMPLETED).

    COMPLETED - an ApprovalApplicationOutcome has been durably written
    for this record. Terminal: nothing in this codebase transitions a
    COMPLETED record back to CLAIMED, deletes it, or overwrites its
    outcome - retrying an already-COMPLETED application is required to
    return the exact stored outcome, never to dispatch again.
    """

    CLAIMED = "claimed"
    COMPLETED = "completed"
