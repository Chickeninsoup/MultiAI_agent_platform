from __future__ import annotations

from src.llm.types import LLMMessage


def test_to_dict_and_from_dict_roundtrip_with_string_content() -> None:
    message = LLMMessage(role="user", content="hello")

    assert LLMMessage.from_dict(message.to_dict()) == message


def test_to_dict_and_from_dict_roundtrip_with_block_content() -> None:
    message = LLMMessage(
        role="assistant",
        content=[
            {"type": "text", "text": "hi"},
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "read_file",
                "input": {"path": "a.py"},
            },
        ],
    )

    assert LLMMessage.from_dict(message.to_dict()) == message
