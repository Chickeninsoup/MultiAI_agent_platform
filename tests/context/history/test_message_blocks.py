from __future__ import annotations

from src.context.history.message_blocks import (
    get_tool_name,
    has_content_block_type,
)
from src.llm.types import LLMMessage


def _tool_use(name: str = "read_file") -> LLMMessage:
    return LLMMessage(
        role="assistant",
        content=[
            {
                "type": "tool_use",
                "id": "call-1",
                "name": name,
                "input": {"path": "src/main.py"},
            }
        ],
    )


def _tool_result() -> LLMMessage:
    return LLMMessage(
        role="user",
        content=[
            {
                "type": "tool_result",
                "tool_use_id": "call-1",
                "content": "result",
                "is_error": False,
            }
        ],
    )


def test_get_tool_name_reads_the_tool_use_block() -> None:
    assert get_tool_name(_tool_use("read_file")) == "read_file"


def test_get_tool_name_reads_a_different_tool_correctly() -> None:
    assert get_tool_name(_tool_use("apply_patch")) == "apply_patch"


def test_get_tool_name_is_none_for_plain_text() -> None:
    message = LLMMessage(role="user", content="hello")

    assert get_tool_name(message) is None


def test_get_tool_name_is_none_for_a_tool_result_message() -> None:
    assert get_tool_name(_tool_result()) is None


def test_has_content_block_type_true_for_matching_block() -> None:
    assert has_content_block_type(_tool_use(), "tool_use") is True


def test_has_content_block_type_false_for_non_matching_block() -> None:
    assert has_content_block_type(_tool_use(), "tool_result") is False


def test_has_content_block_type_false_for_plain_text() -> None:
    message = LLMMessage(role="user", content="hello")

    assert has_content_block_type(message, "tool_use") is False
