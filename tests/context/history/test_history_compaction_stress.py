from __future__ import annotations

from src.context.history.history_budget import HistoryBudget
from src.context.history.message_group_builder import (
    MessageGroupBuilder,
)
from src.context.history.rule_based_history_compactor import (
    RuleBasedHistoryCompactor,
)
from src.llm.types import LLMMessage

TOOL_EXCHANGE_COUNT = 20


def make_initial_task() -> LLMMessage:
    return LLMMessage(
        role="user", content="implement a login feature"
    )


def make_tool_exchange(index: int) -> list[LLMMessage]:
    return [
        LLMMessage(
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "id": f"tool-{index}",
                    "name": "read_file",
                    "input": {"path": f"file_{index}.py"},
                }
            ],
        ),
        LLMMessage(
            role="user",
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": f"tool-{index}",
                    "content": "x" * 5000,
                }
            ],
        ),
    ]


def make_long_history(
    exchange_count: int = TOOL_EXCHANGE_COUNT,
) -> list[LLMMessage]:
    messages = [make_initial_task()]

    for index in range(exchange_count):
        messages.extend(make_tool_exchange(index))

    return messages


def _tool_exchange_index_pairs(
    messages: list[LLMMessage],
) -> list[tuple[int, int]]:
    """(tool_use_index, tool_result_index) for every exchange in
    make_long_history's output - message layout is fixed (1 initial
    task, then pairs), so this doesn't need MessageGroupBuilder at
    all; it's an independent check of the same invariant."""

    return [
        (1 + 2 * i, 2 + 2 * i)
        for i in range(TOOL_EXCHANGE_COUNT)
    ]


def test_stress_history_has_the_expected_shape() -> None:
    messages = make_long_history()

    assert len(messages) == 1 + 2 * TOOL_EXCHANGE_COUNT

    groups = MessageGroupBuilder().build(messages)
    assert len(groups) == 1 + TOOL_EXCHANGE_COUNT


def test_a_tight_budget_actually_compacts_a_large_history() -> None:
    compactor = RuleBasedHistoryCompactor()
    messages = make_long_history()

    # Measure one exchange's real (char-based) cost, then size a
    # budget that can only fit roughly half the exchanges - proving
    # compaction engages rather than trusting a hardcoded number that
    # may or may not exceed this history's actual size.
    groups = MessageGroupBuilder().build(messages)
    initial_tokens = compactor._estimate_group(messages, groups[0])
    one_exchange_tokens = compactor._estimate_group(messages, groups[1])
    budget = HistoryBudget(
        max_tokens=initial_tokens
        + (TOOL_EXCHANGE_COUNT // 2) * one_exchange_tokens
    )

    plan = compactor.compact(messages, budget)

    assert plan.original_count == len(messages)
    assert len(plan.retained_indices) < len(messages)


def test_compression_ratio_exceeds_fifty_percent_under_a_tight_budget() -> (
    None
):
    compactor = RuleBasedHistoryCompactor()
    messages = make_long_history()
    groups = MessageGroupBuilder().build(messages)
    initial_tokens = compactor._estimate_group(messages, groups[0])
    one_exchange_tokens = compactor._estimate_group(messages, groups[1])
    # Budget for the initial group + only 3 of the 20 exchanges.
    budget = HistoryBudget(
        max_tokens=initial_tokens + 3 * one_exchange_tokens
    )

    plan = compactor.compact(messages, budget)

    compression_ratio = 1 - (
        len(plan.retained_indices) / plan.original_count
    )
    assert compression_ratio > 0.5


def test_no_tool_exchange_pair_is_ever_broken_under_a_tight_budget() -> (
    None
):
    compactor = RuleBasedHistoryCompactor()
    messages = make_long_history()
    budget = HistoryBudget(max_tokens=500)  # very tight

    plan = compactor.compact(messages, budget)
    retained = set(plan.retained_indices)

    for tool_use_index, tool_result_index in _tool_exchange_index_pairs(
        messages
    ):
        assert (tool_use_index in retained) == (
            tool_result_index in retained
        )


def test_initial_task_always_survives_even_under_a_near_zero_budget() -> (
    None
):
    compactor = RuleBasedHistoryCompactor()
    messages = make_long_history()

    plan = compactor.compact(messages, HistoryBudget(max_tokens=0))

    assert plan.retained_indices == [0]


def test_generous_budget_leaves_the_full_stress_history_untouched() -> (
    None
):
    compactor = RuleBasedHistoryCompactor()
    messages = make_long_history()

    plan = compactor.compact(
        messages, HistoryBudget(max_tokens=10_000_000)
    )

    assert plan.retained_indices == list(range(len(messages)))


def test_stress_compaction_never_mutates_the_original_history() -> None:
    compactor = RuleBasedHistoryCompactor()
    messages = make_long_history()
    original = list(messages)

    compactor.compact(messages, HistoryBudget(max_tokens=5_000))

    assert messages == original
    assert messages is not original  # sanity: comparing separate lists


def test_compaction_is_deterministic_across_repeated_calls() -> None:
    compactor = RuleBasedHistoryCompactor()
    messages = make_long_history()
    budget = HistoryBudget(max_tokens=8_000)

    plan_one = compactor.compact(messages, budget)
    plan_two = compactor.compact(messages, budget)
    plan_three = compactor.compact(list(messages), budget)

    assert plan_one == plan_two == plan_three


def test_retained_messages_still_form_a_valid_tool_protocol_sequence() -> (
    None
):
    # Every retained tool_result must have a retained tool_use with a
    # matching id immediately before it in the retained sequence -
    # this is what "doesn't break tool protocol" actually means for
    # a real provider, not just "pairs move together as indices."
    compactor = RuleBasedHistoryCompactor()
    messages = make_long_history()
    groups = MessageGroupBuilder().build(messages)
    initial_tokens = compactor._estimate_group(messages, groups[0])
    one_exchange_tokens = compactor._estimate_group(messages, groups[1])
    budget = HistoryBudget(
        max_tokens=initial_tokens + 5 * one_exchange_tokens
    )

    plan = compactor.compact(messages, budget)
    retained_messages = [messages[i] for i in plan.retained_indices]

    pending_tool_use_id: str | None = None
    for message in retained_messages:
        if message.role == "assistant" and isinstance(
            message.content, list
        ):
            tool_use_blocks = [
                block
                for block in message.content
                if block.get("type") == "tool_use"
            ]
            if tool_use_blocks:
                assert pending_tool_use_id is None, (
                    "a tool_use appeared before the previous one's "
                    "tool_result"
                )
                pending_tool_use_id = tool_use_blocks[0]["id"]
                continue

        if message.role == "user" and isinstance(message.content, list):
            tool_result_blocks = [
                block
                for block in message.content
                if block.get("type") == "tool_result"
            ]
            if tool_result_blocks:
                assert pending_tool_use_id is not None, (
                    "a tool_result appeared with no preceding "
                    "tool_use"
                )
                assert (
                    tool_result_blocks[0]["tool_use_id"]
                    == pending_tool_use_id
                )
                pending_tool_use_id = None

    assert pending_tool_use_id is None, (
        "history ends with an unanswered tool_use"
    )
