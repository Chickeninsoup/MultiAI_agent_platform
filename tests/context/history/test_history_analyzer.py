from __future__ import annotations

from src.context.history.rule_based_history_analyzer import (
    RuleBasedHistoryAnalyzer,
)
from src.llm.types import LLMMessage


def test_empty_history_has_zero_messages() -> None:
    analyzer = RuleBasedHistoryAnalyzer()

    analysis = analyzer.analyze([])

    assert analysis.total_messages == 0


def test_analyze_counts_all_messages() -> None:
    analyzer = RuleBasedHistoryAnalyzer()
    messages = [
        LLMMessage(role="user", content="hello"),
        LLMMessage(role="assistant", content="hi"),
    ]

    analysis = analyzer.analyze(messages)

    assert analysis.total_messages == 2


def test_analyze_counts_tool_result_messages() -> None:
    analyzer = RuleBasedHistoryAnalyzer()
    messages = [
        LLMMessage(
            role="user",
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": "call-1",
                    "content": "result",
                    "is_error": False,
                }
            ],
        ),
        LLMMessage(role="user", content="continue"),
    ]

    analysis = analyzer.analyze(messages)

    assert analysis.tool_messages == 1


def test_assistant_tool_use_message_is_not_counted_as_tool_result() -> (
    None
):
    analyzer = RuleBasedHistoryAnalyzer()
    messages = [
        LLMMessage(
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "id": "call-1",
                    "name": "read_file",
                    "input": {"path": "src/main.py"},
                }
            ],
        )
    ]

    analysis = analyzer.analyze(messages)

    assert analysis.tool_messages == 0


def test_estimated_tokens_grows_with_content_size() -> None:
    analyzer = RuleBasedHistoryAnalyzer()
    short_history = [LLMMessage(role="user", content="hi")]
    long_history = [LLMMessage(role="user", content="hi " * 5000)]

    short_analysis = analyzer.analyze(short_history)
    long_analysis = analyzer.analyze(long_history)

    assert long_analysis.estimated_tokens > short_analysis.estimated_tokens


def test_empty_history_estimate_floors_at_one() -> None:
    analyzer = RuleBasedHistoryAnalyzer()

    analysis = analyzer.analyze([])

    assert analysis.estimated_tokens == 1


def test_size_estimator_can_be_injected() -> None:
    class FixedEstimator:
        def estimate(self, messages) -> int:
            return 42

    analyzer = RuleBasedHistoryAnalyzer(size_estimator=FixedEstimator())

    analysis = analyzer.analyze(
        [LLMMessage(role="user", content="hello")]
    )

    assert analysis.estimated_tokens == 42
