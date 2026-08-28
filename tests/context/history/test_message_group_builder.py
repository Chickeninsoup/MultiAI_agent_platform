from __future__ import annotations

from src.context.history.message_group import (
    MessageGroup,
    MessageGroupKind,
)
from src.context.history.message_group_builder import (
    MessageGroupBuilder,
)
from src.llm.types import LLMMessage

INITIAL_TASK = MessageGroupKind.INITIAL_TASK
NORMAL = MessageGroupKind.NORMAL
TOOL_EXCHANGE = MessageGroupKind.TOOL_EXCHANGE


def _tool_use(
    tool_id: str = "call-1", name: str = "read_file"
) -> LLMMessage:
    return LLMMessage(
        role="assistant",
        content=[
            {
                "type": "tool_use",
                "id": tool_id,
                "name": name,
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


def test_empty_history_produces_no_groups() -> None:
    builder = MessageGroupBuilder()

    assert builder.build([]) == []


def test_first_message_is_always_initial_task() -> None:
    builder = MessageGroupBuilder()
    messages = [_text("user", "implement login")]

    groups = builder.build(messages)

    assert groups == [MessageGroup(indices=(0,), kind=INITIAL_TASK)]


def test_the_documented_example_groups_as_expected() -> None:
    builder = MessageGroupBuilder()
    messages = [
        _text("user", "implement login"),  # 0
        _text("assistant", "let me inspect files"),  # 1
        _tool_use(),  # 2
        _tool_result(),  # 3
        _text("assistant", "found bug"),  # 4
    ]

    groups = builder.build(messages)

    assert groups == [
        MessageGroup(indices=(0,), kind=INITIAL_TASK),
        MessageGroup(indices=(1,), kind=NORMAL),
        MessageGroup(
            indices=(2, 3), kind=TOOL_EXCHANGE, tool_name="read_file"
        ),
        MessageGroup(indices=(4,), kind=NORMAL),
    ]


def test_realistic_executor_shaped_history_groups_correctly() -> None:
    # Matches how LLMRunExecutor actually appends messages: one user
    # message (the task), then alternating assistant/tool_use ->
    # user/tool_result rounds, ending on a text-only assistant reply.
    builder = MessageGroupBuilder()
    messages = [
        _text("user", "fix the login bug"),  # 0
        _tool_use("call-1"),  # 1
        _tool_result("call-1"),  # 2
        _tool_use("call-2"),  # 3
        _tool_result("call-2"),  # 4
        _text("assistant", "done"),  # 5
    ]

    groups = builder.build(messages)

    assert groups == [
        MessageGroup(indices=(0,), kind=INITIAL_TASK),
        MessageGroup(
            indices=(1, 2), kind=TOOL_EXCHANGE, tool_name="read_file"
        ),
        MessageGroup(
            indices=(3, 4), kind=TOOL_EXCHANGE, tool_name="read_file"
        ),
        MessageGroup(indices=(5,), kind=NORMAL),
    ]


def test_trailing_tool_use_without_a_result_is_not_grouped() -> None:
    builder = MessageGroupBuilder()
    messages = [
        _text("user", "fix the bug"),  # 0
        _tool_use(),  # 1, no following tool_result
    ]

    groups = builder.build(messages)

    assert groups == [
        MessageGroup(indices=(0,), kind=INITIAL_TASK),
        MessageGroup(indices=(1,), kind=NORMAL),
    ]


def test_tool_use_followed_by_non_tool_result_is_not_grouped() -> None:
    builder = MessageGroupBuilder()
    messages = [
        _text("user", "fix the bug"),  # 0
        _tool_use(),  # 1
        _text("assistant", "unrelated text"),  # 2, not a tool_result
    ]

    groups = builder.build(messages)

    assert groups == [
        MessageGroup(indices=(0,), kind=INITIAL_TASK),
        MessageGroup(indices=(1,), kind=NORMAL),
        MessageGroup(indices=(2,), kind=NORMAL),
    ]


def test_builder_never_mutates_the_input_messages() -> None:
    builder = MessageGroupBuilder()
    messages = [
        _text("user", "fix the bug"),
        _tool_use(),
        _tool_result(),
    ]
    original = list(messages)

    builder.build(messages)

    assert messages == original


def test_tool_exchange_group_carries_its_tool_name() -> None:
    builder = MessageGroupBuilder()
    messages = [
        _text("user", "fix the bug"),
        _tool_use(name="apply_patch"),
        _tool_result(),
    ]

    groups = builder.build(messages)

    assert groups[1].tool_name == "apply_patch"


def test_non_exchange_groups_have_no_tool_name() -> None:
    builder = MessageGroupBuilder()
    messages = [
        _text("user", "fix the bug"),
        _text("assistant", "looking into it"),
    ]

    groups = builder.build(messages)

    assert groups[0].tool_name is None
    assert groups[1].tool_name is None


def test_different_exchanges_carry_their_own_distinct_tool_names() -> (
    None
):
    builder = MessageGroupBuilder()
    messages = [
        _text("user", "fix the bug"),  # 0
        _tool_use("call-1", name="read_file"),  # 1
        _tool_result("call-1"),  # 2
        _tool_use("call-2", name="apply_patch"),  # 3
        _tool_result("call-2"),  # 4
        _tool_use("call-3", name="search"),  # 5
        _tool_result("call-3"),  # 6
    ]

    groups = builder.build(messages)

    assert [group.tool_name for group in groups] == [
        None,  # initial task
        "read_file",
        "apply_patch",
        "search",
    ]
