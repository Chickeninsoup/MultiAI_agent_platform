from __future__ import annotations

import dataclasses

import pytest

from src.context.history.message_group import (
    MessageGroup,
    MessageGroupKind,
)


def test_message_group_holds_indices_and_kind() -> None:
    group = MessageGroup(indices=(2, 3), kind=MessageGroupKind.TOOL_EXCHANGE)

    assert group.indices == (2, 3)
    assert group.kind == MessageGroupKind.TOOL_EXCHANGE


def test_message_group_is_frozen() -> None:
    group = MessageGroup(indices=(0,), kind=MessageGroupKind.INITIAL_TASK)

    with pytest.raises(dataclasses.FrozenInstanceError):
        group.kind = MessageGroupKind.NORMAL


def test_message_group_kind_has_exactly_three_values() -> None:
    assert {kind.value for kind in MessageGroupKind} == {
        "initial_task",
        "normal",
        "tool_exchange",
    }


def test_tool_name_defaults_to_none() -> None:
    group = MessageGroup(indices=(0,), kind=MessageGroupKind.NORMAL)

    assert group.tool_name is None


def test_tool_name_can_be_set() -> None:
    group = MessageGroup(
        indices=(2, 3),
        kind=MessageGroupKind.TOOL_EXCHANGE,
        tool_name="apply_patch",
    )

    assert group.tool_name == "apply_patch"
