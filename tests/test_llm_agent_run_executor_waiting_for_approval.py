from __future__ import annotations

import json
from pathlib import Path

from src.approval_request import RiskLevel
from src.approval_request_repository import ApprovalRequestRepository
from src.approval_resolution_repository import (
    ApprovalResolutionRepository,
)
from src.approval_rule import ApprovalRule
from src.approval_store import ApprovalStore
from src.config.settings import Settings
from src.domain.tools.tool_call import ToolCall
from src.llm.types import (
    LLMRequest,
    LLMResponse,
    LLMTextBlock,
    LLMToolUseBlock,
    LLMUsage,
)
from src.llm_agent_run_executor import LLMAgentRunExecutor
from src.models import (
    AgentDefinition,
    AgentLimits,
    RunDefinition,
    RunExecutionContext,
    TaskDefinition,
)
from src.repositories import RunRepository
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)
from src.rule_based_tool_approval_policy import (
    RuleBasedToolApprovalPolicy,
)
from src.tool_approval_gate import ToolApprovalGate


class _FixedPreviewer:
    def preview(self, tool_call: ToolCall) -> str:
        return "write a.py"


class FakeProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self.call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
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


class TwoRoundFakeProvider:
    """Proposes write_file once, then ends the turn - used for the
    no-gate regression test, where nothing ever pauses execution."""

    provider_name = "fake"

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self.call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        self.call_count += 1

        if self.call_count == 1:
            return LLMResponse(
                content=[
                    LLMToolUseBlock(
                        type="tool_use",
                        id="toolu_1",
                        name="write_file",
                        input={"path": "a.py", "content": "ok"},
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


class FakeAgentRepository:
    def __init__(self, agent_directory: Path) -> None:
        self._agent_directory = agent_directory
        self.requested_agent_ids: list[str] = []

    def get_agent_dir(self, agent_id: str) -> Path:
        self.requested_agent_ids.append(agent_id)
        return self._agent_directory


def _build_agent() -> AgentDefinition:
    return AgentDefinition(
        id="agent-test",
        name="Test Agent",
        description="An agent used for testing.",
        owner="owner-1",
        status="active",
        role="engineer",
        template_id="engineer",
        default_model="claude-model-placeholder",
        credential_id="cred-1",
        system_prompt_path="system-prompt.md",
        tool_policy_path="tool-policy.json",
        default_workspace_id="workspace-1",
        capabilities=["write_file"],
        limits=AgentLimits(
            memory_mb=512,
            cpus=1,
            timeout_seconds=60,
            max_input_tokens=50_000,
            max_output_tokens=4096,
        ),
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


def _build_task() -> TaskDefinition:
    return TaskDefinition(
        id="task-1",
        title="Write a file",
        description="Write a.py.",
        workspace_id="workspace-1",
        status="in_progress",
        priority="normal",
        created_by="user-1",
        assigned_agents=["agent-test"],
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        started_at="2026-01-01T00:00:00Z",
        completed_at=None,
        abandoned_at=None,
        current_run_id="run-007",
        run_count=1,
        completion_criteria=["a.py exists."],
        tags=[],
    )


def _build_run() -> RunDefinition:
    return RunDefinition(
        id="run-007",
        task_id="task-1",
        agent_id="agent-test",
        status="in_progress",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        started_at="2026-01-01T00:00:00Z",
        completed_at=None,
    )


def _build_settings() -> Settings:
    return Settings(
        execution_mode="llm",
        llm_provider="anthropic",
        anthropic_api_key="fake-key",
        anthropic_model="claude-default-model",
        llm_timeout_seconds=60.0,
        llm_max_retries=2,
        llm_max_tokens=4096,
        llm_max_tool_rounds=8,
        llm_max_total_tokens=100_000,
        debug_log_full_output=False,
        test_policy_path="test_policy.json",
        approval_policy_path="approval_policy.json",
    )


def _write_test_policy(repository_root: Path) -> None:
    (repository_root / "test_policy.json").write_text(
        json.dumps({"tests": {}}), encoding="utf-8"
    )


def _write_tool_policy(agent_directory: Path) -> None:
    (agent_directory / "tool-policy.json").write_text(
        json.dumps(
            {
                "default": "deny",
                "tools": {
                    "write_file": {"enabled": True},
                    "read_file": {"enabled": False},
                    "list_files": {"enabled": False},
                    "git_status": {"enabled": False},
                    "git_diff": {"enabled": False},
                },
            }
        ),
        encoding="utf-8",
    )


def _build_context() -> RunExecutionContext:
    return RunExecutionContext(
        task=_build_task(),
        run=_build_run(),
        agent=_build_agent(),
        run_input="Please write a.py.",
        agent_system_prompt="You specialize in writing files.",
        task_background="No prior runs.",
        tool_policy={"default": "deny"},
        project_snapshot="# Snapshot\n\nNo additional context.",
    )


def _gate(tmp_path: Path) -> ToolApprovalGate:
    store = ApprovalStore(
        ApprovalRequestRepository(tmp_path),
        ApprovalResolutionRepository(tmp_path),
    )
    policy = RuleBasedToolApprovalPolicy(
        [
            ApprovalRule(
                tool_name="write_file",
                risk_level=RiskLevel.MEDIUM,
                reason="writes files outside the sandbox",
            )
        ]
    )

    return ToolApprovalGate(policy, _FixedPreviewer(), store)


def _build_executor(
    *, tmp_path: Path, repository_root: Path, agent_directory: Path
) -> tuple[LLMAgentRunExecutor, FakeProvider]:
    provider = FakeProvider()
    agent_repository = FakeAgentRepository(agent_directory)
    run_repository = RunRepository(tmp_path / "tasks")

    executor = LLMAgentRunExecutor(
        provider=provider,
        settings=_build_settings(),
        agent_repository=agent_repository,
        run_repository=run_repository,
        project_root=repository_root,
        approval_gate=_gate(tmp_path),
        continuation_checkpoint_repository=(
            RunContinuationCheckpointRepository(tmp_path / "tasks")
        ),
    )

    return executor, provider


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _write_test_policy(repository_root)

    agent_directory = tmp_path / "agents" / "agent-test"
    agent_directory.mkdir(parents=True)
    _write_tool_policy(agent_directory)

    return repository_root, agent_directory


def test_execute_returns_a_waiting_result(tmp_path: Path) -> None:
    repository_root, agent_directory = _setup(tmp_path)
    executor, _provider = _build_executor(
        tmp_path=tmp_path,
        repository_root=repository_root,
        agent_directory=agent_directory,
    )

    result = executor.execute(_build_context())

    assert result.metadata["waiting_for_approval"] is True
    assert result.metadata["approval_id"]
    assert result.metadata["tool_call_id"] == "toolu_1"


def test_output_and_summary_mention_the_pause_not_completion(
    tmp_path: Path,
) -> None:
    repository_root, agent_directory = _setup(tmp_path)
    executor, _provider = _build_executor(
        tmp_path=tmp_path,
        repository_root=repository_root,
        agent_directory=agent_directory,
    )

    result = executor.execute(_build_context())

    assert "waiting_for_approval" in result.summary_markdown
    assert "completed" not in result.summary_markdown.lower()
    assert result.metadata["approval_id"] in result.summary_markdown


def test_output_and_summary_do_not_leak_the_raw_input(
    tmp_path: Path,
) -> None:
    repository_root, agent_directory = _setup(tmp_path)
    executor, _provider = _build_executor(
        tmp_path=tmp_path,
        repository_root=repository_root,
        agent_directory=agent_directory,
    )

    result = executor.execute(_build_context())

    assert "secret-token" not in result.output_markdown
    assert "secret-token" not in result.summary_markdown


def test_without_a_gate_behavior_is_unchanged(tmp_path: Path) -> None:
    repository_root, agent_directory = _setup(tmp_path)
    provider = TwoRoundFakeProvider()
    agent_repository = FakeAgentRepository(agent_directory)
    run_repository = RunRepository(tmp_path / "tasks")

    executor = LLMAgentRunExecutor(
        provider=provider,
        settings=_build_settings(),
        agent_repository=agent_repository,
        run_repository=run_repository,
        project_root=repository_root,
        # approval_gate omitted entirely - defaults to None
    )

    result = executor.execute(_build_context())

    assert "waiting_for_approval" not in result.metadata
