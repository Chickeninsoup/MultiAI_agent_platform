from __future__ import annotations

from src.context.history.compaction_report_builder import (
    CompactionReportBuilder,
)
from src.context.history.message_group_builder import (
    MessageGroupBuilder,
)
from src.llm.types import LLMMessage


class CountEstimator:
    """Deterministic per-group cost = message count, matching the
    convention used in test_group_selector.py."""

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


def _build_scenario():
    # 0 initial | (1,2) read_file | (3,4) apply_patch
    messages = [
        _text("user", "task"),
        _tool_use("call-1", "read_file"),
        _tool_result("call-1"),
        _tool_use("call-2", "apply_patch"),
        _tool_result("call-2"),
    ]
    groups = MessageGroupBuilder().build(messages)
    return messages, groups


def test_retained_and_removed_counts() -> None:
    messages, groups = _build_scenario()
    builder = CompactionReportBuilder(CountEstimator())

    report = builder.build(messages, groups, retained_positions=[0, 2])

    assert report.retained_count == 2
    assert report.removed_count == 1


def test_protected_group_reason_is_protected_tool() -> None:
    messages, groups = _build_scenario()
    builder = CompactionReportBuilder(CountEstimator())

    report = builder.build(messages, groups, retained_positions=[0, 2])

    apply_patch_entries = [
        entry
        for entry in report.retained_groups
        if entry["tool"] == "apply_patch"
    ]
    assert len(apply_patch_entries) == 1
    assert apply_patch_entries[0]["reason"] == "protected_tool"
    assert apply_patch_entries[0]["group"] == 2
    assert apply_patch_entries[0]["kind"] == "tool_exchange"


def test_initial_group_reason_is_initial_task() -> None:
    messages, groups = _build_scenario()
    builder = CompactionReportBuilder(CountEstimator())

    report = builder.build(messages, groups, retained_positions=[0, 2])

    initial_entries = [
        entry for entry in report.retained_groups if entry["group"] == 0
    ]
    assert initial_entries[0]["reason"] == "initial_task"


def test_removed_group_reason_is_budget_limit() -> None:
    messages, groups = _build_scenario()
    builder = CompactionReportBuilder(CountEstimator())

    report = builder.build(messages, groups, retained_positions=[0, 2])

    assert len(report.removed_groups) == 1
    removed = report.removed_groups[0]
    assert removed["tool"] == "read_file"
    assert removed["reason"] == "budget_limit"


def test_non_protected_retained_group_reason_is_recent_context() -> (
    None
):
    messages = [
        _text("user", "task"),
        _text("assistant", "recent chat"),
    ]
    groups = MessageGroupBuilder().build(messages)
    builder = CompactionReportBuilder(CountEstimator())

    report = builder.build(messages, groups, retained_positions=[0, 1])

    normal_entry = [
        entry for entry in report.retained_groups if entry["group"] == 1
    ][0]
    assert normal_entry["reason"] == "recent_context"


def test_token_totals_reflect_all_groups_vs_retained_only() -> None:
    messages, groups = _build_scenario()
    # groups: G0 (1 msg), G1 read_file (2 msgs), G2 apply_patch (2 msgs)
    builder = CompactionReportBuilder(CountEstimator())

    report = builder.build(messages, groups, retained_positions=[0, 2])

    assert report.original_tokens == 1 + 2 + 2
    assert report.retained_tokens == 1 + 2


def test_report_is_fully_serializable_to_json() -> None:
    import json

    messages, groups = _build_scenario()
    builder = CompactionReportBuilder(CountEstimator())

    report = builder.build(messages, groups, retained_positions=[0, 2])

    # dataclasses.asdict-style manual conversion, since the dict
    # fields are already plain JSON-serializable primitives.
    payload = {
        "retained_count": report.retained_count,
        "removed_count": report.removed_count,
        "original_tokens": report.original_tokens,
        "retained_tokens": report.retained_tokens,
        "retained_groups": report.retained_groups,
        "removed_groups": report.removed_groups,
    }
    json.dumps(payload)  # must not raise
