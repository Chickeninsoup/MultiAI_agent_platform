from __future__ import annotations

from src.context.history.char_based_history_size_estimator import (
    CharBasedHistorySizeEstimator,
)
from src.context.history.compaction_plan import CompactionPlan
from src.context.history.group_selector import GroupSelector
from src.context.history.history_budget import HistoryBudget
from src.context.history.history_size_estimator import (
    HistorySizeEstimator,
)
from src.context.history.message_group import MessageGroup
from src.context.history.message_group_builder import (
    MessageGroupBuilder,
)
from src.llm.types import LLMMessage


class RuleBasedHistoryCompactor:
    """Default HistoryCompactor: builds groups, delegates selection.

    Deterministic, no LLM summary/embedding/importance scoring beyond
    what GroupSelector's tool-priority passes already do. This class
    now only does two things: build groups from the raw message list,
    and flatten GroupSelector's chosen group positions back into
    message indices for the CompactionPlan - the actual selection
    logic (mandatory initial group, protected/normal/evictable
    priority passes, budget packing) lives in GroupSelector, not here.

    Groups, not raw message indices, are the unit of retention -
    MessageGroupBuilder produces a TOOL_EXCHANGE group for an
    assistant tool_use paired with its user tool_result, and
    GroupSelector keeps or drops that pair as one unit, never half of
    it.

    RECENT_GROUP_COUNT and _compact_by_recent_group_count() are the
    original (pre-budget, pre-GroupSelector) algorithm, kept but no
    longer called by compact() - preserved so existing callers/tests
    referencing them directly don't break, not because anything
    currently invokes this path.

    Never touches the messages list - compact() only returns a
    CompactionPlan; nothing is dropped until a later execution step
    applies it.
    """

    RECENT_GROUP_COUNT = 6

    def __init__(
        self,
        group_builder: MessageGroupBuilder | None = None,
        size_estimator: HistorySizeEstimator | None = None,
        group_selector: GroupSelector | None = None,
    ) -> None:
        self._group_builder = (
            group_builder
            if group_builder is not None
            else MessageGroupBuilder()
        )
        self._size_estimator = (
            size_estimator
            if size_estimator is not None
            else CharBasedHistorySizeEstimator()
        )
        self._group_selector = (
            group_selector
            if group_selector is not None
            else GroupSelector(size_estimator=self._size_estimator)
        )

    def compact(
        self, messages: list[LLMMessage], budget: HistoryBudget
    ) -> CompactionPlan:
        count = len(messages)
        groups = self._group_builder.build(messages)

        result = self._group_selector.select(
            messages, groups, budget.max_tokens
        )

        retained_indices = sorted(
            index
            for position in result.retained_positions
            for index in groups[position].indices
        )

        return CompactionPlan(
            original_count=count,
            retained_indices=retained_indices,
        )

    def _estimate_group(
        self, messages: list[LLMMessage], group: MessageGroup
    ) -> int:
        return self._size_estimator.estimate(
            [messages[index] for index in group.indices]
        )

    def _compact_by_recent_group_count(
        self, messages: list[LLMMessage]
    ) -> CompactionPlan:
        """Preserved pre-budget algorithm - not called by compact().

        Kept as a documented fallback per 5D-6B-4B-3's own decision:
        group-count windowing without any token awareness, useful if
        a future caller needs deterministic windowing with no budget
        concept at all.
        """

        count = len(messages)
        groups = self._group_builder.build(messages)
        group_count = len(groups)

        if group_count <= self.RECENT_GROUP_COUNT:
            retained_group_positions = set(range(group_count))
        else:
            start = max(0, group_count - self.RECENT_GROUP_COUNT)
            retained_group_positions = {0}
            retained_group_positions.update(range(start, group_count))

        retained_indices = sorted(
            index
            for position in retained_group_positions
            for index in groups[position].indices
        )

        return CompactionPlan(
            original_count=count,
            retained_indices=retained_indices,
        )
