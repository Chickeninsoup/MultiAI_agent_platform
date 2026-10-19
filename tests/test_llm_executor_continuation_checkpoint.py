from __future__ import annotations

from pathlib import Path

import pytest

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
    def preview(self, tool_call: ToolCall) -> str:
        return "generic preview"


class _FailingCheckpointRepository:
    """A checkpoint repository whose save() always fails - used to
    prove checkpoint-persistence failure fails closed."""

    def save(self, checkpoint) -> None:
        raise RuntimeError("checkpoint save exploded")


class _MultiToolUseProvider:
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
                    input={"path": "b.py", "content": "secret-token"},
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


class _SingleToolUseProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1

        return LLMResponse(
            content=[
                LLMToolUseBlock(
                    type="tool_use",
                    id="toolu_1",
                    name="write_file",
                    input={"path": "a.py", "content": "secret-token"},
                )
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


def _tool_executor(handlers: list, enabled: set[str], tmp_path: Path):
    from src.services.tools.tool_executor import ToolExecutor
    from src.services.tools.tool_policy import (
        ToolPolicy,
        ToolPolicyEntry,
    )

    return ToolExecutor(
        repository_root=tmp_path,
        handlers=handlers,
        tool_policy=ToolPolicy(
            default="deny",
            tools={
                name: ToolPolicyEntry(enabled=True) for name in enabled
            },
        ),
    )


def _gate(tmp_path: Path, rule_tool_name: str = "write_file") -> ToolApprovalGate:
    store = ApprovalStore(
        ApprovalRequestRepository(tmp_path),
        ApprovalResolutionRepository(tmp_path),
    )
    policy = RuleBasedToolApprovalPolicy(
        [
            ApprovalRule(
                tool_name=rule_tool_name,
                risk_level=RiskLevel.MEDIUM,
                reason="needs a human",
            )
        ]
    )

    return ToolApprovalGate(policy, _FixedPreviewer(), store)


def _executor(
    *,
    tmp_path: Path,
    tool_executor,
    provider,
    gate: ToolApprovalGate,
    checkpoint_repository=None,
) -> LLMRunExecutor:
    return LLMRunExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=gate,
        run_id="run-007",
        task_id="task-1",
        continuation_checkpoint_repository=(
            checkpoint_repository
            if checkpoint_repository is not None
            else RunContinuationCheckpointRepository(tmp_path)
        ),
    )


# --- single ToolCall --------------------------------------------------


def test_checkpoint_persisted_before_returning_waiting(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], {"write_file"}, tmp_path
    )
    gate = _gate(tmp_path)
    executor = _executor(
        tmp_path=tmp_path,
        tool_executor=tool_executor,
        provider=_SingleToolUseProvider(),
        gate=gate,
    )

    result = executor.execute(_request())

    checkpoint_repository = RunContinuationCheckpointRepository(
        tmp_path
    )
    checkpoint = checkpoint_repository.load("task-1", "run-007")

    assert checkpoint.approval_id == result.waiting_for_approval.approval_id
    assert checkpoint.pending_tool_call_id == "toolu_1"


def test_pending_tool_call_has_no_tool_result(tmp_path: Path) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], {"write_file"}, tmp_path
    )
    gate = _gate(tmp_path)
    executor = _executor(
        tmp_path=tmp_path,
        tool_executor=tool_executor,
        provider=_SingleToolUseProvider(),
        gate=gate,
    )

    executor.execute(_request())

    checkpoint = RunContinuationCheckpointRepository(tmp_path).load(
        "task-1", "run-007"
    )
    assert checkpoint.completed_tool_results == ()
    assert checkpoint.pending_tool_call_index == 0


def test_persisted_identifiers_match_approval_store(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], {"write_file"}, tmp_path
    )
    gate = _gate(tmp_path)
    executor = _executor(
        tmp_path=tmp_path,
        tool_executor=tool_executor,
        provider=_SingleToolUseProvider(),
        gate=gate,
    )

    executor.execute(_request())

    checkpoint = RunContinuationCheckpointRepository(tmp_path).load(
        "task-1", "run-007"
    )
    stored_request = ApprovalRequestRepository(tmp_path).load(
        checkpoint.approval_id
    )

    assert stored_request.run_id == checkpoint.run_id
    assert stored_request.proposed_action.id == checkpoint.pending_tool_call_id


# --- multiple ToolCalls -------------------------------------------------


def test_multiple_tool_call_checkpoint_represents_all_three_states(
    tmp_path: Path,
) -> None:
    read_handler = _FakeHandler("read_file", output="read ok")
    write_handler = _FakeHandler("write_file", output="write ok")
    tool_executor = _tool_executor(
        [read_handler, write_handler],
        {"read_file", "write_file"},
        tmp_path,
    )
    gate = _gate(tmp_path)
    executor = _executor(
        tmp_path=tmp_path,
        tool_executor=tool_executor,
        provider=_MultiToolUseProvider(),
        gate=gate,
    )

    executor.execute(_request())

    checkpoint = RunContinuationCheckpointRepository(tmp_path).load(
        "task-1", "run-007"
    )

    # toolu_a: completed, result preserved
    assert len(checkpoint.completed_tool_results) == 1
    assert checkpoint.completed_tool_results[0].tool_call_id == "toolu_a"
    assert checkpoint.completed_tool_results[0].success is True

    # toolu_b: pending, exact index, no fabricated result
    assert checkpoint.pending_tool_call_index == 1
    assert checkpoint.pending_tool_call_id == "toolu_b"

    # toolu_c: remains, in order, unexecuted
    assert [
        call.id for call in checkpoint.pending_round_tool_calls
    ] == ["toolu_a", "toolu_b", "toolu_c"]

    assert write_handler.calls == []
    assert len(read_handler.calls) == 1
    assert read_handler.calls[0].id == "toolu_a"


# --- usage / history -----------------------------------------------------


def test_conversation_history_survives_round_trip(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], {"write_file"}, tmp_path
    )
    gate = _gate(tmp_path)
    executor = _executor(
        tmp_path=tmp_path,
        tool_executor=tool_executor,
        provider=_SingleToolUseProvider(),
        gate=gate,
    )

    executor.execute(_request())

    checkpoint = RunContinuationCheckpointRepository(tmp_path).load(
        "task-1", "run-007"
    )

    assert checkpoint.messages[0].role == "user"
    assert checkpoint.messages[0].content == "do the task"
    # The pending round's assistant turn (introducing the ToolCalls)
    # is already the trailing message.
    assert checkpoint.messages[-1].role == "assistant"
    assert any(
        block.get("type") == "tool_use"
        for block in checkpoint.messages[-1].content
    )


def test_accumulated_usage_and_limits_survive_round_trip(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], {"write_file"}, tmp_path
    )
    gate = _gate(tmp_path)
    executor = _executor(
        tmp_path=tmp_path,
        tool_executor=tool_executor,
        provider=_SingleToolUseProvider(),
        gate=gate,
    )

    executor.execute(_request())

    checkpoint = RunContinuationCheckpointRepository(tmp_path).load(
        "task-1", "run-007"
    )

    assert checkpoint.total_input_tokens == 10
    assert checkpoint.total_output_tokens == 5
    assert checkpoint.llm_rounds == 1
    assert checkpoint.tool_rounds == 1
    assert checkpoint.max_tool_rounds == 8
    assert checkpoint.max_total_tokens == 100_000


def test_reconstructed_messages_remain_compatible_with_history_compaction(
    tmp_path: Path,
) -> None:
    from src.context.history.message_group_builder import (
        MessageGroupBuilder,
    )

    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], {"write_file"}, tmp_path
    )
    gate = _gate(tmp_path)
    executor = _executor(
        tmp_path=tmp_path,
        tool_executor=tool_executor,
        provider=_SingleToolUseProvider(),
        gate=gate,
    )

    executor.execute(_request())

    checkpoint = RunContinuationCheckpointRepository(tmp_path).load(
        "task-1", "run-007"
    )

    # Does not raise, and produces one group per message - the same
    # grouping History Compression would already build from this
    # exact list mid-run (5E-5D-4C: round-tripping through the
    # checkpoint does not change the shape MessageGroupBuilder sees).
    groups = MessageGroupBuilder().build(list(checkpoint.messages))
    assert len(groups) == len(checkpoint.messages)


# --- failures fail closed -----------------------------------------------


def test_checkpoint_writer_failure_executes_no_tool(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], {"write_file"}, tmp_path
    )
    gate = _gate(tmp_path)
    executor = _executor(
        tmp_path=tmp_path,
        tool_executor=tool_executor,
        provider=_SingleToolUseProvider(),
        gate=gate,
        checkpoint_repository=_FailingCheckpointRepository(),
    )

    with pytest.raises(RuntimeError):
        executor.execute(_request())

    assert handler.calls == []


def test_checkpoint_writer_failure_returns_no_waiting_result(
    tmp_path: Path,
) -> None:
    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], {"write_file"}, tmp_path
    )
    gate = _gate(tmp_path)
    executor = _executor(
        tmp_path=tmp_path,
        tool_executor=tool_executor,
        provider=_SingleToolUseProvider(),
        gate=gate,
        checkpoint_repository=_FailingCheckpointRepository(),
    )

    # execute() raises rather than returning an LLMRunResult at all -
    # so nothing downstream (RunService) can ever see a
    # waiting_for_approval outcome for this attempt.
    with pytest.raises(RuntimeError):
        executor.execute(_request())


def test_pending_approval_request_remains_inspectable_after_checkpoint_failure(
    tmp_path: Path,
) -> None:
    """Documents the known cross-file atomicity gap (5E-5D-4C): the
    ApprovalRequest write and the checkpoint write are two separate
    JSON files, not one transaction. If the checkpoint write fails
    after the ApprovalRequest already succeeded, the ApprovalRequest
    is not rolled back - it is left as an orphan, inspectable via
    ApprovalStore, with no checkpoint to resume from."""

    handler = _FakeHandler("write_file")
    tool_executor = _tool_executor(
        [handler], {"write_file"}, tmp_path
    )
    gate = _gate(tmp_path)
    executor = _executor(
        tmp_path=tmp_path,
        tool_executor=tool_executor,
        provider=_SingleToolUseProvider(),
        gate=gate,
        checkpoint_repository=_FailingCheckpointRepository(),
    )

    with pytest.raises(RuntimeError):
        executor.execute(_request())

    pending = ApprovalStore(
        ApprovalRequestRepository(tmp_path),
        ApprovalResolutionRepository(tmp_path),
    ).list_pending()

    assert len(pending) == 1
    with pytest.raises(FileNotFoundError):
        RunContinuationCheckpointRepository(tmp_path).load(
            "task-1", "run-007"
        )


# --- restart simulation --------------------------------------------------


def test_restart_simulation_reconstructs_the_exact_pending_position(
    tmp_path: Path,
) -> None:
    read_handler = _FakeHandler("read_file", output="read ok")
    write_handler = _FakeHandler("write_file", output="write ok")
    tool_executor = _tool_executor(
        [read_handler, write_handler],
        {"read_file", "write_file"},
        tmp_path,
    )
    gate = _gate(tmp_path)
    executor = _executor(
        tmp_path=tmp_path,
        tool_executor=tool_executor,
        provider=_MultiToolUseProvider(),
        gate=gate,
    )

    live_result = executor.execute(_request())
    live_approval_id = live_result.waiting_for_approval.approval_id

    # Discard every in-memory object built above - only tmp_path (the
    # "disk") survives.
    del executor, gate, tool_executor, read_handler, write_handler

    # Recreate everything fresh, as a new process would.
    reloaded_store = ApprovalStore(
        ApprovalRequestRepository(tmp_path),
        ApprovalResolutionRepository(tmp_path),
    )
    reloaded_checkpoint_repository = RunContinuationCheckpointRepository(
        tmp_path
    )

    reloaded_request = reloaded_store.get(live_approval_id)
    reloaded_checkpoint = reloaded_checkpoint_repository.load(
        "task-1", "run-007"
    )

    assert reloaded_request.approval_id == live_approval_id
    assert reloaded_checkpoint.approval_id == live_approval_id
    assert reloaded_checkpoint.pending_tool_call_id == "toolu_b"
    assert reloaded_checkpoint.pending_tool_call_index == 1
    assert [
        result.tool_call_id
        for result in reloaded_checkpoint.completed_tool_results
    ] == ["toolu_a"]
    assert [
        call.id for call in reloaded_checkpoint.pending_round_tool_calls
    ] == ["toolu_a", "toolu_b", "toolu_c"]
    # Not executed or resumed - only reconstructed and inspected.
