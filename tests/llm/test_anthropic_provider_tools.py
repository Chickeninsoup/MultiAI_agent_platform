from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from src.domain.tools.tool_definition import ToolDefinition
from src.llm.anthropic_provider import AnthropicProvider
from src.llm.types import (
    LLMMessage,
    LLMRequest,
    LLMTextBlock,
    LLMToolUseBlock,
)


def create_provider_with_mock_response(
    response: SimpleNamespace,
) -> tuple[AnthropicProvider, Mock]:
    provider = AnthropicProvider(
        api_key="test-key",
    )

    mock_create = Mock(return_value=response)
    provider._client.messages.create = mock_create

    return provider, mock_create


def test_sends_tools_to_anthropic() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text="I will inspect the repository.",
            ),
        ],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=20,
            output_tokens=10,
        ),
    )

    provider, mock_create = (
        create_provider_with_mock_response(response)
    )

    request = LLMRequest(
        system_prompt="You are a coding agent.",
        messages=[
            LLMMessage(
                role="user",
                content="Inspect the repository.",
            )
        ],
        model="test-model",
        max_tokens=1000,
        tools=[
            ToolDefinition(
                name="read_file",
                description="Read a repository text file.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                        }
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            )
        ],
    )

    provider.complete(request)

    call_arguments = mock_create.call_args.kwargs

    assert call_arguments["tools"] == [
        {
            "name": "read_file",
            "description": (
                "Read a repository text file."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        }
    ]


def test_omits_tools_when_request_has_none() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text="Hello.",
            )
        ],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=5,
            output_tokens=2,
        ),
    )

    provider, mock_create = (
        create_provider_with_mock_response(response)
    )

    request = LLMRequest(
        system_prompt="You are helpful.",
        messages=[
            LLMMessage(
                role="user",
                content="Hello.",
            )
        ],
        model="test-model",
        max_tokens=100,
    )

    provider.complete(request)

    call_arguments = mock_create.call_args.kwargs

    assert "tools" not in call_arguments


def test_parses_text_and_tool_use_blocks() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text="I need to inspect the file.",
            ),
            SimpleNamespace(
                type="tool_use",
                id="toolu_123",
                name="read_file",
                input={
                    "path": "src/main.py",
                },
            ),
        ],
        stop_reason="tool_use",
        usage=SimpleNamespace(
            input_tokens=30,
            output_tokens=15,
        ),
    )

    provider, _ = create_provider_with_mock_response(
        response
    )

    request = LLMRequest(
        system_prompt="You are a coding agent.",
        messages=[
            LLMMessage(
                role="user",
                content="Inspect src/main.py.",
            )
        ],
        model="test-model",
        max_tokens=1000,
    )

    result = provider.complete(request)

    assert result.stop_reason == "tool_use"
    assert len(result.content) == 2

    assert isinstance(
        result.content[0],
        LLMTextBlock,
    )
    assert result.content[0].text == (
        "I need to inspect the file."
    )

    assert isinstance(
        result.content[1],
        LLMToolUseBlock,
    )
    assert result.content[1].id == "toolu_123"
    assert result.content[1].name == "read_file"
    assert result.content[1].input == {
        "path": "src/main.py",
    }

    assert result.has_tool_calls is True
    assert len(result.tool_calls) == 1
    assert result.text == (
        "I need to inspect the file."
    )


def test_parses_multiple_tool_calls() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                id="toolu_1",
                name="list_files",
                input={
                    "path": ".",
                    "recursive": False,
                },
            ),
            SimpleNamespace(
                type="tool_use",
                id="toolu_2",
                name="git_status",
                input={},
            ),
        ],
        stop_reason="tool_use",
        usage=SimpleNamespace(
            input_tokens=35,
            output_tokens=20,
        ),
    )

    provider, _ = create_provider_with_mock_response(
        response
    )

    request = LLMRequest(
        system_prompt="You are a coding agent.",
        messages=[
            LLMMessage(
                role="user",
                content="Inspect repository state.",
            )
        ],
        model="test-model",
        max_tokens=1000,
    )

    result = provider.complete(request)

    assert len(result.tool_calls) == 2
    assert result.tool_calls[0].name == "list_files"
    assert result.tool_calls[1].name == "git_status"

