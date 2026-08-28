from __future__ import annotations

from src.context.history.compaction_plan import CompactionPlan
from src.context.history.history_budget import HistoryBudget
from src.context.history.message_group_builder import (
    MessageGroupBuilder,
)
from src.context.history.rule_based_history_compactor import (
    RuleBasedHistoryCompactor,
)
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
from src.llm_executor import LLMRunExecutor


class FakeProvider:
    provider_name = "fake"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = responses
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return self._responses[len(self.requests) - 1]


class FakeToolExecutor:
    def __init__(self, output_by_tool_id: dict[str, str]) -> None:
        self._output_by_tool_id = output_by_tool_id

    def get_definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="read_file",
                description="Read a file.",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            )
        ]

    def execute(self, tool_call) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=True,
            output=self._output_by_tool_id[tool_call.id],
        )


class FakeHistoryCompactor:
    def __init__(self, plan: CompactionPlan) -> None:
        self._plan = plan
        self.calls: list[tuple[list[LLMMessage], HistoryBudget]] = []

    def compact(
        self, messages: list[LLMMessage], budget: HistoryBudget
    ) -> CompactionPlan:
        self.calls.append((list(messages), budget))
        return self._plan


def _tool_use_response(tool_id: str, tokens: int = 10) -> LLMResponse:
    return LLMResponse(
        content=[
            LLMTextBlock(type="text", text="looking"),
            LLMToolUseBlock(
                type="tool_use",
                id=tool_id,
                name="read_file",
                input={"path": "example.txt"},
            ),
        ],
        stop_reason="tool_use",
        usage=LLMUsage(input_tokens=tokens, output_tokens=5),
    )


def _final_response(text: str = "done", tokens: int = 10) -> LLMResponse:
    return LLMResponse(
        content=[LLMTextBlock(type="text", text=text)],
        stop_reason="end_turn",
        usage=LLMUsage(input_tokens=tokens, output_tokens=5),
    )


def _request() -> LLMRequest:
    return LLMRequest(
        system_prompt="You are an agent.",
        messages=[
            LLMMessage(role="user", content="Inspect example.txt.")
        ],
        model="fake-model",
        max_tokens=100,
    )


def test_default_history_budget_does_not_shrink_small_requests() -> None:
    provider = FakeProvider(
        [_tool_use_response("call-1"), _final_response()]
    )
    tool_executor = FakeToolExecutor({"call-1": "1: hello"})
    executor = LLMRunExecutor(
        provider=provider, tool_executor=tool_executor
    )

    executor.execute(_request())

    # Round 2 should see the full history: task, tool_use, tool_result.
    assert len(provider.requests[1].messages) == 3


def test_full_history_is_preserved_and_recent_rounds_take_priority() -> (
    None
):
    # Three rounds: two tool exchanges, then a final answer. A tight
    # budget should drop the *older* exchange from round 3's request
    # while still correctly carrying round 2's real tool result -
    # proving compaction reflects the full, current history each
    # round rather than working off a stale or destroyed copy.
    big_output = "R" * 800
    provider = FakeProvider(
        [
            _tool_use_response("call-1"),
            _tool_use_response("call-2"),
            _final_response(),
        ]
    )
    tool_executor = FakeToolExecutor(
        {"call-1": big_output, "call-2": big_output}
    )

    # Compute a budget that fits the initial task + exactly one
    # tool-exchange pair, using the same estimator the compactor uses.
    # Built from the *actual* response/tool-result shapes the executor
    # produces (LLMResponse.to_message_content() + ToolResult.to_
    # message_block()), so the probe's token count matches reality -
    # a hand-written stand-in content list would under-count the
    # assistant's accompanying text block and throw the budget off.
    probe_compactor = RuleBasedHistoryCompactor()
    probe_messages = [
        LLMMessage(role="user", content="Inspect example.txt."),
        LLMMessage(
            role="assistant",
            content=_tool_use_response("call-1").to_message_content(),
        ),
        LLMMessage(
            role="user",
            content=[
                ToolResult(
                    tool_call_id="call-1",
                    tool_name="read_file",
                    success=True,
                    output=big_output,
                ).to_message_block()
            ],
        ),
    ]
    groups = MessageGroupBuilder().build(probe_messages)
    initial_tokens = probe_compactor._estimate_group(
        probe_messages, groups[0]
    )
    exchange_tokens = probe_compactor._estimate_group(
        probe_messages, groups[1]
    )
    budget = HistoryBudget(max_tokens=initial_tokens + exchange_tokens)

    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        history_budget=budget,
    )

    executor.execute(_request())

    # Round 3's request: initial task + the *second* (recent) tool
    # exchange only - the first exchange was dropped as a whole unit.
    round_three_request = provider.requests[2]
    assert len(round_three_request.messages) == 3
    assert round_three_request.messages[0].content == (
        "Inspect example.txt."
    )
    tool_use_blocks = [
        block
        for block in round_three_request.messages[1].content
        if block["type"] == "tool_use"
    ]
    assert tool_use_blocks[0]["id"] == "call-2"
    tool_result_block = round_three_request.messages[2].content[0]
    assert tool_result_block["tool_use_id"] == "call-2"
    assert tool_result_block["content"] == big_output


def test_custom_history_compactor_can_be_injected() -> None:
    provider = FakeProvider(
        [_tool_use_response("call-1"), _final_response()]
    )
    tool_executor = FakeToolExecutor({"call-1": "1: hello"})
    fake_compactor = FakeHistoryCompactor(
        CompactionPlan(original_count=1, retained_indices=[0])
    )
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        history_compactor=fake_compactor,
    )

    executor.execute(_request())

    assert len(fake_compactor.calls) == 2
    # Every round's request reflects the injected compactor's plan.
    assert all(
        len(request.messages) == 1 for request in provider.requests
    )


def test_history_budget_is_passed_through_to_the_compactor() -> None:
    provider = FakeProvider([_final_response()])
    tool_executor = FakeToolExecutor({})
    fake_compactor = FakeHistoryCompactor(
        CompactionPlan(original_count=1, retained_indices=[0])
    )
    budget = HistoryBudget(max_tokens=777)
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        history_compactor=fake_compactor,
        history_budget=budget,
    )

    executor.execute(_request())

    assert fake_compactor.calls[0][1] is budget


def test_durable_history_keeps_growing_even_when_a_round_is_compacted() -> (
    None
):
    # The FakeHistoryCompactor always retains only index 0, yet the
    # executor must still track the full, ever-growing history
    # internally (visible via the compactor being invoked with a
    # longer `messages` list on each subsequent round).
    provider = FakeProvider(
        [_tool_use_response("call-1"), _final_response()]
    )
    tool_executor = FakeToolExecutor({"call-1": "1: hello"})
    fake_compactor = FakeHistoryCompactor(
        CompactionPlan(original_count=1, retained_indices=[0])
    )
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        history_compactor=fake_compactor,
    )

    executor.execute(_request())

    round_one_messages, _ = fake_compactor.calls[0]
    round_two_messages, _ = fake_compactor.calls[1]
    assert len(round_one_messages) == 1
    # Round 2 sees the tool_use + tool_result appended after round 1,
    # even though round 1's *sent* request was compacted down to 1.
    assert len(round_two_messages) == 3
