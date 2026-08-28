from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationError:
    """One problem PlanValidator found, tagged with whether it's worth fixing.

    code is a short machine-readable tag (UNKNOWN_AGENT,
    DEPENDENCY_CYCLE, ...) - message is the human-readable text that
    used to be the whole error (PlanReviewService's summary still
    shows exactly this text, via error_messages()). repairable
    distinguishes "a different plan could fix this" (wrong agent
    name, a cycle) from "no plan could fix this" (a genuinely
    structural problem) - the difference matters once something
    downstream (RepairDecisionService) has to decide whether asking
    the Planner to try again is even worth attempting.
    """

    code: str
    message: str
    repairable: bool
