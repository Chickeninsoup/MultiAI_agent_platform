from __future__ import annotations

import json
from pathlib import Path

from src.config.settings import Settings
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
    RunExecutionResult,
    TaskDefinition,
)
from src.repositories import RunRepository


class FakeProvider:
    """Stands in for the real Anthropic provider; never calls Claude."""

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
                    LLMTextBlock(
                        type="text",
                        text="Let me check the file first.",
                    ),
                    LLMToolUseBlock(
                        type="tool_use",
                        id="toolu_1",
                        name="read_file",
                        input={"path": "example.txt"},
                    ),
                ],
                stop_reason="tool_use",
                usage=LLMUsage(input_tokens=20, output_tokens=8),
            )

        return LLMResponse(
            content=[
                LLMTextBlock(
                    type="text",
                    text="The file contains: hello world.",
                )
            ],
            stop_reason="end_turn",
            usage=LLMUsage(input_tokens=30, output_tokens=12),
        )


class FakeAgentRepository:
    def __init__(self, agent_directory: Path) -> None:
        self._agent_directory = agent_directory
        self.requested_agent_ids: list[str] = []

    def get_agent_dir(self, agent_id: str) -> Path:
        self.requested_agent_ids.append(agent_id)
        return self._agent_directory


def _build_agent(
    default_model: str = "claude-model-placeholder",
) -> AgentDefinition:
    return AgentDefinition(
        id="agent-test",
        name="Test Agent",
        description="An agent used for testing.",
        owner="owner-1",
        status="active",
        role="engineer",
        default_model=default_model,
        credential_id="cred-1",
        system_prompt_path="system-prompt.md",
        tool_policy_path="tool-policy.json",
        default_workspace_id="workspace-1",
        capabilities=["read_file"],
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
        title="Inspect example file",
        description="Read example.txt and report its contents.",
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
        current_run_id="run-1",
        run_count=1,
        completion_criteria=["Report the file contents accurately."],
        tags=[],
    )


def _build_run() -> RunDefinition:
    return RunDefinition(
        id="run-1",
        task_id="task-1",
        agent_id="agent-test",
        status="running",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        started_at="2026-01-01T00:00:00Z",
        completed_at=None,
    )


def _build_settings(
    *,
    debug_log_full_output: bool = False,
) -> Settings:
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
        debug_log_full_output=debug_log_full_output,
    )


def _write_tool_policy(agent_directory: Path) -> None:
    policy_path = agent_directory / "tool-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "default": "deny",
                "tools": {
                    "read_file": {"enabled": True},
                    "list_files": {"enabled": False},
                    "git_status": {"enabled": False},
                    "git_diff": {"enabled": False},
                },
            }
        ),
        encoding="utf-8",
    )


def _build_context(
    *,
    agent: AgentDefinition | None = None,
) -> RunExecutionContext:
    return RunExecutionContext(
        task=_build_task(),
        run=_build_run(),
        agent=agent or _build_agent(),
        run_input="Please inspect example.txt.",
        agent_system_prompt="You specialize in reading files.",
        task_background="No prior runs.",
        tool_policy={"default": "deny"},
        project_snapshot="# Snapshot\n\nNo additional context.",
    )


def test_executes_run_through_multi_round_tool_loop(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "example.txt").write_text(
        "hello world\n",
        encoding="utf-8",
    )

    agent_directory = tmp_path / "agents" / "agent-test"
    agent_directory.mkdir(parents=True)
    _write_tool_policy(agent_directory)

    provider = FakeProvider()
    agent_repository = FakeAgentRepository(agent_directory)
    run_repository = RunRepository(tmp_path / "tasks")

    executor = LLMAgentRunExecutor(
        provider=provider,
        settings=_build_settings(),
        agent_repository=agent_repository,
        run_repository=run_repository,
        project_root=repository_root,
    )

    context = _build_context()

    result = executor.execute(context)

    # agent_directory is resolved from context.agent.id, not a hardcoded path
    assert agent_repository.requested_agent_ids == ["agent-test"]

    # ToolExecutor is built from the agent's own tool-policy.json:
    # only read_file is enabled, so only it is offered to the model
    first_request = provider.requests[0]
    tool_names = {tool.name for tool in first_request.tools}
    assert tool_names == {"read_file"}

    # LLMRequest is constructed with the resolved model and run input
    assert first_request.model == "claude-default-model"
    assert isinstance(first_request.messages[0].content, str)
    assert "Please inspect example.txt." in first_request.messages[0].content

    # The multi-round LLMRunExecutor loop actually ran: one tool_use
    # round followed by the final answer
    assert provider.call_count == 2

    second_request = provider.requests[1]
    assert second_request.messages[-1].role == "user"
    tool_result_content = second_request.messages[-1].content
    assert tool_result_content[0]["content"] == "1: hello world"

    # A RunExecutionResult is returned
    assert isinstance(result, RunExecutionResult)

    # output_markdown contains the model's final text and cumulative
    # (not just last-round) token usage
    assert "The file contains: hello world." in result.output_markdown
    assert "Input tokens: `50`" in result.output_markdown
    assert "Output tokens: `20`" in result.output_markdown

    # summary_markdown is generated with cumulative usage and round counts
    assert "Run Summary" in result.summary_markdown
    assert "run-1" in result.summary_markdown
    assert "Total tokens: `70`" in result.summary_markdown
    assert "LLM rounds: `2`" in result.summary_markdown
    assert "Tool rounds: `1`" in result.summary_markdown
    assert "Tool calls: `1`" in result.summary_markdown

    # events.jsonl is written with one line per LLM/tool-call event,
    # and does not include full tool output by default (debug mode off)
    events_file = run_repository.get_events_file("task-1", "run-1")
    events = [
        json.loads(line)
        for line in events_file.read_text(encoding="utf-8").splitlines()
    ]

    assert [event["type"] for event in events] == [
        "llm_response",
        "tool_call",
        "tool_result",
        "llm_response",
        "run_completed",
    ]

    tool_call_event = events[1]
    assert tool_call_event["name"] == "read_file"
    assert tool_call_event["input"] == {"path": "example.txt"}

    tool_result_event = events[2]
    assert tool_result_event["name"] == "read_file"
    assert tool_result_event["success"] is True
    assert tool_result_event["output_chars"] == len("1: hello world")
    assert tool_result_event["truncated"] is False
    assert isinstance(tool_result_event["duration_ms"], int)
    assert "output" not in tool_result_event


def test_uses_agent_default_model_when_not_placeholder(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "example.txt").write_text(
        "hello world\n",
        encoding="utf-8",
    )

    agent_directory = tmp_path / "agents" / "agent-test"
    agent_directory.mkdir(parents=True)
    _write_tool_policy(agent_directory)

    provider = FakeProvider()
    agent_repository = FakeAgentRepository(agent_directory)

    executor = LLMAgentRunExecutor(
        provider=provider,
        settings=_build_settings(),
        agent_repository=agent_repository,
        run_repository=RunRepository(tmp_path / "tasks"),
        project_root=repository_root,
    )

    agent = _build_agent(default_model="claude-agent-specific-model")
    context = _build_context(agent=agent)

    executor.execute(context)

    assert provider.requests[0].model == "claude-agent-specific-model"


def test_debug_mode_includes_full_tool_output_in_events(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "example.txt").write_text(
        "hello world\n",
        encoding="utf-8",
    )

    agent_directory = tmp_path / "agents" / "agent-test"
    agent_directory.mkdir(parents=True)
    _write_tool_policy(agent_directory)

    run_repository = RunRepository(tmp_path / "tasks")

    executor = LLMAgentRunExecutor(
        provider=FakeProvider(),
        settings=_build_settings(debug_log_full_output=True),
        agent_repository=FakeAgentRepository(agent_directory),
        run_repository=run_repository,
        project_root=repository_root,
    )

    executor.execute(_build_context())

    events_file = run_repository.get_events_file("task-1", "run-1")
    events = [
        json.loads(line)
        for line in events_file.read_text(encoding="utf-8").splitlines()
    ]

    tool_result_event = next(
        event for event in events if event["type"] == "tool_result"
    )
    assert tool_result_event["output"] == "1: hello world"
