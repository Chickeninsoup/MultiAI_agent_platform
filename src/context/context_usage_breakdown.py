from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextUsageBreakdown:
    """A per-round token breakdown of what's actually sent to the provider.

    initial_message_tokens covers request.messages[0] as a whole -
    the original task text AND the static context snapshot
    (project_snapshot) baked into it by RunContextBuilder/
    LLMAgentRunExecutor._build_request. They aren't split apart here:
    that's a single message by the time it reaches LLMRequest, so
    separating "task" from "snapshot" would need instrumenting
    ContextBuilder, not this. history_before_tokens is diagnostic
    only (what the durable history would cost pre-compaction) - it's
    excluded from total_sent_tokens, which reflects only what this
    round's request actually contains.
    """

    system_prompt_tokens: int
    tool_definition_tokens: int
    initial_message_tokens: int
    history_before_tokens: int
    history_after_tokens: int

    @property
    def total_sent_tokens(self) -> int:
        return (
            self.system_prompt_tokens
            + self.tool_definition_tokens
            + self.initial_message_tokens
            + self.history_after_tokens
        )
