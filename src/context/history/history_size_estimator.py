from typing import Protocol

from src.llm.types import LLMMessage


class HistorySizeEstimator(Protocol):
    """Something that can answer "how big is this slice of history?"

    Structural, matching this codebase's ContextSizeEstimator
    convention. Takes a plain list[LLMMessage] - a group's messages,
    or the whole history - rather than a group-aware signature, so
    callers decide what "one thing to estimate" means; this only
    measures it. Swapping the char-based heuristic for a real
    provider tokenizer (e.g. Anthropic's count_tokens) should never
    require touching RuleBasedHistoryCompactor or
    RuleBasedHistoryAnalyzer, only this.
    """

    def estimate(self, messages: list[LLMMessage]) -> int:
        ...
