from typing import Protocol

from src.context.context_snapshot import ContextSnapshot


class ContextSizeEstimator(Protocol):
    """Something that can answer "how big is this ContextSnapshot?"

    Structural, matching this codebase's Planner/ContextSelector
    convention. Kept separate from ContextTrimmer on purpose: today
    it's RuleBasedContextSizeEstimator's char-count heuristic, later
    it could be a real Claude/OpenAI tokenizer - swapping that out
    should never require touching whatever consumes the estimate.
    """

    def estimate(self, snapshot: ContextSnapshot) -> int:
        ...
