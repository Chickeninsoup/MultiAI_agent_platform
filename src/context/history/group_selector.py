from __future__ import annotations

from dataclasses import dataclass

from src.context.history.history_size_estimator import (
    HistorySizeEstimator,
)
from src.context.history.message_group import (
    MessageGroup,
    MessageGroupKind,
)
from src.context.history.tool_retention_policy import (
    RuleBasedToolRetentionPolicy,
    ToolRetentionClass,
    ToolRetentionPolicy,
)
from src.llm.types import LLMMessage


@dataclass(frozen=True)
class GroupSelectionResult:
    """Which group positions (not message indices) survived selection.

    Positions into the `groups` list passed to select(), not message
    indices - RuleBasedHistoryCompactor is the one that knows how to
    flatten a MessageGroup's own indices into the final
    CompactionPlan. Keeping this at group granularity means
    GroupSelector never needs to know anything about LLMMessage
    indices itself, just which groups it picked.
    """

    retained_positions: list[int]


class GroupSelector:
    """Picks which groups survive a budget, tool-priority aware.

    Not a Protocol - there's only one implementation so far, unlike
    HistorySizeEstimator/ToolRetentionPolicy which already have a
    reason to vary (char-based vs a real tokenizer, rule-based vs
    LLM-judged). Add one if/when a second GroupSelector strategy
    actually shows up.

    Selection runs in four passes, each newest-first:
      1. group 0 (INITIAL_TASK) - always retained, unconditionally,
         even if it alone exceeds the budget.
      2. PROTECTED tool exchanges - state-changing tools (apply_patch,
         write_file, ...) get first claim on whatever budget remains.
         No early break here: a big protected group blocking the scan
         must not disqualify a smaller protected group further back,
         since losing state-changing history is worse than losing a
         read.
      3. everything not yet retained and not EVICTABLE (i.e. NORMAL
         groups, plus any PROTECTED group pass 2 couldn't afford -
         re-checked here for consistency/simplicity, though if it
         didn't fit in pass 2 it won't fit now either, since remaining
         only shrinks between passes).
      4. EVICTABLE tool exchanges (read_file, list_files, search, ...)
         - last claim on whatever budget is left.

    Every pass estimates a group's cost as the sum of just that
    group's own messages via the injected HistorySizeEstimator - the
    same abstraction RuleBasedHistoryCompactor itself now delegates
    to, rather than measuring here independently.
    """

    def __init__(
        self,
        size_estimator: HistorySizeEstimator,
        retention_policy: ToolRetentionPolicy | None = None,
    ) -> None:
        self._size_estimator = size_estimator
        self._retention_policy = (
            retention_policy
            if retention_policy is not None
            else RuleBasedToolRetentionPolicy()
        )

    def select(
        self,
        messages: list[LLMMessage],
        groups: list[MessageGroup],
        max_tokens: int,
    ) -> GroupSelectionResult:
        if not groups:
            return GroupSelectionResult(retained_positions=[])

        retained: set[int] = {0}
        remaining = max_tokens - self._estimate_group(
            messages, groups[0]
        )

        # Pass 1: protected tool exchanges, no break - a big one must
        # not block a smaller one further back.
        for position in range(len(groups) - 1, 0, -1):
            group = groups[position]

            if self._retention_class(group) != ToolRetentionClass.PROTECTED:
                continue

            size = self._estimate_group(messages, group)

            if size <= remaining:
                retained.add(position)
                remaining -= size

        # Pass 2: everything else that isn't evictable.
        for position in range(len(groups) - 1, 0, -1):
            if position in retained:
                continue

            if (
                self._retention_class(groups[position])
                == ToolRetentionClass.EVICTABLE
            ):
                continue

            size = self._estimate_group(messages, groups[position])

            if size <= remaining:
                retained.add(position)
                remaining -= size

        # Pass 3: evictable tool exchanges, last claim on the budget.
        for position in range(len(groups) - 1, 0, -1):
            if position in retained:
                continue

            size = self._estimate_group(messages, groups[position])

            if size <= remaining:
                retained.add(position)
                remaining -= size

        return GroupSelectionResult(
            retained_positions=sorted(retained)
        )

    def _retention_class(self, group: MessageGroup) -> ToolRetentionClass:
        if group.kind != MessageGroupKind.TOOL_EXCHANGE:
            return ToolRetentionClass.NORMAL

        return self._retention_policy.classify(group.tool_name)

    def _estimate_group(
        self, messages: list[LLMMessage], group: MessageGroup
    ) -> int:
        return self._size_estimator.estimate(
            [messages[index] for index in group.indices]
        )
