from __future__ import annotations

from enum import Enum


class RunContinuationTransition(Enum):
    """The terminal shape one resume_after_approval() attempt actually
    reached (5E-5D-6C) - recorded on a COMPLETED
    RunContinuationAttemptRecord so a retry can report what happened
    without re-driving anything. A different vocabulary from
    ContinuationNextAction (src/continuation_next_action.py) on
    purpose: that enum describes what happens to one pending ToolCall;
    this describes what happens to the whole Run by the time this
    attempt stops touching it.

    RUN_COMPLETED - the LLM loop reached a response with no further
    tool calls; the Run was finalized through the existing
    completion/review path (RunService._complete_run()).

    RUN_CANCELLED - the pending decision was CANCEL; the Run was
    finalized as terminally cancelled (RunService._cancel_run()), no
    remaining ToolCall in the round was dispatched, and no provider
    call was made.

    RUN_WAITING_FOR_APPROVAL - a later ToolCall in the same round (or
    a later round) required approval in turn; the Run was returned to
    waiting_for_approval for a *new* approval_id
    (RunService._pause_run()), and this attempt stops there without
    reaching any call after the new pending one.
    """

    RUN_COMPLETED = "run_completed"
    RUN_CANCELLED = "run_cancelled"
    RUN_WAITING_FOR_APPROVAL = "run_waiting_for_approval"
