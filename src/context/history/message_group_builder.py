from __future__ import annotations

from src.context.history.message_blocks import (
    get_tool_name,
    has_content_block_type,
)
from src.context.history.message_group import (
    MessageGroup,
    MessageGroupKind,
)
from src.llm.types import LLMMessage


class MessageGroupBuilder:
    """Groups an LLMMessage history into INITIAL_TASK/NORMAL/TOOL_EXCHANGE.

    Read-only, like HistoryAnalyzer - this doesn't decide what to keep
    or drop, only what shape the history has. Index 0 is always
    INITIAL_TASK: it's the first user message carrying the original
    task prompt (this codebase's messages list never contains a
    system-role entry - see RuleBasedHistoryCompactor's docstring for
    why). An assistant message carrying a tool_use block, immediately
    followed by a user message carrying a tool_result block, groups
    together as one TOOL_EXCHANGE - that pairing is the natural unit
    LLMRunExecutor's tool-calling loop produces, and splitting it
    would let a future compactor drop half a round (e.g. the tool_use
    without its result), which is exactly the kind of ordering bug a
    Plan-based approach is meant to avoid. Everything else is its own
    single-message NORMAL group. A TOOL_EXCHANGE group's tool_name is
    read straight off its tool_use message; INITIAL_TASK/NORMAL groups
    leave it None.
    """

    def build(self, messages: list[LLMMessage]) -> list[MessageGroup]:
        groups: list[MessageGroup] = []
        index = 0
        count = len(messages)

        while index < count:
            if index == 0:
                groups.append(
                    MessageGroup(
                        indices=(0,),
                        kind=MessageGroupKind.INITIAL_TASK,
                    )
                )
                index += 1
                continue

            if self._starts_tool_exchange(messages, index):
                groups.append(
                    MessageGroup(
                        indices=(index, index + 1),
                        kind=MessageGroupKind.TOOL_EXCHANGE,
                        tool_name=get_tool_name(messages[index]),
                    )
                )
                index += 2
                continue

            groups.append(
                MessageGroup(
                    indices=(index,), kind=MessageGroupKind.NORMAL
                )
            )
            index += 1

        return groups

    def _starts_tool_exchange(
        self, messages: list[LLMMessage], index: int
    ) -> bool:
        if index + 1 >= len(messages):
            return False

        return has_content_block_type(
            messages[index], "tool_use"
        ) and has_content_block_type(
            messages[index + 1], "tool_result"
        )
