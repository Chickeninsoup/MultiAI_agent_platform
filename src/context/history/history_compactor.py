from typing import Protocol

from src.context.history.compaction_plan import CompactionPlan
from src.context.history.history_budget import HistoryBudget
from src.llm.types import LLMMessage


class HistoryCompactor(Protocol):
    """Something that can decide which messages are worth keeping.

    Returns a CompactionPlan, not shortened messages - keeps the
    Analyzer (observe) / Compactor (decide) / Executor (apply)
    responsibilities separate, matching this codebase's
    Selector/Estimator/Trimmer split for static context.
    """

    def compact(
        self, messages: list[LLMMessage], budget: HistoryBudget
    ) -> CompactionPlan:
        ...
