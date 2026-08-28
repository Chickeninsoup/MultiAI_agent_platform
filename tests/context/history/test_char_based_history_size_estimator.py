from __future__ import annotations

from src.context.history.char_based_history_size_estimator import (
    CharBasedHistorySizeEstimator,
)
from src.llm.types import LLMMessage


def test_empty_messages_floor_at_one() -> None:
    estimator = CharBasedHistorySizeEstimator()

    assert estimator.estimate([]) == 1


def test_estimate_divides_character_count_by_four() -> None:
    estimator = CharBasedHistorySizeEstimator()
    messages = [LLMMessage(role="user", content="hi")]

    expected = max(1, len(str(messages[0])) // 4)

    assert estimator.estimate(messages) == expected


def test_more_messages_increase_the_estimate() -> None:
    estimator = CharBasedHistorySizeEstimator()
    short_history = [LLMMessage(role="user", content="hi")]
    long_history = [
        LLMMessage(role="user", content="hi"),
        LLMMessage(role="assistant", content="x" * 500),
    ]

    assert estimator.estimate(long_history) > estimator.estimate(
        short_history
    )
