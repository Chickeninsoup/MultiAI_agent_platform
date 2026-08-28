from __future__ import annotations

from src.context.context_usage_breakdown import ContextUsageBreakdown
from src.context.history.history_size_estimator import (
    HistorySizeEstimator,
)
from src.domain.tools.tool_definition import ToolDefinition
from src.llm.types import LLMMessage, LLMRequest


class ContextUsageBuilder:
    """Turns a (compacted) LLMRequest into a per-round token breakdown.

    Doesn't compute token sizes itself - everything routes through
    the injected HistorySizeEstimator (the same abstraction
    RuleBasedHistoryCompactor/RuleBasedHistoryAnalyzer use), including
    system_prompt and tool definitions, which Phase 1 Step 4's smoke
    test found the compactor's own estimate was blind to entirely.
    Wrapping raw text (system_prompt, serialized tools) in a synthetic
    LLMMessage to reuse the same estimate() call keeps this the one
    place token math changes when a real provider tokenizer replaces
    the char-based default.

    Needs both the compacted `request` (system_prompt, tools, and the
    messages actually being sent this round) and the full, durable
    `full_messages` list (to report what history would have cost
    before compaction) - build() can't compute history_before from
    request alone, since request.messages is already post-compaction.
    """

    def __init__(self, size_estimator: HistorySizeEstimator) -> None:
        self._size_estimator = size_estimator

    def build(
        self,
        request: LLMRequest,
        full_messages: list[LLMMessage],
    ) -> ContextUsageBreakdown:
        return ContextUsageBreakdown(
            system_prompt_tokens=self._estimate_text(
                request.system_prompt
            ),
            tool_definition_tokens=self._estimate_tools(request.tools),
            initial_message_tokens=self._size_estimator.estimate(
                request.messages[:1]
            ),
            history_before_tokens=self._size_estimator.estimate(
                full_messages[1:]
            ),
            history_after_tokens=self._size_estimator.estimate(
                request.messages[1:]
            ),
        )

    def _estimate_text(self, text: str) -> int:
        return self._size_estimator.estimate(
            [LLMMessage(role="user", content=text)]
        )

    def _estimate_tools(self, tools: list[ToolDefinition]) -> int:
        if not tools:
            return 0

        text = "\n".join(str(tool) for tool in tools)

        return self._estimate_text(text)
