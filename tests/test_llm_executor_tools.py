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
from src.run_events import InMemoryRunEventSink


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

    assert result.final_response.text == "The file contains hello."
    assert provider.call_count == 2
    assert result.llm_rounds == 2
    assert result.tool_rounds == 1
    assert result.tool_calls == 1
    assert result.total_input_tokens == 10 + 15
    assert result.total_output_tokens == 5 + 6

    assert [event["type"] for event in result.events] == [
        "compaction_report",
        "context_usage",
        "llm_response",
        "tool_call",
        "tool_result",
        "compaction_report",
        "context_usage",
        "llm_response",
        "run_completed",
    ]

    tool_call_event = result.events[3]
    assert tool_call_event["name"] == "read_file"
    assert tool_call_event["input"] == {"path": "example.txt"}

    tool_result_event = result.events[4]
    assert tool_result_event["name"] == "read_file"
    assert tool_result_event["success"] is True
    assert tool_result_event["output_chars"] == len("1: hello")
    assert "output" not in tool_result_event

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

    result = executor.execute(request)

    tool_result_content = (
        provider.requests[1].messages[-1].content
    )

    assert tool_result_content[0]["is_error"] is True
    assert tool_result_content[0]["content"] == (
        "Path does not exist."
    )

    tool_result_event = next(
        event for event in result.events if event["type"] == "tool_result"
    )
    assert tool_result_event["success"] is False
    assert tool_result_event["error_code"] == "PATH_NOT_FOUND"


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
    sink = InMemoryRunEventSink()

    executor = LLMRunExecutor(
        provider=InfiniteToolProvider(),
        tool_executor=FakeToolExecutor(),
        max_tool_rounds=2,
        max_total_tokens=1000,
        event_sink=sink,
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

    event_types = [event["type"] for event in sink.events]
    assert "run_limit_exceeded" in event_types
    assert "run_failed" in event_types

    limit_event = next(
        event
        for event in sink.events
        if event["type"] == "run_limit_exceeded"
    )
    assert limit_event["limit"] == "max_tool_rounds"
    assert limit_event["configured_limit"] == 2

    failed_event = next(
        event for event in sink.events if event["type"] == "run_failed"
    )
    assert failed_event["error_type"] == "LLMRunLimitError"


class CrashingProvider(FakeProvider):
    def complete(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        self.requests.append(request)
        self.call_count += 1

        if self.call_count == 1:
            return LLMResponse(
                content=[
                    LLMToolUseBlock(
                        type="tool_use",
                        id="toolu_1",
                        name="read_file",
                        input={"path": "example.txt"},
                    )
                ],
                stop_reason="tool_use",
                usage=LLMUsage(
                    input_tokens=10,
                    output_tokens=5,
                ),
            )

        raise RuntimeError("Simulated provider failure.")


def test_events_survive_mid_run_failure() -> None:
    sink = InMemoryRunEventSink()

    executor = LLMRunExecutor(
        provider=CrashingProvider(),
        tool_executor=FakeToolExecutor(),
        max_tool_rounds=5,
        max_total_tokens=1000,
        event_sink=sink,
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

    with pytest.raises(
        RuntimeError,
        match="Simulated provider failure",
    ):
        executor.execute(request)

    event_types = [event["type"] for event in sink.events]

    assert "llm_response" in event_types
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert "run_failed" in event_types
    # the run never reached a normal end, so no run_completed
    assert "run_completed" not in event_types


def test_tool_output_is_not_logged_by_default() -> None:
    sink = InMemoryRunEventSink()

    executor = LLMRunExecutor(
        provider=FakeProvider(),
        tool_executor=FakeToolExecutor(),
        max_tool_rounds=5,
        max_total_tokens=1000,
        event_sink=sink,
        debug_log_full_output=False,
    )

    request = LLMRequest(
        system_prompt="You are an agent.",
        messages=[
            LLMMessage(role="user", content="Inspect example.txt."),
        ],
        model="fake-model",
        max_tokens=100,
    )

    executor.execute(request)

    tool_result_event = next(
        event for event in sink.events if event["type"] == "tool_result"
    )
    assert "output" not in tool_result_event


class WriteFileFakeToolExecutor:
    def get_definitions(
        self,
    ) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="write_file",
                description="Write a file.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            )
        ]

    def execute(self, tool_call) -> ToolResult:
        assert tool_call.name == "write_file"

        return ToolResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=True,
            output="Created example.txt",
            metadata={
                "path": "example.txt",
                "mode": "create",
                "created": True,
                "overwritten": False,
                "bytes_written": 5,
                "before_sha256": None,
                "after_sha256": "deadbeef",
            },
        )


class WriteFileProvider(FakeProvider):
    def complete(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        self.requests.append(request)
        self.call_count += 1

        if self.call_count == 1:
            return LLMResponse(
                content=[
                    LLMToolUseBlock(
                        type="tool_use",
                        id="toolu_1",
                        name="write_file",
                        input={
                            "path": "example.txt",
                            "content": "hello",
                        },
                    )
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
                    text="Created the file.",
                )
            ],
            stop_reason="end_turn",
            usage=LLMUsage(
                input_tokens=15,
                output_tokens=6,
            ),
        )


def test_write_file_result_emits_file_mutation_event() -> None:
    sink = InMemoryRunEventSink()

    executor = LLMRunExecutor(
        provider=WriteFileProvider(),
        tool_executor=WriteFileFakeToolExecutor(),
        max_tool_rounds=5,
        max_total_tokens=1000,
        event_sink=sink,
    )

    request = LLMRequest(
        system_prompt="You are an agent.",
        messages=[
            LLMMessage(role="user", content="Create example.txt."),
        ],
        model="fake-model",
        max_tokens=100,
    )

    executor.execute(request)

    event_types = [event["type"] for event in sink.events]
    assert event_types == [
        "compaction_report",
        "context_usage",
        "llm_response",
        "tool_call",
        "tool_result",
        "file_mutation",
        "compaction_report",
        "context_usage",
        "llm_response",
        "run_completed",
    ]

    mutation_event = next(
        event
        for event in sink.events
        if event["type"] == "file_mutation"
    )
    assert mutation_event["tool_call_id"] == "toolu_1"
    assert mutation_event["operation"] == "create"
    assert mutation_event["path"] == "example.txt"
    assert mutation_event["before_sha256"] is None
    assert mutation_event["after_sha256"] == "deadbeef"
    assert mutation_event["bytes_written"] == 5


def test_read_only_tool_does_not_emit_file_mutation_event() -> None:
    sink = InMemoryRunEventSink()

    executor = LLMRunExecutor(
        provider=FakeProvider(),
        tool_executor=FakeToolExecutor(),
        max_tool_rounds=5,
        max_total_tokens=1000,
        event_sink=sink,
    )

    request = LLMRequest(
        system_prompt="You are an agent.",
        messages=[
            LLMMessage(role="user", content="Inspect example.txt."),
        ],
        model="fake-model",
        max_tokens=100,
    )

    executor.execute(request)

    event_types = [event["type"] for event in sink.events]
    assert "file_mutation" not in event_types


class PatchFileFakeToolExecutor:
    """A tool distinct from write_file, to prove the file_mutation
    event is driven by ToolResult.metadata shape, not tool_name.
    """

    def get_definitions(
        self,
    ) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="patch_file",
                description="Patch a file.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                    },
                    "required": ["path", "old_text", "new_text"],
                },
            )
        ]

    def execute(self, tool_call) -> ToolResult:
        assert tool_call.name == "patch_file"

        return ToolResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=True,
            output="Patched test.py",
            metadata={
                "operation": "patch",
                "path": "test.py",
                "before_sha256": "aaaa",
                "after_sha256": "bbbb",
                "bytes_written": 3,
            },
        )


class PatchFileProvider(FakeProvider):
    def complete(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        self.requests.append(request)
        self.call_count += 1

        if self.call_count == 1:
            return LLMResponse(
                content=[
                    LLMToolUseBlock(
                        type="tool_use",
                        id="toolu_1",
                        name="patch_file",
                        input={
                            "path": "test.py",
                            "old_text": "old",
                            "new_text": "new",
                        },
                    )
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
                    text="Patched the file.",
                )
            ],
            stop_reason="end_turn",
            usage=LLMUsage(
                input_tokens=15,
                output_tokens=6,
            ),
        )


def test_patch_file_result_emits_file_mutation_event() -> None:
    sink = InMemoryRunEventSink()

    executor = LLMRunExecutor(
        provider=PatchFileProvider(),
        tool_executor=PatchFileFakeToolExecutor(),
        max_tool_rounds=5,
        max_total_tokens=1000,
        event_sink=sink,
    )

    request = LLMRequest(
        system_prompt="You are an agent.",
        messages=[
            LLMMessage(role="user", content="Patch test.py."),
        ],
        model="fake-model",
        max_tokens=100,
    )

    executor.execute(request)

    mutation_event = next(
        event
        for event in sink.events
        if event["type"] == "file_mutation"
    )
    assert mutation_event["operation"] == "patch"
    assert mutation_event["path"] == "test.py"
    assert mutation_event["before_sha256"] == "aaaa"
    assert mutation_event["after_sha256"] == "bbbb"
    assert mutation_event["bytes_written"] == 3


def test_full_tool_output_is_logged_in_debug_mode() -> None:
    sink = InMemoryRunEventSink()

    executor = LLMRunExecutor(
        provider=FakeProvider(),
        tool_executor=FakeToolExecutor(),
        max_tool_rounds=5,
        max_total_tokens=1000,
        event_sink=sink,
        debug_log_full_output=True,
    )

    request = LLMRequest(
        system_prompt="You are an agent.",
        messages=[
            LLMMessage(role="user", content="Inspect example.txt."),
        ],
        model="fake-model",
        max_tokens=100,
    )

    executor.execute(request)

    tool_result_event = next(
        event for event in sink.events if event["type"] == "tool_result"
    )
    assert tool_result_event["output"] == "1: hello"
