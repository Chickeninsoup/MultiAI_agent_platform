from __future__ import annotations

from pathlib import Path

import pytest

from src.approval_errors import DuplicateApprovalRequestError
from src.approval_request import RiskLevel
from src.approval_request_repository import ApprovalRequestRepository
from src.approval_resolution_repository import (
    ApprovalResolutionRepository,
)
from src.approval_rule import ApprovalRule
from src.approval_store import ApprovalStore
from src.domain.tools.tool_call import ToolCall
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
from src.rule_based_tool_approval_policy import (
    RuleBasedToolApprovalPolicy,
)
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)
from src.run_events import InMemoryRunEventSink
from src.services.tools.tool_executor import ToolExecutor
from src.services.tools.tool_policy import ToolPolicy, ToolPolicyEntry
from src.tool_approval_gate import ToolApprovalGate


class _FakeHandler:
    def __init__(self, name: str, output: str = "ok") -> None:
        self.definition = ToolDefinition(
            name=name,
            description="fake",
            input_schema={"type": "object", "properties": {}},
        )
        self.calls: list[ToolCall] = []
        self._output = output

    def execute(
        self,
        *,
        tool_call_id: str,
        tool_input: dict,
        repository_root: Path,
        max_output_chars: int,
    ) -> ToolResult:
        self.calls.append(
            ToolCall(
                id=tool_call_id,
                name=self.definition.name,
                input=tool_input,
            )
        )

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.definition.name,
            success=True,
            output=self._output,
        )


class _FixedPreviewer:
    def __init__(self, text: str = "generic preview") -> None:
        self.calls: list[ToolCall] = []
        self._text = text

    def preview(self, tool_call: ToolCall) -> str:
        self.calls.append(tool_call)
        return self._text


class _RaisingPreviewer:
    def preview(self, tool_call: ToolCall) -> str:
        raise RuntimeError("previewer exploded")


class _RaisingPolicy:
    def evaluate(self, tool_call: ToolCall):
        raise RuntimeError("policy exploded")


class _PoisonGate:
    """A ToolApprovalGate stand-in that fails the test if check() is
    ever called - used to prove an unauthorized tool never reaches
    ToolApprovalGate at all."""

    def check(self, run_id: str, tool_call: ToolCall):
        raise AssertionError(
            "ToolApprovalGate.check() must not be called for an "
            "unauthorized tool_call"
        )


def _raising_id_factory(run_id: str, tool_call: ToolCall) -> str:
    raise RuntimeError("id factory exploded")


class _SingleToolUseProvider:
    """Round 1: proposes one tool_use. Round 2 (if reached): ends the
    turn with text. Never reached when a round pauses for approval."""

    provider_name = "fake"

    def __init__(
        self, tool_name: str = "write_file", tool_call_id: str = "toolu_1"
    ) -> None:
        self.call_count = 0
        self._tool_name = tool_name
        self._tool_call_id = tool_call_id

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1

        if self.call_count == 1:
            return LLMResponse(
                content=[
                    LLMToolUseBlock(
                        type="tool_use",
                        id=self._tool_call_id,
                        name=self._tool_name,
                        input={"path": "a.py", "content": "secret-token"},
                    )
                ],
                stop_reason="tool_use",
                usage=LLMUsage(input_tokens=10, output_tokens=5),
            )

        return LLMResponse(
            content=[LLMTextBlock(type="text", text="done")],
            stop_reason="end_turn",
            usage=LLMUsage(input_tokens=5, output_tokens=5),
        )


class _MultiToolUseProvider:
    """One round, three tool_use blocks in original order."""

    provider_name = "fake"

    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1

        return LLMResponse(
            content=[
                LLMToolUseBlock(
                    type="tool_use",
                    id="toolu_a",
                    name="read_file",
                    input={"path": "a.py"},
                ),
                LLMToolUseBlock(
                    type="tool_use",
                    id="toolu_b",
                    name="write_file",
                    input={"path": "b.py", "content": "x"},
                ),
                LLMToolUseBlock(
                    type="tool_use",
                    id="toolu_c",
                    name="read_file",
                    input={"path": "c.py"},
                ),
            ],
            stop_reason="tool_use",
            usage=LLMUsage(input_tokens=10, output_tokens=5),
        )


def _request() -> LLMRequest:
    return LLMRequest(
        system_prompt="You are an agent.",
        messages=[LLMMessage(role="user", content="do the task")],
        model="fake-model",
        max_tokens=100,
    )


def _tool_policy(enabled: set[str]) -> ToolPolicy:
    return ToolPolicy(
        default="deny",
        tools={name: ToolPolicyEntry(enabled=True) for name in enabled},
    )


def _tool_executor(
    handlers: list, enabled: set[str], tmp_path: Path
) -> ToolExecutor:
    return ToolExecutor(
        repository_root=tmp_path,
        handlers=handlers,
        tool_policy=_tool_policy(enabled),
    )


def _gate(
    tmp_path: Path,
    *,
    rules: list[ApprovalRule] | None = None,
    policy=None,
    previewer=None,
    approval_id_factory=None,
    event_sink=None,
) -> ToolApprovalGate:
    store = ApprovalStore(
        ApprovalRequestRepository(tmp_path),
        ApprovalResolutionRepository(tmp_path),
        event_sink=event_sink,
    )

    return ToolApprovalGate(
        policy
        if policy is not None
        else RuleBasedToolApprovalPolicy(rules or []),
        previewer if previewer is not None else _FixedPreviewer(),
        store,
        approval_id_factory,
    )


def _rule(tool_name: str, risk: RiskLevel = RiskLevel.MEDIUM) -> ApprovalRule:
    return ApprovalRule(
        tool_name=tool_name, risk_level=risk, reason="needs a human"
    )


# --- authorization / order ------------------------------------------------


def test_unauthorized_tool_creates_no_approval_request(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={}, tmp_path=tmp_path
    )  # write_file NOT enabled
    gate = _gate(tmp_path, rules=[_rule("write_file")])

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    result = executor.execute(_request())

    assert result.waiting_for_approval is None
    assert ApprovalRequestRepository(tmp_path).list_all() == []


def test_unauthorized_tool_never_invokes_the_gate(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={}, tmp_path=tmp_path
    )

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=_PoisonGate(),
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    # Must not raise the AssertionError _PoisonGate.check() would
    # raise if it were ever called.
    executor.execute(_request())


def test_authorized_unconfigured_tool_executes_normally(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={"write_file"}, tmp_path=tmp_path
    )
    gate = _gate(tmp_path, rules=[])  # no rule for write_file

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    result = executor.execute(_request())

    assert result.waiting_for_approval is None
    assert len(handler.calls) == 1
    assert ApprovalRequestRepository(tmp_path).list_all() == []


def test_authorization_happens_before_approval_evaluation(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={}, tmp_path=tmp_path
    )  # disabled
    gate = _gate(tmp_path, rules=[_rule("write_file")])  # also gated

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    result = executor.execute(_request())

    # TOOL_DISABLED wins - never even reaches "waiting".
    assert result.waiting_for_approval is None
    assert ApprovalRequestRepository(tmp_path).list_all() == []
    assert len(handler.calls) == 0


# --- waiting ---------------------------------------------------------------


def test_configured_tool_creates_exactly_one_approval_request(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={"write_file"}, tmp_path=tmp_path
    )
    gate = _gate(tmp_path, rules=[_rule("write_file")])

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    executor.execute(_request())

    assert len(ApprovalRequestRepository(tmp_path).list_all()) == 1


def test_approval_requested_event_is_emitted_once(
    tmp_path: Path,
) -> None:
    sink = InMemoryRunEventSink()
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={"write_file"}, tmp_path=tmp_path
    )
    gate = _gate(
        tmp_path, rules=[_rule("write_file")], event_sink=sink
    )

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
        event_sink=sink,
    )

    executor.execute(_request())

    requested = [
        event
        for event in sink.events
        if event["type"] == "approval_requested"
    ]
    assert len(requested) == 1


def test_tool_handler_is_never_called_when_waiting(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={"write_file"}, tmp_path=tmp_path
    )
    gate = _gate(tmp_path, rules=[_rule("write_file")])

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    executor.execute(_request())

    assert handler.calls == []


def test_no_tool_result_event_is_emitted_for_the_paused_call(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={"write_file"}, tmp_path=tmp_path
    )
    gate = _gate(tmp_path, rules=[_rule("write_file")])

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    result = executor.execute(_request())

    tool_result_events = [
        event for event in result.events if event["type"] == "tool_result"
    ]
    assert tool_result_events == []


def test_provider_is_not_called_again_after_waiting(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={"write_file"}, tmp_path=tmp_path
    )
    gate = _gate(tmp_path, rules=[_rule("write_file")])

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    executor.execute(_request())

    assert provider.call_count == 1


def test_runtime_result_reports_waiting_for_approval(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={"write_file"}, tmp_path=tmp_path
    )
    gate = _gate(tmp_path, rules=[_rule("write_file")])

    provider = _SingleToolUseProvider(
        tool_name="write_file", tool_call_id="toolu_distinctive"
    )
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    result = executor.execute(_request())

    assert result.waiting_for_approval is not None
    assert result.waiting_for_approval.run_id == "run-007"
    assert result.waiting_for_approval.tool_call_id == "toolu_distinctive"
    assert result.waiting_for_approval.approval_id


# --- failures fail closed ---------------------------------------------


def test_policy_failure_executes_no_tool(tmp_path: Path) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={"write_file"}, tmp_path=tmp_path
    )
    gate = _gate(tmp_path, policy=_RaisingPolicy())

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    with pytest.raises(RuntimeError):
        executor.execute(_request())

    assert handler.calls == []
    assert ApprovalRequestRepository(tmp_path).list_all() == []


def test_preview_failure_executes_no_tool(tmp_path: Path) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={"write_file"}, tmp_path=tmp_path
    )
    gate = _gate(
        tmp_path,
        rules=[_rule("write_file")],
        previewer=_RaisingPreviewer(),
    )

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    with pytest.raises(RuntimeError):
        executor.execute(_request())

    assert handler.calls == []
    assert ApprovalRequestRepository(tmp_path).list_all() == []


def test_id_factory_failure_executes_no_tool(tmp_path: Path) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={"write_file"}, tmp_path=tmp_path
    )
    gate = _gate(
        tmp_path,
        rules=[_rule("write_file")],
        approval_id_factory=_raising_id_factory,
    )

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    with pytest.raises(RuntimeError):
        executor.execute(_request())

    assert handler.calls == []
    assert ApprovalRequestRepository(tmp_path).list_all() == []


def test_duplicate_request_executes_no_tool(tmp_path: Path) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={"write_file"}, tmp_path=tmp_path
    )
    # Fixed id factory means the second run's derived id collides.
    gate = _gate(
        tmp_path,
        rules=[_rule("write_file")],
        approval_id_factory=lambda run_id, tool_call: "approval-fixed",
    )

    provider = _SingleToolUseProvider(tool_name="write_file")
    first_executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )
    first_executor.execute(_request())

    second_provider = _SingleToolUseProvider(tool_name="write_file")
    second_executor = LLMRunExecutor(
        provider=second_provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    with pytest.raises(DuplicateApprovalRequestError):
        second_executor.execute(_request())

    assert handler.calls == []


# --- multiple tool calls in one round --------------------------------


def test_multiple_tool_calls_stop_at_the_first_requiring_approval(
    tmp_path: Path,
) -> None:
    read_handler = _FakeHandler("read_file", output="read ok")
    write_handler = _FakeHandler("write_file", output="write ok")
    tool_executor = _tool_executor(
        [read_handler, write_handler],
        enabled={"read_file", "write_file"},
        tmp_path=tmp_path,
    )
    gate = _gate(tmp_path, rules=[_rule("write_file")])

    provider = _MultiToolUseProvider()
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    result = executor.execute(_request())

    # toolu_a (read_file) ran; toolu_b (write_file) paused;
    # toolu_c (read_file, listed after toolu_b) never ran.
    assert len(read_handler.calls) == 1
    assert read_handler.calls[0].id == "toolu_a"
    assert write_handler.calls == []
    assert result.waiting_for_approval is not None
    assert result.waiting_for_approval.tool_call_id == "toolu_b"

    tool_result_events = [
        event for event in result.events if event["type"] == "tool_result"
    ]
    assert len(tool_result_events) == 1
    assert tool_result_events[0]["tool_call_id"] == "toolu_a"


# --- security / regression --------------------------------------------


def test_waiting_event_excludes_raw_input(tmp_path: Path) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={"write_file"}, tmp_path=tmp_path
    )
    gate = _gate(
        tmp_path,
        rules=[_rule("write_file")],
        previewer=_FixedPreviewer(text="write a.py"),
    )

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    result = executor.execute(_request())

    waiting_events = [
        event
        for event in result.events
        if event["type"] == "run_waiting_for_approval"
    ]
    assert len(waiting_events) == 1
    serialized = repr(waiting_events[0])
    assert "secret-token" not in serialized
    assert "input" not in waiting_events[0]


def test_waiting_result_repr_excludes_raw_input(tmp_path: Path) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={"write_file"}, tmp_path=tmp_path
    )
    gate = _gate(tmp_path, rules=[_rule("write_file")])

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path)
        ),
    )

    result = executor.execute(_request())

    assert "secret-token" not in repr(result.waiting_for_approval)


def test_no_approval_gate_is_behaviorally_unchanged(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], enabled={"write_file"}, tmp_path=tmp_path
    )

    provider = _SingleToolUseProvider(tool_name="write_file")
    executor = LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
    )

    result = executor.execute(_request())

    assert result.waiting_for_approval is None
    assert len(handler.calls) == 1
    assert result.final_response.text == "done"
