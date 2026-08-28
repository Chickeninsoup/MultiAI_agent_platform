from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CompactionPlan:
    """A decision about which messages to keep, not the messages themselves.

    Describes intent (indices) rather than holding a copy of the data
    (retained_messages: list[LLMMessage]) - a Plan should be reviewable,
    testable, and loggable independent of the messages' own lifetime,
    the same reasoning behind TaskPlan/PlanReview/PlanApproval in
    src/planning/. Actually dropping the un-retained messages is a
    separate execution step (5D-6B-4B-2+), not this dataclass's job -
    building this doesn't touch any message list.
    """

    original_count: int
    retained_indices: list[int] = field(default_factory=list)
