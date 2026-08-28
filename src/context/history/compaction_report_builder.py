from __future__ import annotations

from typing import Any

from src.context.history.compaction_report import CompactionReport
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


class CompactionReportBuilder:
    """Explains a GroupSelector decision after the fact - debug only.

    Never influences what gets retained - GroupSelector already made
    that call; this only re-describes the same decision (which
    positions ended up in retained_positions) in a serializable shape.
    Re-derives *why* each group was retained/removed by re-running the
    same ToolRetentionPolicy classification GroupSelector used, rather
    than GroupSelector reporting its own reasoning - keeps selection
    and explanation as separate concerns that can't drift out of sync
    with GroupSelector's actual pass order (initial task, then
    protected, then everything else) as long as both use the same
    policy.
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

    def build(
        self,
        messages: list[LLMMessage],
        groups: list[MessageGroup],
        retained_positions: list[int],
    ) -> CompactionReport:
        retained_set = set(retained_positions)
        retained_groups: list[dict[str, Any]] = []
        removed_groups: list[dict[str, Any]] = []
        original_tokens = 0
        retained_tokens = 0

        for position, group in enumerate(groups):
            group_tokens = self._estimate_group(messages, group)
            original_tokens += group_tokens

            entry: dict[str, Any] = {
                "group": position,
                "kind": group.kind.value,
                "tool": group.tool_name,
            }

            if position in retained_set:
                retained_tokens += group_tokens
                entry["reason"] = self._retained_reason(
                    position, group
                )
                retained_groups.append(entry)
            else:
                entry["reason"] = "budget_limit"
                removed_groups.append(entry)

        return CompactionReport(
            retained_count=len(retained_groups),
            removed_count=len(removed_groups),
            original_tokens=original_tokens,
            retained_tokens=retained_tokens,
            retained_groups=retained_groups,
            removed_groups=removed_groups,
        )

    def _retained_reason(
        self, position: int, group: MessageGroup
    ) -> str:
        if position == 0:
            return "initial_task"

        if (
            group.kind == MessageGroupKind.TOOL_EXCHANGE
            and self._retention_policy.classify(group.tool_name)
            == ToolRetentionClass.PROTECTED
        ):
            return "protected_tool"

        return "recent_context"

    def _estimate_group(
        self, messages: list[LLMMessage], group: MessageGroup
    ) -> int:
        return self._size_estimator.estimate(
            [messages[index] for index in group.indices]
        )
