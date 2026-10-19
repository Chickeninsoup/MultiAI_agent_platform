from __future__ import annotations

from enum import Enum


class RunContinuationAttemptStatus(Enum):
    """Where one RunContinuationAttemptRecord is in its lifecycle
    (5E-5D-6C) - the same two-state shape ApprovalApplicationStatus
    already established for its own, narrower claim (one pending
    ToolCall), applied here to the *whole* continuation of a Run from
    its approval checkpoint (resolving B, finishing the interrupted
    round, driving the LLM loop onward, and reaching a terminal
    transition). See ApprovalApplicationStatus's own docstring for why
    CLAIMED deliberately does not distinguish "actively running" from
    "crashed after claiming" - the same reasoning applies one layer up:
    this class has no heartbeat or liveness signal either, so neither
    can it.

    CLAIMED - a process exclusively created this record for this
    run_id (won create_exclusive()) but has not yet persisted a
    RunContinuationTransition. Everything from applying the pending
    decision through driving the LLM loop and persisting the Run's new
    terminal/paused state happens while a record is CLAIMED - a
    process observing CLAIMED for any run_id must never attempt its
    own continuation for that Run, regardless of which approval_id it
    was asked to resume with.

    COMPLETED - a RunContinuationTransition has been durably recorded.
    Terminal - nothing transitions a COMPLETED record back to CLAIMED.
    """

    CLAIMED = "claimed"
    COMPLETED = "completed"
