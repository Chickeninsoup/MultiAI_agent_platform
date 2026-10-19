from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.approval_application_repository import (
    ApprovalApplicationRepository,
)
from src.approval_application_service import ApprovalApplicationService
from src.approval_continuation_preparation_service import (
    ApprovalContinuationPreparationService,
)
from src.approval_decision import ApprovalDecision
from src.approval_request import RiskLevel
from src.approval_request_repository import ApprovalRequestRepository
from src.approval_resolution import ApprovalResolution
from src.approval_resolution_repository import (
    ApprovalResolutionRepository,
)
from src.approval_rule import ApprovalRule
from src.approval_store import ApprovalStore
from src.context_builder import RunContextBuilder
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
from src.models import RunDefinition, RunExecutionResult, TaskDefinition
from src.repositories import AgentRepository, RunRepository, TaskRepository
from src.rule_based_tool_approval_policy import (
    RuleBasedToolApprovalPolicy,
)
from src.run_continuation_attempt_errors import (
    RunContinuationBlockedError,
    RunContinuationMismatchError,
    RunContinuationNotConfiguredError,
    RunContinuationPersistenceError,
)
from src.run_continuation_attempt_repository import (
    RunContinuationAttemptRepository,
)
from src.run_continuation_attempt_status import (
    RunContinuationAttemptStatus,
)
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)
from src.run_service import RunService
from src.services.tools.tool_executor import ToolExecutor
from src.services.tools.tool_policy import ToolPolicy, ToolPolicyEntry
from src.tool_approval_gate import ToolApprovalGate

NOW = "2026-01-01T00:00:00Z"
SECRET = "super-secret-b"


# --- test doubles -----------------------------------------------------


class _CountingHandler:
    def __init__(self, name: str, *, mutates: bool = False) -> None:
        self.definition = ToolDefinition(
            name=name, description="test tool", input_schema={}
        )
        self.calls: list[dict[str, Any]] = []
        self._mutates = mutates

    def execute(
        self,
        *,
        tool_call_id: str,
        tool_input: dict[str, Any],
        repository_root: Path,
        max_output_chars: int,
    ) -> ToolResult:
        self.calls.append(
            {"tool_call_id": tool_call_id, "tool_input": tool_input}
        )

        metadata: dict[str, Any] = {}
        if self._mutates:
            metadata = {
                "operation": "write",
                "path": tool_input.get("path"),
                "before_sha256": "before",
                "after_sha256": f"after-{tool_call_id}",
                "bytes_written": 10,
            }

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.definition.name,
            success=True,
            output=f"{self.definition.name} ok ({tool_call_id})",
            metadata=metadata,
        )


class _FixedPreviewer:
    def preview(self, tool_call: ToolCall) -> str:
        return "generic preview"


class _ScriptedProvider:
    provider_name = "fake"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.received_requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.received_requests.append(request)

        if not self._responses:
            raise AssertionError(
                "Scripted provider ran out of responses"
            )

        return self._responses.pop(0)


class _ScriptedExecutor:
    """A minimal RunExecutor/ApprovalContinuationCapableExecutor that
    drives a *real* LLMRunExecutor against a scripted provider and
    counting tool handlers - exercises the actual tool-loop/
    continuation logic under test (LLMRunExecutor.execute()/
    resume_from_checkpoint()) without standing up the heavier
    LLMAgentRunExecutor (prompt building / agent-directory / Settings
    machinery, a different, already-covered concern)."""

    def __init__(
        self,
        *,
        provider: _ScriptedProvider,
        tool_executor: ToolExecutor,
        approval_gate: ToolApprovalGate | None,
        checkpoint_repository: RunContinuationCheckpointRepository,
        run_repository: RunRepository,
        max_tool_rounds: int = 8,
        max_total_tokens: int = 100_000,
    ) -> None:
        self._provider = provider
        self._tool_executor = tool_executor
        self._approval_gate = approval_gate
        self._checkpoint_repository = checkpoint_repository
        self._run_repository = run_repository
        self._max_tool_rounds = max_tool_rounds
        self._max_total_tokens = max_total_tokens

    def _build(
        self, context, *, truncate_existing: bool
    ) -> LLMRunExecutor:
        from src.run_events import JsonlRunEventSink

        events_path = self._run_repository.get_events_file(
            context.task.id, context.run.id
        )
        event_sink = JsonlRunEventSink(
            events_path, truncate_existing=truncate_existing
        )

        return LLMRunExecutor(
            provider=self._provider,
            tool_executor=self._tool_executor,
            max_tool_rounds=self._max_tool_rounds,
            max_total_tokens=self._max_total_tokens,
            event_sink=event_sink,
            approval_gate=self._approval_gate,
            run_id=context.run.id,
            task_id=context.task.id,
            continuation_checkpoint_repository=(
                self._checkpoint_repository
            ),
        )

    @staticmethod
    def _template(context) -> LLMRequest:
        return LLMRequest(
            system_prompt="test system prompt",
            messages=[
                LLMMessage(role="user", content=context.run_input)
            ],
            model="fake-model",
            max_tokens=100,
        )

    def execute(self, context) -> RunExecutionResult:
        run_result = self._build(
            context, truncate_existing=True
        ).execute(self._template(context))
        return _to_execution_result(run_result)

    def resume_after_approval(
        self, context, checkpoint, outcome
    ) -> RunExecutionResult:
        run_result = self._build(
            context, truncate_existing=False
        ).resume_from_checkpoint(
            self._template(context), checkpoint, outcome
        )
        return _to_execution_result(run_result)


def _to_execution_result(run_result) -> RunExecutionResult:
    metadata = {
        "llm_rounds": run_result.llm_rounds,
        "tool_rounds": run_result.tool_rounds,
        "tool_calls": run_result.tool_calls,
        "total_input_tokens": run_result.total_input_tokens,
        "total_output_tokens": run_result.total_output_tokens,
    }

    if run_result.cancelled:
        return RunExecutionResult(
            output_markdown="cancelled",
            summary_markdown="cancelled",
            metadata={**metadata, "cancelled": True},
        )

    if run_result.waiting_for_approval is not None:
        pause = run_result.waiting_for_approval
        return RunExecutionResult(
            output_markdown="waiting",
            summary_markdown="waiting",
            metadata={
                **metadata,
                "waiting_for_approval": True,
                "approval_id": pause.approval_id,
                "tool_call_id": pause.tool_call_id,
            },
        )

    return RunExecutionResult(
        output_markdown=run_result.final_response.text,
        summary_markdown="done",
        metadata=metadata,
    )


class _CompleteFailingAttemptRepository(RunContinuationAttemptRepository):
    def complete(self, task_id, run_id, **kwargs):  # type: ignore[override]
        raise OSError("disk unavailable")


# --- fixture helpers -----------------------------------------------------


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_agent(agents_dir: Path, agent_id: str) -> None:
    agent_dir = agents_dir / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "system-prompt.md").write_text(
        "You are a test agent.", encoding="utf-8"
    )
    (agent_dir / "tool-policy.json").write_text("{}", encoding="utf-8")
    _write_json(
        agent_dir / "agent.json",
        {
            "id": agent_id,
            "name": agent_id,
            "description": "A test agent.",
            "owner": "owner-1",
            "status": "ready",
            "role": "general",
            "template_id": "general",
            "default_model": "fake-model",
            "credential_id": "cred-1",
            "system_prompt_path": "system-prompt.md",
            "tool_policy_path": "tool-policy.json",
            "default_workspace_id": "workspace-1",
            "capabilities": [],
            "limits": {
                "memory_mb": 512,
                "cpus": 1,
                "timeout_seconds": 60,
                "max_input_tokens": 1000,
                "max_output_tokens": 1000,
            },
            "created_at": NOW,
            "updated_at": NOW,
        },
    )


def _round1_response(
    *,
    first_tool: str = "read_file",
    first_id: str = "toolu_a",
    first_input: dict[str, Any] | None = None,
    third_tool: str = "read_file",
    third_id: str = "toolu_c",
    third_input: dict[str, Any] | None = None,
) -> LLMResponse:
    return LLMResponse(
        content=[
            LLMToolUseBlock(
                type="tool_use",
                id=first_id,
                name=first_tool,
                input=first_input or {"path": "a.txt"},
            ),
            LLMToolUseBlock(
                type="tool_use",
                id="toolu_b",
                name="write_file",
                input={"path": "b.txt", "content": SECRET},
            ),
            LLMToolUseBlock(
                type="tool_use",
                id=third_id,
                name=third_tool,
                input=third_input or {"path": "c.txt"},
            ),
        ],
        stop_reason="tool_use",
        usage=LLMUsage(input_tokens=20, output_tokens=10),
    )


def _final_response(text: str = "All done.") -> LLMResponse:
    return LLMResponse(
        content=[LLMTextBlock(type="text", text=text)],
        stop_reason="end_turn",
        usage=LLMUsage(input_tokens=5, output_tokens=3),
    )


def _build_scenario(
    tmp_path: Path,
    *,
    agent_id: str = "agent-test",
    task_id: str = "task-1",
    run_id: str = "run-001",
    first_tool: str = "read_file",
    first_id: str = "toolu_a",
    first_input: dict[str, Any] | None = None,
    third_tool: str = "read_file",
    third_id: str = "toolu_c",
    third_input: dict[str, Any] | None = None,
    read_mutates: bool = False,
    attempt_repository_cls: type[
        RunContinuationAttemptRepository
    ] = RunContinuationAttemptRepository,
    with_approval_gate: bool = True,
) -> dict[str, Any]:
    tasks_dir = tmp_path / "tasks"
    agents_dir = tmp_path / "agents"
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    _write_agent(agents_dir, agent_id)

    _write_json(
        tasks_dir / task_id / "task.json",
        {
            "id": task_id,
            "title": "Test task",
            "description": "A task used for testing.",
            "workspace_id": "workspace-1",
            "status": "in_progress",
            "priority": "normal",
            "created_by": "user-1",
            "assigned_agents": [agent_id],
            "created_at": NOW,
            "updated_at": NOW,
            "started_at": NOW,
            "completed_at": None,
            "abandoned_at": None,
            "current_run_id": run_id,
            "run_count": 1,
            "completion_criteria": [],
            "tags": [],
        },
    )

    task_repository = TaskRepository(tasks_dir)
    run_repository = RunRepository(tasks_dir)
    agent_repository = AgentRepository(agents_dir)

    run_repository.save(
        RunDefinition(
            id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            status="in_progress",
            created_at=NOW,
            updated_at=NOW,
            started_at=NOW,
            completed_at=None,
        )
    )
    run_repository.write_input(task_id, run_id, "do the task")

    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    checkpoint_repository = RunContinuationCheckpointRepository(
        tasks_dir
    )
    preparation_service = ApprovalContinuationPreparationService(
        run_repository, checkpoint_repository, approval_store
    )
    application_repository = ApprovalApplicationRepository(tasks_dir)

    read_handler = _CountingHandler("read_file", mutates=read_mutates)
    write_handler = _CountingHandler("write_file", mutates=True)
    tool_policy = ToolPolicy(
        default="deny",
        tools={
            "read_file": ToolPolicyEntry(enabled=True),
            "write_file": ToolPolicyEntry(enabled=True),
        },
    )
    tool_executor = ToolExecutor(
        repository_root=repo_root,
        handlers=[read_handler, write_handler],
        tool_policy=tool_policy,
    )

    application_service = ApprovalApplicationService(
        preparation_service, application_repository, tool_executor
    )

    approval_gate = None
    if with_approval_gate:
        policy = RuleBasedToolApprovalPolicy(
            [
                ApprovalRule(
                    tool_name="write_file",
                    risk_level=RiskLevel.MEDIUM,
                    reason="writes a file",
                )
            ]
        )
        approval_gate = ToolApprovalGate(
            policy, _FixedPreviewer(), approval_store
        )

    provider = _ScriptedProvider(
        [
            _round1_response(
                first_tool=first_tool,
                first_id=first_id,
                first_input=first_input,
                third_tool=third_tool,
                third_id=third_id,
                third_input=third_input,
            ),
            _final_response(),
        ]
    )

    executor = _ScriptedExecutor(
        provider=provider,
        tool_executor=tool_executor,
        approval_gate=approval_gate,
        checkpoint_repository=checkpoint_repository,
        run_repository=run_repository,
    )

    context_builder = RunContextBuilder(
        project_root=repo_root,
        task_repository=task_repository,
        run_repository=run_repository,
        agent_repository=agent_repository,
    )

    attempt_repository = attempt_repository_cls(tasks_dir)

    run_service = RunService(
        task_repository,
        run_repository,
        agent_repository,
        context_builder,
        executor,
        repo_root,
        approval_continuation_preparation_service=preparation_service,
        approval_application_service=application_service,
        run_continuation_attempt_repository=attempt_repository,
    )

    return {
        "tasks_dir": tasks_dir,
        "repo_root": repo_root,
        "task_id": task_id,
        "run_id": run_id,
        "agent_id": agent_id,
        "run_service": run_service,
        "provider": provider,
        "read_handler": read_handler,
        "write_handler": write_handler,
        "approval_store": approval_store,
        "checkpoint_repository": checkpoint_repository,
        "run_repository": run_repository,
        "task_repository": task_repository,
        "attempt_repository": attempt_repository,
        "application_repository": application_repository,
    }


def _resolve(
    scenario: dict[str, Any],
    approval_id: str,
    decision: ApprovalDecision,
    *,
    modified_input: dict[str, Any] | None = None,
) -> None:
    scenario["approval_store"].resolve(
        approval_id,
        ApprovalResolution(
            approval_id=approval_id,
            decision=decision,
            modified_input=modified_input,
        ),
    )


def _pause_on_b(scenario: dict[str, Any]) -> str:
    result = scenario["run_service"].execute(scenario["task_id"])
    assert result.status == "waiting_for_approval"
    assert result.approval_id is not None
    return result.approval_id


# --- APPROVE / MODIFY / REJECT / CANCEL ------------------------------


def test_approve_executes_b_once_and_c_once_with_paired_round(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    approval_id = _pause_on_b(scenario)
    _resolve(scenario, approval_id, ApprovalDecision.APPROVE)

    result = scenario["run_service"].resume_after_approval(
        scenario["run_id"], approval_id
    )

    assert result.status == "completed"
    assert [c["tool_call_id"] for c in scenario["read_handler"].calls] == [
        "toolu_a",
        "toolu_c",
    ]
    assert [
        c["tool_call_id"] for c in scenario["write_handler"].calls
    ] == ["toolu_b"]
    assert scenario["write_handler"].calls[0]["tool_input"] == {
        "path": "b.txt",
        "content": SECRET,
    }

    second_request = scenario["provider"].received_requests[1]
    assistant_message = second_request.messages[-2]
    tool_result_message = second_request.messages[-1]
    assert assistant_message.role == "assistant"
    tool_use_ids = [
        block["id"]
        for block in assistant_message.content
        if block.get("type") == "tool_use"
    ]
    assert tool_use_ids == ["toolu_a", "toolu_b", "toolu_c"]
    assert tool_result_message.role == "user"
    result_ids = [
        block["tool_use_id"] for block in tool_result_message.content
    ]
    assert result_ids == ["toolu_a", "toolu_b", "toolu_c"]
    assert all(
        not block["is_error"] for block in tool_result_message.content
    )


def test_modify_executes_replacement_and_preserves_original_history(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    approval_id = _pause_on_b(scenario)
    modified_input = {"path": "safe.txt", "content": "replaced"}
    _resolve(
        scenario,
        approval_id,
        ApprovalDecision.MODIFY,
        modified_input=modified_input,
    )

    result = scenario["run_service"].resume_after_approval(
        scenario["run_id"], approval_id
    )

    assert result.status == "completed"
    assert scenario["write_handler"].calls[0]["tool_input"] == (
        modified_input
    )

    stored_checkpoint = scenario["checkpoint_repository"].load(
        scenario["task_id"], scenario["run_id"]
    )
    original_b = stored_checkpoint.pending_round_tool_calls[1]
    assert original_b.input == {"path": "b.txt", "content": SECRET}

    second_request = scenario["provider"].received_requests[1]
    assistant_message = second_request.messages[-2]
    original_tool_use = next(
        block
        for block in assistant_message.content
        if block.get("id") == "toolu_b"
    )
    assert original_tool_use["input"] == {
        "path": "b.txt",
        "content": SECRET,
    }


def test_reject_skips_handler_and_continues_with_c(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    approval_id = _pause_on_b(scenario)
    _resolve(scenario, approval_id, ApprovalDecision.REJECT)

    result = scenario["run_service"].resume_after_approval(
        scenario["run_id"], approval_id
    )

    assert result.status == "completed"
    assert scenario["write_handler"].calls == []
    assert [c["tool_call_id"] for c in scenario["read_handler"].calls] == [
        "toolu_a",
        "toolu_c",
    ]

    second_request = scenario["provider"].received_requests[1]
    tool_result_message = second_request.messages[-1]
    rejected_block = next(
        block
        for block in tool_result_message.content
        if block["tool_use_id"] == "toolu_b"
    )
    assert rejected_block["is_error"] is True


def test_cancel_is_terminal_with_no_further_execution(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    approval_id = _pause_on_b(scenario)
    _resolve(scenario, approval_id, ApprovalDecision.CANCEL)

    result = scenario["run_service"].resume_after_approval(
        scenario["run_id"], approval_id
    )

    assert result.status == "cancelled"
    assert result.run_id == scenario["run_id"]
    assert scenario["write_handler"].calls == []
    assert [
        c["tool_call_id"] for c in scenario["read_handler"].calls
    ] == ["toolu_a"]
    assert len(scenario["provider"].received_requests) == 1


# --- a second approval pause -------------------------------------------


def test_c_requiring_approval_pauses_again_with_correct_state(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(
        tmp_path,
        third_tool="write_file",
        third_id="toolu_c2",
        third_input={"path": "c2.txt", "content": "secret-c2"},
    )
    approval_id_b = _pause_on_b(scenario)
    _resolve(scenario, approval_id_b, ApprovalDecision.APPROVE)

    result = scenario["run_service"].resume_after_approval(
        scenario["run_id"], approval_id_b
    )

    assert result.status == "waiting_for_approval"
    new_approval_id = result.approval_id
    assert new_approval_id is not None
    assert new_approval_id != approval_id_b

    checkpoint = scenario["checkpoint_repository"].load(
        scenario["task_id"], scenario["run_id"]
    )
    assert checkpoint.approval_id == new_approval_id
    assert [
        call.id for call in checkpoint.pending_round_tool_calls
    ] == ["toolu_a", "toolu_b", "toolu_c2"]
    assert [
        r.tool_call_id for r in checkpoint.completed_tool_results
    ] == ["toolu_a", "toolu_b"]
    assert checkpoint.pending_tool_call_index == 2
    assert checkpoint.pending_tool_call_id == "toolu_c2"
    assert checkpoint.llm_rounds == 1
    assert checkpoint.tool_rounds == 1
    assert checkpoint.cumulative_tool_calls == 3
    assert len(scenario["provider"].received_requests) == 1

    # A second, independent continuation resolves the new approval.
    _resolve(scenario, new_approval_id, ApprovalDecision.APPROVE)
    second_result = scenario["run_service"].resume_after_approval(
        scenario["run_id"], new_approval_id
    )

    assert second_result.status == "completed"
    assert [
        c["tool_call_id"] for c in scenario["write_handler"].calls
    ] == ["toolu_b", "toolu_c2"]
    assert len(scenario["provider"].received_requests) == 2


# --- counters/budgets vs uninterrupted execution -------------------------


def test_counters_match_an_equivalent_uninterrupted_execution(
    tmp_path: Path,
) -> None:
    paused = _build_scenario(tmp_path, run_id="run-paused")
    approval_id = _pause_on_b(paused)
    _resolve(paused, approval_id, ApprovalDecision.APPROVE)
    paused_result = paused["run_service"].resume_after_approval(
        paused["run_id"], approval_id
    )

    uninterrupted = _build_scenario(
        tmp_path, run_id="run-direct", with_approval_gate=False
    )
    direct_result = uninterrupted["run_service"].execute(
        uninterrupted["task_id"]
    )

    assert direct_result.status == "completed"
    assert paused_result.llm_rounds == direct_result.llm_rounds
    assert paused_result.tool_rounds == direct_result.tool_rounds
    assert paused_result.tool_calls == direct_result.tool_calls
    assert (
        paused_result.total_input_tokens
        == direct_result.total_input_tokens
    )
    assert (
        paused_result.total_output_tokens
        == direct_result.total_output_tokens
    )


# --- retry / idempotency --------------------------------------------------


def test_completed_retry_adds_no_handler_or_provider_calls(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    approval_id = _pause_on_b(scenario)
    _resolve(scenario, approval_id, ApprovalDecision.APPROVE)
    scenario["run_service"].resume_after_approval(
        scenario["run_id"], approval_id
    )

    read_calls_before = len(scenario["read_handler"].calls)
    write_calls_before = len(scenario["write_handler"].calls)
    requests_before = len(scenario["provider"].received_requests)

    retried = scenario["run_service"].resume_after_approval(
        scenario["run_id"], approval_id
    )

    assert retried.status == "completed"
    assert len(scenario["read_handler"].calls) == read_calls_before
    assert len(scenario["write_handler"].calls) == write_calls_before
    assert (
        len(scenario["provider"].received_requests) == requests_before
    )


def test_retry_for_approval_b_cannot_silently_resume_approval_c(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(
        tmp_path,
        third_tool="write_file",
        third_id="toolu_c2",
        third_input={"path": "c2.txt", "content": "secret-c2"},
    )
    approval_id_b = _pause_on_b(scenario)
    _resolve(scenario, approval_id_b, ApprovalDecision.APPROVE)

    # B's own chapter completes with transition RUN_WAITING_FOR_APPROVAL
    # - the Run is now genuinely waiting on a *different*, new
    # approval_id for C.
    pause_result = scenario["run_service"].resume_after_approval(
        scenario["run_id"], approval_id_b
    )
    new_approval_id = pause_result.approval_id
    assert new_approval_id is not None

    # C's approval is now resolved too, so prepare() can fully
    # validate the Run's current state - but asking to resume with an
    # unrelated id must still be rejected, not silently resolved
    # against whatever is actually pending.
    _resolve(scenario, new_approval_id, ApprovalDecision.APPROVE)

    with pytest.raises(RunContinuationMismatchError):
        scenario["run_service"].resume_after_approval(
            scenario["run_id"], "approval-unrelated"
        )

    # Nothing was dispatched for the mismatched request.
    assert [
        c["tool_call_id"] for c in scenario["write_handler"].calls
    ] == ["toolu_b"]

    # B's own approval_id is also no longer resumable - its chapter is
    # already COMPLETED (with transition RUN_WAITING_FOR_APPROVAL), and
    # retrying it returns that same cached transition rather than ever
    # touching C.
    retried = scenario["run_service"].resume_after_approval(
        scenario["run_id"], approval_id_b
    )
    assert retried.status == "waiting_for_approval"
    assert scenario["write_handler"].calls == [
        {
            "tool_call_id": "toolu_b",
            "tool_input": {"path": "b.txt", "content": SECRET},
        }
    ]


# --- failure / interruption handling --------------------------------------


def test_not_configured_raises_without_touching_anything(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    bare_service = RunService(
        scenario["task_repository"],
        scenario["run_repository"],
        AgentRepository(tmp_path / "agents"),
        RunContextBuilder(
            project_root=scenario["repo_root"],
            task_repository=scenario["task_repository"],
            run_repository=scenario["run_repository"],
            agent_repository=AgentRepository(tmp_path / "agents"),
        ),
        scenario["run_service"]._executor,  # noqa: SLF001
        scenario["repo_root"],
    )

    with pytest.raises(RunContinuationNotConfiguredError):
        bare_service.resume_after_approval(
            scenario["run_id"], "approval-x"
        )


def test_incomplete_attempt_blocks_dispatch_after_restart(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    approval_id = _pause_on_b(scenario)
    _resolve(scenario, approval_id, ApprovalDecision.APPROVE)

    from src.run_continuation_attempt_record import (
        ATTEMPT_RECORD_SCHEMA_VERSION,
        RunContinuationAttemptRecord,
    )

    stuck_claim = RunContinuationAttemptRecord(
        schema_version=ATTEMPT_RECORD_SCHEMA_VERSION,
        task_id=scenario["task_id"],
        run_id=scenario["run_id"],
        approval_id=approval_id,
        status=RunContinuationAttemptStatus.CLAIMED,
    )
    scenario["attempt_repository"].create_exclusive(stuck_claim)

    with pytest.raises(RunContinuationBlockedError):
        scenario["run_service"].resume_after_approval(
            scenario["run_id"], approval_id
        )

    assert scenario["write_handler"].calls == []


def test_interruption_after_c_side_effect_blocks_automatic_replay(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(
        tmp_path,
        attempt_repository_cls=_CompleteFailingAttemptRepository,
    )
    approval_id = _pause_on_b(scenario)
    _resolve(scenario, approval_id, ApprovalDecision.APPROVE)

    with pytest.raises(RunContinuationPersistenceError):
        scenario["run_service"].resume_after_approval(
            scenario["run_id"], approval_id
        )

    # The side effects (B and C) already happened.
    assert len(scenario["write_handler"].calls) == 1
    assert [c["tool_call_id"] for c in scenario["read_handler"].calls] == [
        "toolu_a",
        "toolu_c",
    ]

    stuck = RunContinuationAttemptRepository(
        scenario["tasks_dir"]
    ).try_load(scenario["task_id"], scenario["run_id"], approval_id)
    assert stuck.status is RunContinuationAttemptStatus.CLAIMED

    plain_repository = RunContinuationAttemptRepository(
        scenario["tasks_dir"]
    )
    retry_service = RunService(
        scenario["task_repository"],
        scenario["run_repository"],
        AgentRepository(tmp_path / "agents"),
        RunContextBuilder(
            project_root=scenario["repo_root"],
            task_repository=scenario["task_repository"],
            run_repository=scenario["run_repository"],
            agent_repository=AgentRepository(tmp_path / "agents"),
        ),
        scenario["run_service"]._executor,  # noqa: SLF001
        scenario["repo_root"],
        approval_continuation_preparation_service=(
            ApprovalContinuationPreparationService(
                scenario["run_repository"],
                scenario["checkpoint_repository"],
                scenario["approval_store"],
            )
        ),
        approval_application_service=ApprovalApplicationService(
            ApprovalContinuationPreparationService(
                scenario["run_repository"],
                scenario["checkpoint_repository"],
                scenario["approval_store"],
            ),
            scenario["application_repository"],
            scenario["run_service"]._executor._tool_executor,  # noqa: SLF001
        ),
        run_continuation_attempt_repository=plain_repository,
    )

    with pytest.raises(RunContinuationBlockedError):
        retry_service.resume_after_approval(
            scenario["run_id"], approval_id
        )

    assert len(scenario["write_handler"].calls) == 1
    assert len(scenario["read_handler"].calls) == 2


def test_new_waiting_checkpoint_does_not_hide_unfinished_attempt(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(
        tmp_path,
        third_tool="write_file",
        third_id="toolu_c2",
        third_input={"path": "c2.txt", "content": "secret-c2"},
        attempt_repository_cls=_CompleteFailingAttemptRepository,
    )
    approval_id_b = _pause_on_b(scenario)
    _resolve(scenario, approval_id_b, ApprovalDecision.APPROVE)

    with pytest.raises(RunContinuationPersistenceError):
        scenario["run_service"].resume_after_approval(
            scenario["run_id"], approval_id_b
        )

    # The Run now *looks* ready to continue: a fresh checkpoint and a
    # fresh ApprovalRequest exist for C.
    checkpoint = scenario["checkpoint_repository"].load(
        scenario["task_id"], scenario["run_id"]
    )
    new_approval_id = checkpoint.approval_id
    assert new_approval_id != approval_id_b
    run = scenario["run_repository"].load(
        scenario["task_id"], scenario["run_id"]
    )
    assert run.status == "waiting_for_approval"

    _resolve(scenario, new_approval_id, ApprovalDecision.APPROVE)

    plain_repository = RunContinuationAttemptRepository(
        scenario["tasks_dir"]
    )
    fresh_preparation_service = ApprovalContinuationPreparationService(
        scenario["run_repository"],
        scenario["checkpoint_repository"],
        scenario["approval_store"],
    )
    retry_service = RunService(
        scenario["task_repository"],
        scenario["run_repository"],
        AgentRepository(tmp_path / "agents"),
        RunContextBuilder(
            project_root=scenario["repo_root"],
            task_repository=scenario["task_repository"],
            run_repository=scenario["run_repository"],
            agent_repository=AgentRepository(tmp_path / "agents"),
        ),
        scenario["run_service"]._executor,  # noqa: SLF001
        scenario["repo_root"],
        approval_continuation_preparation_service=(
            fresh_preparation_service
        ),
        approval_application_service=ApprovalApplicationService(
            fresh_preparation_service,
            scenario["application_repository"],
            scenario["run_service"]._executor._tool_executor,  # noqa: SLF001
        ),
        run_continuation_attempt_repository=plain_repository,
    )

    with pytest.raises(RunContinuationBlockedError):
        retry_service.resume_after_approval(
            scenario["run_id"], new_approval_id
        )

    assert scenario["write_handler"].calls == [
        {"tool_call_id": "toolu_b", "tool_input": {
            "path": "b.txt", "content": SECRET,
        }}
    ]


# --- generic resume cannot bypass the guard -------------------------------


def test_generic_resume_cannot_bypass_incomplete_attempt(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path)
    approval_id = _pause_on_b(scenario)

    from src.run_continuation_attempt_record import (
        ATTEMPT_RECORD_SCHEMA_VERSION,
        RunContinuationAttemptRecord,
    )

    stuck_claim = RunContinuationAttemptRecord(
        schema_version=ATTEMPT_RECORD_SCHEMA_VERSION,
        task_id=scenario["task_id"],
        run_id=scenario["run_id"],
        approval_id=approval_id,
        status=RunContinuationAttemptStatus.CLAIMED,
    )
    scenario["attempt_repository"].create_exclusive(stuck_claim)

    with pytest.raises(RunContinuationBlockedError):
        scenario["run_service"].resume(scenario["run_id"])

    run = scenario["run_repository"].load(
        scenario["task_id"], scenario["run_id"]
    )
    assert run.status == "waiting_for_approval"


def test_separately_constructed_ordinary_run_service_cannot_bypass_attempt(
    tmp_path: Path,
) -> None:
    """Defense in depth: every status resume_after_approval()'s own
    code paths can currently produce is already outside
    RESUMABLE_STATUSES, so in practice a Run never reaches resume()
    with both a resumable status *and* an incomplete continuation
    attempt. This test constructs that combination artificially to
    prove the explicit find_incomplete() check in resume() is doing
    real, independent work - not simply riding along on a status that
    happens to already exclude it - and that it holds even for a
    RunService built without the approval-execution collaborators
    (approval_continuation_preparation_service/
    approval_application_service), only run_continuation_attempt_
    repository."""

    scenario = _build_scenario(tmp_path)
    approval_id = _pause_on_b(scenario)

    from dataclasses import replace as _replace

    from src.run_continuation_attempt_record import (
        ATTEMPT_RECORD_SCHEMA_VERSION,
        RunContinuationAttemptRecord,
    )

    run = scenario["run_repository"].load(
        scenario["task_id"], scenario["run_id"]
    )
    scenario["run_repository"].save(
        _replace(run, status="interrupted")
    )

    stuck_claim = RunContinuationAttemptRecord(
        schema_version=ATTEMPT_RECORD_SCHEMA_VERSION,
        task_id=scenario["task_id"],
        run_id=scenario["run_id"],
        approval_id=approval_id,
        status=RunContinuationAttemptStatus.CLAIMED,
    )
    scenario["attempt_repository"].create_exclusive(stuck_claim)

    ordinary_service = RunService(
        scenario["task_repository"],
        scenario["run_repository"],
        AgentRepository(tmp_path / "agents"),
        RunContextBuilder(
            project_root=scenario["repo_root"],
            task_repository=scenario["task_repository"],
            run_repository=scenario["run_repository"],
            agent_repository=AgentRepository(tmp_path / "agents"),
        ),
        scenario["run_service"]._executor,  # noqa: SLF001
        scenario["repo_root"],
        run_continuation_attempt_repository=scenario[
            "attempt_repository"
        ],
    )

    with pytest.raises(RunContinuationBlockedError):
        ordinary_service.resume(scenario["run_id"])

    assert scenario["run_repository"].list_run_ids(
        scenario["task_id"]
    ) == [scenario["run_id"]]


# --- review baseline --------------------------------------------------


def test_final_review_includes_pre_pause_changes(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(
        tmp_path,
        agent_id="agent-coder",
        first_tool="read_file",
        first_id="toolu_a",
        first_input={"path": "a.txt"},
        read_mutates=True,
    )
    approval_id = _pause_on_b(scenario)
    _resolve(scenario, approval_id, ApprovalDecision.APPROVE)

    result = scenario["run_service"].resume_after_approval(
        scenario["run_id"], approval_id
    )

    assert result.status == "awaiting_review"

    from src.review.snapshot_repository import SnapshotRepository

    run_directory = scenario["run_repository"].get_run_dir(
        scenario["task_id"], scenario["run_id"]
    )
    snapshot = SnapshotRepository().load(run_directory)
    assert "a.txt" in snapshot.changed_files
    assert "b.txt" in snapshot.changed_files


# --- unrelated behavior stays intact --------------------------------------


def test_execution_without_approval_gate_is_unaffected(
    tmp_path: Path,
) -> None:
    scenario = _build_scenario(tmp_path, with_approval_gate=False)

    result = scenario["run_service"].execute(scenario["task_id"])

    assert result.status == "completed"
    assert len(scenario["read_handler"].calls) == 2
    assert len(scenario["write_handler"].calls) == 1


# --- additional validation failures --------------------------------------


def test_missing_resolution_prevents_dispatch(tmp_path: Path) -> None:
    from src.approval_continuation_preparation_errors import (
        ApprovalResolutionPendingError,
    )

    scenario = _build_scenario(tmp_path)
    approval_id = _pause_on_b(scenario)
    # Deliberately not resolved.

    with pytest.raises(ApprovalResolutionPendingError):
        scenario["run_service"].resume_after_approval(
            scenario["run_id"], approval_id
        )

    assert scenario["write_handler"].calls == []

    stored = scenario["attempt_repository"].try_load(
        scenario["task_id"], scenario["run_id"], approval_id
    )
    assert stored is None


def test_changed_run_state_prevents_dispatch(tmp_path: Path) -> None:
    scenario = _build_scenario(tmp_path)
    approval_id = _pause_on_b(scenario)
    _resolve(scenario, approval_id, ApprovalDecision.APPROVE)

    # Simulate the Run having moved on by some other means before this
    # continuation attempt runs.
    from dataclasses import replace as _replace

    run = scenario["run_repository"].load(
        scenario["task_id"], scenario["run_id"]
    )
    scenario["run_repository"].save(
        _replace(run, status="interrupted")
    )

    from src.approval_decision_errors import (
        ApprovalRunNotWaitingForApprovalError,
    )

    with pytest.raises(ApprovalRunNotWaitingForApprovalError):
        scenario["run_service"].resume_after_approval(
            scenario["run_id"], approval_id
        )

    assert scenario["write_handler"].calls == []
    stored = scenario["attempt_repository"].try_load(
        scenario["task_id"], scenario["run_id"], approval_id
    )
    assert stored is None
