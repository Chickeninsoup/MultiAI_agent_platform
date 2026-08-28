from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepairDecision:
    """Whether it's worth asking the Planner to try again, and why.

    reason exists alongside the bool for the same reason ValidationError
    carries a message alongside its code - a human (or a log line)
    reading "should_repair=False" still needs to know if that's
    because the plan was already fine or because it's unfixably
    broken. RepairDecisionService is the only thing that constructs
    these; nothing else should be guessing at should_repair itself.
    """

    should_repair: bool
    reason: str
