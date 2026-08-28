from typing import Protocol

from src.context.context_budget import ContextBudget
from src.context.context_snapshot import ContextSnapshot


class ContextTrimmer(Protocol):
    """Something that can shrink a ContextSnapshot to fit a budget.

    Structural, matching this codebase's Planner/ContextSelector
    convention. Today's RuleBasedContextTrimmer only drops whole
    files (ContextFile has no content/token_count/score to trim
    within a file yet) - a future trimmer could do finer-grained
    truncation without callers changing.
    """

    def trim(
        self, snapshot: ContextSnapshot, budget: ContextBudget
    ) -> ContextSnapshot:
        ...
