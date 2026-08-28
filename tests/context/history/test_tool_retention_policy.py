from __future__ import annotations

from src.context.history.tool_retention_policy import (
    RuleBasedToolRetentionPolicy,
    ToolRetentionClass,
)


def test_apply_patch_is_protected() -> None:
    policy = RuleBasedToolRetentionPolicy()

    assert (
        policy.classify("apply_patch") == ToolRetentionClass.PROTECTED
    )


def test_write_file_is_protected() -> None:
    policy = RuleBasedToolRetentionPolicy()

    assert policy.classify("write_file") == ToolRetentionClass.PROTECTED


def test_read_file_is_evictable() -> None:
    policy = RuleBasedToolRetentionPolicy()

    assert policy.classify("read_file") == ToolRetentionClass.EVICTABLE


def test_list_files_is_evictable() -> None:
    policy = RuleBasedToolRetentionPolicy()

    assert (
        policy.classify("list_files") == ToolRetentionClass.EVICTABLE
    )


def test_unknown_tool_is_normal() -> None:
    policy = RuleBasedToolRetentionPolicy()

    assert (
        policy.classify("future_unknown_tool")
        == ToolRetentionClass.NORMAL
    )


def test_none_is_normal() -> None:
    policy = RuleBasedToolRetentionPolicy()

    assert policy.classify(None) == ToolRetentionClass.NORMAL


def test_retention_class_has_exactly_three_values() -> None:
    assert {member.value for member in ToolRetentionClass} == {
        "protected",
        "normal",
        "evictable",
    }
