from __future__ import annotations

from src.context.context_usage_builder import ContextUsageBuilder
from src.domain.tools.tool_definition import ToolDefinition
from src.llm.types import LLMMessage, LLMRequest


class FixedSizeEstimator:
    """Estimates any message list as its combined content length, so
    tests can assert exact expected numbers without depending on the
    real char//4 heuristic's internals."""

    def estimate(self, messages: list[LLMMessage]) -> int:
        return sum(len(str(message.content)) for message in messages)


def _request(
    *,
    system_prompt: str = "sys",
    messages: list[LLMMessage],
    tools: list[ToolDefinition] | None = None,
) -> LLMRequest:
    return LLMRequest(
        system_prompt=system_prompt,
        messages=messages,
        model="fake-model",
        max_tokens=100,
        tools=tools or [],
    )


def test_breakdown_reports_initial_and_history_after_from_request() -> (
    None
):
    builder = ContextUsageBuilder(FixedSizeEstimator())
    request = _request(
        messages=[
            LLMMessage(role="user", content="task"),
            LLMMessage(role="assistant", content="reply"),
        ]
    )

    breakdown = builder.build(request, full_messages=request.messages)

    assert breakdown.initial_message_tokens == len("task")
    assert breakdown.history_after_tokens == len("reply")


def test_breakdown_reports_history_before_from_full_messages() -> None:
    builder = ContextUsageBuilder(FixedSizeEstimator())
    full_messages = [
        LLMMessage(role="user", content="task"),
        LLMMessage(role="assistant", content="dropped-by-compaction"),
        LLMMessage(role="assistant", content="kept"),
    ]
    # Compacted request only carries the initial task + one message.
    compacted_request = _request(
        messages=[full_messages[0], full_messages[2]]
    )

    breakdown = builder.build(compacted_request, full_messages)

    assert breakdown.history_before_tokens == len(
        "dropped-by-compaction"
    ) + len("kept")
    assert breakdown.history_after_tokens == len("kept")


def test_breakdown_estimates_system_prompt() -> None:
    builder = ContextUsageBuilder(FixedSizeEstimator())
    request = _request(
        system_prompt="you are an agent",
        messages=[LLMMessage(role="user", content="task")],
    )

    breakdown = builder.build(request, full_messages=request.messages)

    assert breakdown.system_prompt_tokens == len("you are an agent")


def test_breakdown_is_zero_for_no_tools() -> None:
    builder = ContextUsageBuilder(FixedSizeEstimator())
    request = _request(messages=[LLMMessage(role="user", content="t")])

    breakdown = builder.build(request, full_messages=request.messages)

    assert breakdown.tool_definition_tokens == 0


def test_breakdown_estimates_tool_definitions_when_present() -> None:
    builder = ContextUsageBuilder(FixedSizeEstimator())
    request = _request(
        messages=[LLMMessage(role="user", content="t")],
        tools=[
            ToolDefinition(
                name="read_file",
                description="Read a file.",
                input_schema={"type": "object"},
            )
        ],
    )

    breakdown = builder.build(request, full_messages=request.messages)

    assert breakdown.tool_definition_tokens > 0
