from __future__ import annotations

from src.context.history.char_based_history_size_estimator import (
    CharBasedHistorySizeEstimator,
)
from src.context.history.history_analysis import HistoryAnalysis
from src.context.history.history_size_estimator import (
    HistorySizeEstimator,
)
from src.context.history.message_blocks import has_content_block_type
from src.llm.types import LLMMessage


class RuleBasedHistoryAnalyzer:
    """Counts messages and estimates their size - observe only.

    No compaction decisions here (5D-6B-4A). "Tool message" means a
    role="user" message carrying a tool_result content block - this
    codebase's LLMRole is only "user"/"assistant" (Anthropic-style;
    there is no separate "tool" role), and tool results are returned
    as user-role messages whose content is a list of blocks including
    {"type": "tool_result", ...} (see ToolResult.to_message_block()
    and LLMRunExecutor's tool-round handling). Token estimation is
    delegated to an injected HistorySizeEstimator (same one
    RuleBasedHistoryCompactor uses) rather than computed here, so a
    real provider-tokenizer-backed estimator upgrades both at once.
    """

    def __init__(
        self, size_estimator: HistorySizeEstimator | None = None
    ) -> None:
        self._size_estimator = (
            size_estimator
            if size_estimator is not None
            else CharBasedHistorySizeEstimator()
        )

    def analyze(self, messages: list[LLMMessage]) -> HistoryAnalysis:
        total_messages = len(messages)

        tool_messages = sum(
            1
            for message in messages
            if has_content_block_type(message, "tool_result")
        )

        estimated_tokens = self._size_estimator.estimate(messages)

        return HistoryAnalysis(
            total_messages=total_messages,
            estimated_tokens=estimated_tokens,
            tool_messages=tool_messages,
        )
