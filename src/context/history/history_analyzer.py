from typing import Protocol

from src.context.history.history_analysis import HistoryAnalysis
from src.llm.types import LLMMessage


class HistoryAnalyzer(Protocol):
    """Something that can measure a conversation's message history.

    Structural, matching this codebase's Planner/ContextSelector
    convention. Takes list[LLMMessage] - the actual type that flows
    through LLMRunExecutor's tool-calling loop (src/llm_executor.py) -
    rather than a generic list[dict], so this layer never needs its
    own conversion step before 5D-6B-4C can wire it in for real.
    """

    def analyze(self, messages: list[LLMMessage]) -> HistoryAnalysis:
        ...
