from __future__ import annotations

from src.context.history.history_budget import HistoryBudget
from src.context.history.message_group import (
    MessageGroup,
    MessageGroupKind,
)
from src.context.history.rule_based_history_compactor import (
    RuleBasedHistoryCompactor,
)
from src.llm.types import LLMMessage


def _messages(count: int) -> list[LLMMessage]:
    return [
        LLMMessage(role="user", content=f"message {i}")
        for i in range(count)
    ]


def _tool_use(tool_id: str = "call-1") -> LLMMessage:
    return LLMMessage(
        role="assistant",
        content=[
            {
                "type": "tool_use",
                "id": tool_id,
                "name": "read_file",
                "input": {"path": "src/main.py"},
            }
        ],
    )


def _tool_result(tool_id: str = "call-1") -> LLMMessage:
    return LLMMessage(
        role="user",
        content=[
            {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": "file contents",
                "is_error": False,
            }
        ],
    )


def _text(role: str, text: str) -> LLMMessage:
    return LLMMessage(role=role, content=text)


class FakeGroupBuilder:
    """Lets tests inject a fixed grouping instead of relying on the
    real MessageGroupBuilder, so budget-packing behavior can be
    tested independently of grouping behavior."""

    def __init__(self, groups: list[MessageGroup]) -> None:
        self._groups = groups

    def build(self, messages: list[LLMMessage]) -> list[MessageGroup]:
        return self._groups


# --- compact(messages, budget): token-budget packing -----------------


def test_empty_messages_produce_an_empty_plan() -> None:
    compactor = RuleBasedHistoryCompactor()

    plan = compactor.compact([], HistoryBudget(max_tokens=1000))

    assert plan.original_count == 0
    assert plan.retained_indices == []


def test_generous_budget_retains_every_message() -> None:
    compactor = RuleBasedHistoryCompactor()
    messages = _messages(10)

    plan = compactor.compact(messages, HistoryBudget(max_tokens=100_000))

    assert plan.original_count == 10
    assert plan.retained_indices == list(range(10))


def test_initial_group_is_retained_even_if_it_alone_exceeds_budget() -> (
    None
):
    compactor = RuleBasedHistoryCompactor()
    messages = _messages(5)

    plan = compactor.compact(messages, HistoryBudget(max_tokens=0))

    assert plan.retained_indices == [0]


def test_small_budget_keeps_only_the_most_recent_messages_that_fit() -> (
    None
):
    compactor = RuleBasedHistoryCompactor()
    # Each plain-text message is a single-message NORMAL group.
    messages = _messages(10)
    group_builder = compactor._group_builder
    groups = group_builder.build(messages)
    tokens_per_group = compactor._estimate_group(
        messages, groups[-1]
    )
    initial_tokens = compactor._estimate_group(messages, groups[0])
    # Budget for the initial group + exactly 2 more recent groups.
    budget = HistoryBudget(
        max_tokens=initial_tokens + 2 * tokens_per_group
    )

    plan = compactor.compact(messages, budget)

    assert plan.retained_indices == [0, 8, 9]


def test_a_small_older_group_can_be_picked_up_past_a_bigger_blocker() -> (
    None
):
    # Since Step 3B (GroupSelector), selection is priority-pass based,
    # not a single stop-at-first-miss scan: a non-fitting group no
    # longer blocks smaller older groups behind it from being picked
    # up in a later pass, as long as the budget allows. The big group
    # itself still never fits and is never retained.
    messages = [
        _text("user", "task"),  # 0: initial
        _text("assistant", "a"),  # 1: small, older
        _text("assistant", "x" * 4000),  # 2: huge, never fits
        _text("assistant", "b"),  # 3: small, newest
    ]
    groups = [
        MessageGroup(indices=(0,), kind=MessageGroupKind.INITIAL_TASK),
        MessageGroup(indices=(1,), kind=MessageGroupKind.NORMAL),
        MessageGroup(indices=(2,), kind=MessageGroupKind.NORMAL),
        MessageGroup(indices=(3,), kind=MessageGroupKind.NORMAL),
    ]
    compactor = RuleBasedHistoryCompactor(
        group_builder=FakeGroupBuilder(groups)
    )
    initial_tokens = compactor._estimate_group(messages, groups[0])
    newest_tokens = compactor._estimate_group(messages, groups[3])
    small_old_tokens = compactor._estimate_group(
        messages, groups[1]
    )
    # Enough for initial + newest + the older small group, but nowhere
    # near enough for the huge blocking group.
    budget = HistoryBudget(
        max_tokens=initial_tokens
        + newest_tokens
        + small_old_tokens
        + 5
    )

    plan = compactor.compact(messages, budget)

    assert plan.retained_indices == [0, 1, 3]
    assert 2 not in plan.retained_indices


def test_tool_exchange_group_is_never_split_by_budget() -> None:
    # 0 user task | 1 assistant tool_use | 2 user tool_result
    messages = [
        _text("user", "implement login"),
        _tool_use(),
        _tool_result(),
    ]
    compactor = RuleBasedHistoryCompactor()
    groups = compactor._group_builder.build(messages)
    initial_tokens = compactor._estimate_group(messages, groups[0])
    exchange_tokens = compactor._estimate_group(
        messages, groups[1]
    )
    # Budget for initial + the tool exchange pair, nothing more.
    budget = HistoryBudget(max_tokens=initial_tokens + exchange_tokens)

    plan = compactor.compact(messages, budget)

    assert (1 in plan.retained_indices) == (2 in plan.retained_indices)
    assert plan.retained_indices == [0, 1, 2]


def test_tool_exchange_group_is_dropped_whole_when_it_does_not_fit() -> (
    None
):
    # 0 user task | 1 assistant tool_use | 2 user tool_result | 3 text
    # The trailing "done" text is newest and gets scanned first,
    # leaving no room for the exchange pair - it must be dropped
    # entirely, never half-retained.
    messages = [
        _text("user", "implement login"),
        _tool_use(),
        _tool_result(),
        _text("assistant", "done"),
    ]
    compactor = RuleBasedHistoryCompactor()
    groups = compactor._group_builder.build(messages)
    initial_tokens = compactor._estimate_group(messages, groups[0])
    newest_tokens = compactor._estimate_group(messages, groups[2])
    budget = HistoryBudget(max_tokens=initial_tokens + newest_tokens)

    plan = compactor.compact(messages, budget)

    assert (1 in plan.retained_indices) == (2 in plan.retained_indices)
    assert plan.retained_indices == [0, 3]


def test_retained_indices_are_sorted_and_deduplicated() -> None:
    compactor = RuleBasedHistoryCompactor()
    messages = _messages(20)

    plan = compactor.compact(messages, HistoryBudget(max_tokens=100_000))

    assert plan.retained_indices == sorted(set(plan.retained_indices))


def test_original_count_matches_input_length() -> None:
    compactor = RuleBasedHistoryCompactor()

    plan = compactor.compact(_messages(20), HistoryBudget(max_tokens=1))

    assert plan.original_count == 20


def test_compact_never_mutates_the_input_messages() -> None:
    compactor = RuleBasedHistoryCompactor()
    messages = _messages(20)
    original = list(messages)

    compactor.compact(messages, HistoryBudget(max_tokens=50))

    assert messages == original


def test_group_builder_can_be_injected() -> None:
    groups = [
        MessageGroup(indices=(0,), kind=MessageGroupKind.INITIAL_TASK)
    ]
    compactor = RuleBasedHistoryCompactor(
        group_builder=FakeGroupBuilder(groups)
    )

    plan = compactor.compact(_messages(1), HistoryBudget(max_tokens=1000))

    assert plan.retained_indices == [0]


def test_size_estimator_can_be_injected() -> None:
    class HugeEstimator:
        def estimate(self, messages) -> int:
            return 999_999

    compactor = RuleBasedHistoryCompactor(
        size_estimator=HugeEstimator()
    )
    messages = _messages(5)

    plan = compactor.compact(messages, HistoryBudget(max_tokens=1))

    # Every group looks huge to the injected estimator, so only the
    # mandatory initial group survives.
    assert plan.retained_indices == [0]


def test_size_estimator_receives_only_the_groups_own_messages() -> None:
    class RecordingEstimator:
        def __init__(self) -> None:
            self.calls: list[list] = []

        def estimate(self, messages) -> int:
            self.calls.append(list(messages))
            return 1

    estimator = RecordingEstimator()
    compactor = RuleBasedHistoryCompactor(size_estimator=estimator)
    messages = [
        _text("user", "task"),
        _tool_use(),
        _tool_result(),
    ]

    compactor.compact(messages, HistoryBudget(max_tokens=1000))

    # The exchange group's call should carry exactly its own 2
    # messages, not the whole history.
    exchange_calls = [call for call in estimator.calls if len(call) == 2]
    assert exchange_calls == [[messages[1], messages[2]]]


# --- _compact_by_recent_group_count(): preserved fallback -------------


def test_fallback_short_history_retains_every_message() -> None:
    compactor = RuleBasedHistoryCompactor()
    messages = _messages(3)

    plan = compactor._compact_by_recent_group_count(messages)

    assert plan.original_count == 3
    assert plan.retained_indices == [0, 1, 2]


def test_fallback_retains_first_and_most_recent_groups() -> None:
    compactor = RuleBasedHistoryCompactor()
    messages = _messages(20)

    plan = compactor._compact_by_recent_group_count(messages)

    assert 0 in plan.retained_indices
    assert plan.retained_indices[-1] == 19
    assert set(range(14, 20)).issubset(set(plan.retained_indices))
    assert 10 not in plan.retained_indices


def test_fallback_never_mutates_the_input_messages() -> None:
    compactor = RuleBasedHistoryCompactor()
    messages = _messages(20)
    original = list(messages)

    compactor._compact_by_recent_group_count(messages)

    assert messages == original
