from __future__ import annotations

import dataclasses

import pytest

from src.context.context_usage_breakdown import ContextUsageBreakdown


def test_total_sent_tokens_excludes_history_before() -> None:
    breakdown = ContextUsageBreakdown(
        system_prompt_tokens=2500,
        tool_definition_tokens=9000,
        initial_message_tokens=12000,
        history_before_tokens=8000,
        history_after_tokens=1000,
    )

    assert breakdown.total_sent_tokens == 24500


def test_context_usage_breakdown_is_frozen() -> None:
    breakdown = ContextUsageBreakdown(
        system_prompt_tokens=1,
        tool_definition_tokens=1,
        initial_message_tokens=1,
        history_before_tokens=1,
        history_after_tokens=1,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        breakdown.system_prompt_tokens = 2
