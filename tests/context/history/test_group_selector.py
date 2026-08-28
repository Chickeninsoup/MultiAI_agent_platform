from __future__ import annotations

from src.context.history.group_selector import GroupSelector
from src.context.history.message_group_builder import (
    MessageGroupBuilder,
)
from src.llm.types import LLMMessage


class CountEstimator:
    """Estimates a group's cost as its message count - deterministic
    and independent of char-based math, so these selection-order
    tests aren't sensitive to unrelated string-length changes."""

    def estimate(self, messages: list[LLMMessage]) -> int:
        return len(messages)


def _text(role: str, text: str) -> LLMMessage:
    return LLMMessage(role=role, content=text)


def _tool_use(tool_id: str, name: str) -> LLMMessage:
    return LLMMessage(
        role="assistant",
        content=[
            {
                "type": "tool_use",
                "id": tool_id,
                "name": name,
                "input": {},
            }
        ],
    )


def _tool_result(tool_id: str) -> LLMMessage:
    return LLMMessage(
        role="user",
        content=[
            {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": "result",
                "is_error": False,
            }
        ],
    )


def test_protected_tool_is_selected_over_evictable_one() -> None:
    # 0 initial | (1,2) read_file [evictable] | (3,4) apply_patch
    # [protected] | 5 normal text. Budget only fits initial + one
    # exchange + the normal text - the protected one must win.
    messages = [
        _text("user", "task"),
        _tool_use("call-1", "read_file"),
        _tool_result("call-1"),
        _tool_use("call-2", "apply_patch"),
        _tool_result("call-2"),
        _text("assistant", "done"),
    ]
    groups = MessageGroupBuilder().build(messages)
    selector = GroupSelector(size_estimator=CountEstimator())

    result = selector.select(messages, groups, max_tokens=4)

    assert 2 in result.retained_positions  # apply_patch group
    assert 1 not in result.retained_positions  # read_file group


def test_older_evictable_exchange_is_dropped_for_a_newer_one() -> None:
    # Two read_file exchanges, budget for only one - the newer one
    # (closer to the end of history) wins.
    messages = [
        _text("user", "task"),
        _tool_use("call-1", "read_file"),  # older
        _tool_result("call-1"),
        _tool_use("call-2", "read_file"),  # newer
        _tool_result("call-2"),
    ]
    groups = MessageGroupBuilder().build(messages)
    selector = GroupSelector(size_estimator=CountEstimator())

    result = selector.select(messages, groups, max_tokens=3)

    older_read_file_position = 1
    newer_read_file_position = 2
    assert newer_read_file_position in result.retained_positions
    assert older_read_file_position not in result.retained_positions


def test_recent_normal_group_is_preferred_over_an_older_one() -> None:
    messages = [
        _text("user", "task"),
        _text("assistant", "old chat message"),
        _text("assistant", "recent chat message"),
    ]
    groups = MessageGroupBuilder().build(messages)
    selector = GroupSelector(size_estimator=CountEstimator())

    result = selector.select(messages, groups, max_tokens=2)

    assert 2 in result.retained_positions
    assert 1 not in result.retained_positions


def test_tool_exchanges_are_never_split_across_a_tight_budget() -> None:
    messages = [_text("user", "task")]
    for i in range(6):
        messages.append(_tool_use(f"call-{i}", "read_file"))
        messages.append(_tool_result(f"call-{i}"))

    groups = MessageGroupBuilder().build(messages)
    selector = GroupSelector(size_estimator=CountEstimator())

    result = selector.select(messages, groups, max_tokens=5)

    retained_message_indices = {
        index
        for position in result.retained_positions
        for index in groups[position].indices
    }

    for exchange in range(6):
        tool_use_index = 1 + 2 * exchange
        tool_result_index = 2 + 2 * exchange
        assert (tool_use_index in retained_message_indices) == (
            tool_result_index in retained_message_indices
        )


def test_unknown_tool_competes_as_normal_not_evictable() -> None:
    # An unrecognized tool (deploy_service) should be treated like a
    # NORMAL group, not silently discarded like an evictable one -
    # given a choice between it and an evictable read_file exchange
    # under a budget that only fits one, the unknown tool wins.
    messages = [
        _text("user", "task"),
        _tool_use("call-1", "read_file"),
        _tool_result("call-1"),
        _tool_use("call-2", "deploy_service"),
        _tool_result("call-2"),
    ]
    groups = MessageGroupBuilder().build(messages)
    selector = GroupSelector(size_estimator=CountEstimator())

    result = selector.select(messages, groups, max_tokens=3)

    deploy_service_position = 2
    read_file_position = 1
    assert deploy_service_position in result.retained_positions
    assert read_file_position not in result.retained_positions


def test_selection_is_deterministic() -> None:
    messages = [_text("user", "task")]
    for i in range(10):
        messages.append(_tool_use(f"call-{i}", "read_file"))
        messages.append(_tool_result(f"call-{i}"))

    groups = MessageGroupBuilder().build(messages)
    selector = GroupSelector(size_estimator=CountEstimator())

    first = selector.select(messages, groups, max_tokens=8)
    second = selector.select(messages, groups, max_tokens=8)

    assert first == second


def test_initial_group_always_retained_even_with_zero_budget() -> None:
    messages = [
        _text("user", "task"),
        _tool_use("call-1", "apply_patch"),
        _tool_result("call-1"),
    ]
    groups = MessageGroupBuilder().build(messages)
    selector = GroupSelector(size_estimator=CountEstimator())

    result = selector.select(messages, groups, max_tokens=0)

    assert result.retained_positions == [0]


def test_empty_groups_produce_an_empty_result() -> None:
    selector = GroupSelector(size_estimator=CountEstimator())

    result = selector.select([], [], max_tokens=1000)

    assert result.retained_positions == []
