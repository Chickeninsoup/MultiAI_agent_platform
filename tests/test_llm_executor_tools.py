from pathlib import Path

import pytest

from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult
from src.llm.types import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMTextBlock,
    LLMToolUseBlock,
    LLMUsage,
)
from src.llm_executor import LLMRunExecutor, LLMRunLimitError


class FakeProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self.call_count = 0

    def complete(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        self.requests.append(request)
        self.call_count += 1

        if self.call_count == 1:
            return LLMResponse(
                content=[
                    LLMTextBlock(
                        type="text",
                        text="I will inspect the file.",
                    ),
                    LLMToolUseBlock(
                        type="tool_use",
                        id="toolu_1",
                        name="read_file",
                        input={"path": "example.txt"},
                    ),
                ],
                stop_reason="tool_use",
                usage=LLMUsage(
                    input_tokens=10,
                    output_tokens=5,
                ),
            )

        return LLMResponse(
            content=[
                LLMTextBlock(
                    type="text",
                    text="The file contains hello.",
                )
            ],
            stop_reason="end_turn",
            usage=LLMUsage(
                input_tokens=15,
                output_tokens=6,
            ),
        )


class FakeToolExecutor:
    def get_definitions(
        self,
    ) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="read_file",
                description="Read a file.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                        }
                    },
                    "required": ["path"],
                },
            )
        ]

    def execute(self, tool_call) -> ToolResult:
        assert tool_call.name == "read_file"

        return ToolResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=True,
            output="1: hello",
        )


def test_executes_tool_and_continues_llm_loop() -> None:
    provider = FakeProvider()
    tool_executor = FakeToolExecutor()

    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        max_tool_rounds=5,
        max_total_tokens=1000,
    )

    request = LLMRequest(
        system_prompt="You are an agent.",
        messages=[
            LLMMessage(
                role="user",
                content="Inspect example.txt.",
            )
        ],
        model="fake-model",
        max_tokens=100,
    )

    result = executor.execute(request)

    assert result.text == "The file contains hello."
    assert provider.call_count == 2

    second_request = provider.requests[1]

    assert second_request.messages[-2].role == "assistant"
    assert second_request.messages[-1].role == "user"

    assistant_content = second_request.messages[-2].content
    tool_result_content = second_request.messages[-1].content

    assert assistant_content[1] == {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "read_file",
        "input": {
            "path": "example.txt",
        },
    }

    assert tool_result_content[0] == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": "1: hello",
        "is_error": False,
    }


class FailingToolExecutor(FakeToolExecutor):
    def execute(self, tool_call) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=False,
            output="Path does not exist.",
            error_code="PATH_NOT_FOUND",
        )


def test_tool_failure_is_returned_to_model() -> None:
    provider = FakeProvider()

    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=FailingToolExecutor(),
        max_tool_rounds=5,
        max_total_tokens=1000,
    )

    request = LLMRequest(
        system_prompt="You are an agent.",
        messages=[
            LLMMessage(
                role="user",
                content="Inspect missing.txt.",
            )
        ],
        model="fake-model",
        max_tokens=100,
    )

    executor.execute(request)

    tool_result_content = (
        provider.requests[1].messages[-1].content
    )

    assert tool_result_content[0]["is_error"] is True
    assert tool_result_content[0]["content"] == (
        "Path does not exist."
    )


class InfiniteToolProvider(FakeProvider):
    def complete(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        self.requests.append(request)
        self.call_count += 1

        return LLMResponse(
            content=[
                LLMToolUseBlock(
                    type="tool_use",
                    id=f"toolu_{self.call_count}",
                    name="read_file",
                    input={"path": "example.txt"},
                )
            ],
            stop_reason="tool_use",
            usage=LLMUsage(
                input_tokens=1,
                output_tokens=1,
            ),
        )


def test_rejects_too_many_tool_rounds() -> None:
    executor = LLMRunExecutor(
        provider=InfiniteToolProvider(),
        tool_executor=FakeToolExecutor(),
        max_tool_rounds=2,
        max_total_tokens=1000,
    )

    request = LLMRequest(
        system_prompt="You are an agent.",
        messages=[
            LLMMessage(
                role="user",
                content="Keep reading.",
            )
        ],
        model="fake-model",
        max_tokens=100,
    )

    with pytest.raises(LLMRunLimitError):
        executor.execute(request)
