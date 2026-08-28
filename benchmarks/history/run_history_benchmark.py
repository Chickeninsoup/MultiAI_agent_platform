"""Local, deterministic benchmark for History Compression (5D-6B-4).

Not a pytest test and not a live-API smoke test - it measures the
compaction pipeline itself (MessageGroupBuilder -> GroupSelector ->
RuleBasedHistoryCompactor) against a synthetic but realistic long
agent history, so results are free, instant, and reproducible instead
of depending on how many real API rounds a live task happens to
produce before something else (like the real cumulative token
ceiling) cuts the run short - which is exactly what happened in the
5D-6B-4 smoke test: real runs so far have never pushed history past
its budget before the run failed for an unrelated reason (a
task-irrelevant-content problem, not a compaction problem). This
benchmark constructs a history big enough to make compaction actually
engage, so its effect is visible and measurable.

Run: python -m benchmarks.history.run_history_benchmark
"""

from __future__ import annotations

import json
from pathlib import Path

from src.context.history.apply_compaction_plan import (
    apply_compaction_plan,
)
from src.context.history.char_based_history_size_estimator import (
    CharBasedHistorySizeEstimator,
)
from src.context.history.history_budget import HistoryBudget
from src.context.history.message_group_builder import (
    MessageGroupBuilder,
)
from src.context.history.rule_based_history_compactor import (
    RuleBasedHistoryCompactor,
)
from src.llm.types import LLMMessage

ROUNDS = 80
DISABLED_BUDGET = HistoryBudget(max_tokens=10_000_000)
ENABLED_BUDGET = HistoryBudget(max_tokens=8_000)

# Every 5th round does a state-changing edit (protected); most rounds
# read/search (evictable); the rest are plain back-and-forth text
# (normal) - a rough approximation of a real long coding session.
# ROUNDS is deliberately large (not just "a few over budget") -
# early rounds never need compaction at all (history hasn't grown
# past ENABLED_BUDGET yet), so a short benchmark dilutes the
# steady-state savings with a lot of "nothing to compress yet"
# rounds. A long session is where compaction's benefit actually
# compounds, so that's what this measures.
_TOOL_RESULT_CHARS = 2_000


def _initial_task() -> LLMMessage:
    return LLMMessage(
        role="user", content="Add a small validation feature."
    )


def _tool_exchange(
    round_index: int, tool_name: str
) -> list[LLMMessage]:
    call_id = f"call-{round_index}"
    return [
        LLMMessage(
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "id": call_id,
                    "name": tool_name,
                    "input": {"path": f"file_{round_index}.py"},
                }
            ],
        ),
        LLMMessage(
            role="user",
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": "x" * _TOOL_RESULT_CHARS,
                    "is_error": False,
                }
            ],
        ),
    ]


def _normal_exchange(round_index: int) -> list[LLMMessage]:
    return [
        LLMMessage(
            role="assistant",
            content=f"round {round_index}: thinking out loud",
        )
    ]


def _round_tool_name(round_index: int) -> str | None:
    if round_index % 5 == 0:
        return "apply_patch"

    if round_index % 3 == 0:
        return None  # plain text round, no tool call

    return "read_file"


def build_full_history(rounds: int = ROUNDS) -> list[LLMMessage]:
    messages = [_initial_task()]

    for round_index in range(1, rounds + 1):
        tool_name = _round_tool_name(round_index)

        if tool_name is None:
            messages.extend(_normal_exchange(round_index))
        else:
            messages.extend(_tool_exchange(round_index, tool_name))

    return messages


def _simulate_run(
    full_history: list[LLMMessage],
    budget: HistoryBudget,
    compactor: RuleBasedHistoryCompactor,
    estimator: CharBasedHistorySizeEstimator,
) -> dict:
    """Replays the run round-by-round, the way LLMRunExecutor does:
    at each round `messages` has grown by one more exchange, and
    compact() is re-run fresh against the full history so far."""

    total_sent_tokens = 0
    broken_tool_pairs = 0
    group_builder = MessageGroupBuilder()

    # Walk forward one message-group at a time, mirroring how the
    # real executor's `messages` list grows one exchange per round.
    groups_so_far = group_builder.build(full_history)
    cursor = 0

    for group in groups_so_far:
        cursor = max(cursor, group.indices[-1] + 1)
        messages_so_far = full_history[:cursor]

        plan = compactor.compact(messages_so_far, budget)
        sent_messages = apply_compaction_plan(messages_so_far, plan)
        total_sent_tokens += estimator.estimate(sent_messages)

        broken_tool_pairs += _count_broken_pairs(sent_messages)

    return {
        "input_tokens": total_sent_tokens,
        "broken_tool_pairs": broken_tool_pairs,
    }


def _count_broken_pairs(messages: list[LLMMessage]) -> int:
    """Counts any tool_use with no matching following tool_result (or
    vice versa) in a retained message sequence - the same protocol
    check used in tests/context/history/test_history_compaction_stress.py."""

    broken = 0
    pending_id: str | None = None

    for message in messages:
        if message.role == "assistant" and isinstance(
            message.content, list
        ):
            tool_use_blocks = [
                block
                for block in message.content
                if block.get("type") == "tool_use"
            ]
            if tool_use_blocks:
                if pending_id is not None:
                    broken += 1
                pending_id = tool_use_blocks[0]["id"]
                continue

        if message.role == "user" and isinstance(message.content, list):
            tool_result_blocks = [
                block
                for block in message.content
                if block.get("type") == "tool_result"
            ]
            if tool_result_blocks:
                if pending_id is None:
                    broken += 1
                elif (
                    tool_result_blocks[0]["tool_use_id"] != pending_id
                ):
                    broken += 1
                pending_id = None

    if pending_id is not None:
        broken += 1

    return broken


def run_benchmark() -> dict:
    estimator = CharBasedHistorySizeEstimator()
    full_history = build_full_history(ROUNDS)

    without_compaction = _simulate_run(
        full_history,
        DISABLED_BUDGET,
        RuleBasedHistoryCompactor(size_estimator=estimator),
        estimator,
    )
    with_compaction = _simulate_run(
        full_history,
        ENABLED_BUDGET,
        RuleBasedHistoryCompactor(size_estimator=estimator),
        estimator,
    )

    compression_ratio = 1 - (
        with_compaction["input_tokens"]
        / without_compaction["input_tokens"]
    )

    return {
        "task": "retention_test",
        "rounds": ROUNDS,
        "without_compaction": {
            "input_tokens": without_compaction["input_tokens"],
        },
        "with_compaction": {
            "input_tokens": with_compaction["input_tokens"],
        },
        "compression_ratio": round(compression_ratio, 4),
        "broken_tool_pairs": with_compaction["broken_tool_pairs"],
    }


def main() -> None:
    result = run_benchmark()
    print(json.dumps(result, indent=2))

    output_path = Path(__file__).parent / "last_result.json"
    output_path.write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
