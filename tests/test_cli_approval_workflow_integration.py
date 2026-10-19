"""End-to-end 5E-5D-6D coverage, driven through src/main.py's real
command functions and real composition path (src/run_service_composition.py),
not by manually injecting a gate into a service fixture or mocking away
RunService. The only thing faked is the LLM provider itself (unavoidable -
these tests must never call a real Anthropic endpoint); everything else
(ToolExecutor, ToolPolicy, ApprovalPolicy loading, ToolApprovalGate,
RunService, the attempt/application repositories) is the real production
composition.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import src.main as main
from src.approval_resolution_repository import (
    ApprovalResolutionRepository,
)
from src.config.settings import Settings
from src.llm.types import (
    LLMRequest,
    LLMResponse,
    LLMTextBlock,
    LLMToolUseBlock,
    LLMUsage,
)
from src.repositories import AgentRepository, RunRepository, TaskRepository
from src.run_continuation_attempt_record import (
    ATTEMPT_RECORD_SCHEMA_VERSION,
    RunContinuationAttemptRecord,
)
from src.run_continuation_attempt_repository import (
    RunContinuationAttemptRepository,
)
from src.run_continuation_attempt_status import (
    RunContinuationAttemptStatus,
)

NOW = "2026-01-01T00:00:00Z"
TASK_ID = "task-1"
RUN_ID = "run-001"
AGENT_ID = "agent-test"
SECRET_B = "super-secret-b-content"
SECRET_C = "super-secret-c-content"


# --- fake provider ---------------------------------------------------


class _ScriptedCliProvider:
    provider_name = "fake"

    def __init__(self) -> None:
        self._responses: list[LLMResponse] = []
        self.received_requests: list[LLMRequest] = []

    def queue(self, *responses: LLMResponse) -> None:
        self._responses.extend(responses)

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.received_requests.append(request)

        if not self._responses:
            raise AssertionError(
                "Scripted CLI provider ran out of responses"
            )

        return self._responses.pop(0)


def _final_response(text: str = "All done.") -> LLMResponse:
    return LLMResponse(
        content=[LLMTextBlock(type="text", text=text)],
        stop_reason="end_turn",
        usage=LLMUsage(input_tokens=5, output_tokens=3),
    )


def _round_response(
    *tool_uses: tuple[str, str, dict[str, Any]],
) -> LLMResponse:
    return LLMResponse(
        content=[
            LLMToolUseBlock(type="tool_use", id=id_, name=name, input=input_)
            for id_, name, input_ in tool_uses
        ],
        stop_reason="tool_use",
        usage=LLMUsage(input_tokens=20, output_tokens=10),
    )


def _poisoned_create_llm_provider(settings: Settings):
    raise AssertionError(
        "create_llm_provider() must not be called by a read-only "
        "command, decision recording, or a cached continuation replay"
    )


# --- fixture scaffolding -----------------------------------------------


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_agent(agents_dir: Path, agent_id: str = AGENT_ID) -> None:
    agent_dir = agents_dir / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "system-prompt.md").write_text(
        "You are a test agent.", encoding="utf-8"
    )
    _write_json(
        agent_dir / "tool-policy.json",
        {
            "default": "deny",
            "tools": {
                "read_file": {"enabled": True},
                "write_file": {"enabled": True},
            },
        },
    )
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


def _write_task_and_run(
    tasks_dir: Path,
    *,
    task_id: str = TASK_ID,
    run_id: str = RUN_ID,
    agent_id: str = AGENT_ID,
) -> None:
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
    _write_json(
        tasks_dir / task_id / "runs" / run_id / "run.json",
        {
            "id": run_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "status": "in_progress",
            "created_at": NOW,
            "updated_at": NOW,
            "started_at": NOW,
            "completed_at": None,
        },
    )
    RunRepository(tasks_dir).write_input(task_id, run_id, "do the task")


def _write_approval_policy(
    path: Path, *, tool_names: tuple[str, ...] = ("write_file",)
) -> None:
    _write_json(
        path,
        {
            "rules": [
                {
                    "tool_name": tool_name,
                    "risk_level": "medium",
                    "reason": f"{tool_name} requires review",
                }
                for tool_name in tool_names
            ]
        },
    )


def _build_settings(
    tmp_path: Path, *, approval_policy_path: Path | None = None
) -> Settings:
    policy_path = approval_policy_path or (tmp_path / "approval_policy.json")

    return Settings(
        execution_mode="llm",
        llm_provider="anthropic",
        anthropic_api_key=None,
        anthropic_model="fake-model",
        llm_timeout_seconds=60.0,
        llm_max_retries=2,
        llm_max_tokens=4096,
        llm_max_tool_rounds=8,
        llm_max_total_tokens=100_000,
        debug_log_full_output=False,
        test_policy_path="src/config/test_policy.json",
        approval_policy_path=str(policy_path),
    )


def _write_fake_project_root(project_root: Path) -> None:
    """A minimal, isolated stand-in repository root (5E-5D-6D) - write_
    file/read_file tool calls resolve paths relative to whatever
    project_root the composition was built with
    (LLMAgentRunExecutor._resolve_repository_root() always returns it),
    so these tests must never let that be the real repository root.
    Only src/config/test_policy.json is required content (TestPolicy.
    load() runs eagerly inside create_tool_executor(), even though
    run_test is never actually invoked by these tests)."""

    _write_json(
        project_root / "src" / "config" / "test_policy.json",
        {"tests": {}},
    )


def _wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: _ScriptedCliProvider,
    tool_names: tuple[str, ...] = ("write_file",),
    task_id: str = TASK_ID,
    run_id: str = RUN_ID,
    agent_id: str = AGENT_ID,
) -> Path:
    tasks_dir = tmp_path / "tasks"
    agents_dir = tmp_path / "agents"
    project_root = tmp_path / "repo"

    _write_fake_project_root(project_root)
    _write_agent(agents_dir, agent_id)
    _write_task_and_run(
        tasks_dir, task_id=task_id, run_id=run_id, agent_id=agent_id
    )

    policy_path = tmp_path / "approval_policy.json"
    _write_approval_policy(policy_path, tool_names=tool_names)

    monkeypatch.setattr(main, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(main, "TASKS_DIR", tasks_dir)
    monkeypatch.setattr(main, "AGENTS_DIR", agents_dir)
    monkeypatch.setattr(main, "task_repository", TaskRepository(tasks_dir))
    monkeypatch.setattr(main, "run_repository", RunRepository(tasks_dir))
    monkeypatch.setattr(
        main, "agent_repository", AgentRepository(agents_dir)
    )
    monkeypatch.setattr(
        main, "settings", _build_settings(tmp_path, approval_policy_path=policy_path)
    )
    monkeypatch.setattr(
        "src.executor_factory.create_llm_provider",
        lambda settings: provider,
    )

    return tasks_dir


# --- pause behavior -----------------------------------------------------


def test_nonempty_configuration_pauses_before_target_tool_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    provider = _ScriptedCliProvider()
    provider.queue(
        _round_response(
            ("toolu_a", "read_file", {"path": "does-not-exist.txt"}),
            ("toolu_b", "write_file", {"path": "b.txt", "content": SECRET_B}),
        )
    )
    _wire(tmp_path, monkeypatch, provider=provider)

    main.run_task(TASK_ID)

    out = capsys.readouterr().out
    assert "waiting_for_approval" in out
    assert "Approval ID:" in out
    assert SECRET_B not in out

    run = RunRepository(tmp_path / "tasks").load(TASK_ID, RUN_ID)
    assert run.status == "waiting_for_approval"
    # b.txt was never written - the gated call never executed.
    assert not (tmp_path / "b.txt").exists()


def _pause_on_write_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: _ScriptedCliProvider,
    tool_names: tuple[str, ...] = ("write_file",),
) -> str:
    provider.queue(
        _round_response(
            ("toolu_a", "read_file", {"path": "missing.txt"}),
            ("toolu_b", "write_file", {"path": "b.txt", "content": SECRET_B}),
        )
    )
    _wire(tmp_path, monkeypatch, provider=provider, tool_names=tool_names)

    main.run_task(TASK_ID)

    run = RunRepository(tmp_path / "tasks").load(TASK_ID, RUN_ID)
    assert run.metadata.get("approval_id") is not None

    return run.metadata["approval_id"]


# --- list / show ----------------------------------------------------------


def test_list_and_show_display_safe_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    provider = _ScriptedCliProvider()
    approval_id = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)
    capsys.readouterr()

    main.list_tool_approvals()
    list_output = capsys.readouterr().out
    assert approval_id in list_output
    assert RUN_ID in list_output
    assert "write_file" in list_output
    assert SECRET_B not in list_output

    main.show_tool_approval(approval_id)
    show_output = capsys.readouterr().out
    assert approval_id in show_output
    assert RUN_ID in show_output
    assert TASK_ID in show_output
    assert "write_file" in show_output
    assert "Decision: pending" in show_output
    assert SECRET_B not in show_output
    assert "b.txt" in show_output  # path is a reviewed-safe field


def test_list_tool_approvals_filters_by_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    provider = _ScriptedCliProvider()
    _pause_on_write_file(tmp_path, monkeypatch, provider=provider)
    capsys.readouterr()

    main.list_tool_approvals(run_id="run-does-not-exist")
    assert "No pending" in capsys.readouterr().out

    main.list_tool_approvals(run_id=RUN_ID)
    assert RUN_ID in capsys.readouterr().out


# --- decision recording leaves target unchanged --------------------------


def test_recording_decision_does_not_touch_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _ScriptedCliProvider()
    approval_id = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)

    main.approve_tool_call(approval_id)

    assert not (tmp_path / "b.txt").exists()
    resolution = ApprovalResolutionRepository(tmp_path / "tasks").get(
        approval_id
    )
    assert resolution is not None


# --- explicit resume ------------------------------------------------------


def test_explicit_resume_executes_approved_call_and_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    provider = _ScriptedCliProvider()
    approval_id = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)
    provider.queue(_final_response())

    main.approve_tool_call(approval_id)
    capsys.readouterr()

    main.resume_after_approval_command(RUN_ID, approval_id)

    output = capsys.readouterr().out
    assert "Continued run" in output
    assert "Replayed" not in output

    repo_root = Path(main.PROJECT_ROOT)
    written = (repo_root / "b.txt")
    assert written.exists()
    assert written.read_text(encoding="utf-8") == SECRET_B
    written.unlink()

    run = RunRepository(tmp_path / "tasks").load(TASK_ID, RUN_ID)
    assert run.status in ("completed", "awaiting_review")


def test_repeating_resume_adds_no_additional_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    provider = _ScriptedCliProvider()
    approval_id = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)
    provider.queue(_final_response())
    main.approve_tool_call(approval_id)
    main.resume_after_approval_command(RUN_ID, approval_id)

    repo_root = Path(main.PROJECT_ROOT)
    written = repo_root / "b.txt"
    assert written.exists()
    written_at_first = written.read_text(encoding="utf-8")
    requests_before = len(provider.received_requests)
    capsys.readouterr()

    # Poison the provider so any further call fails loudly.
    def _poisoned_complete(request):
        raise AssertionError("provider must not be called on replay")

    monkeypatch.setattr(provider, "complete", _poisoned_complete)

    main.resume_after_approval_command(RUN_ID, approval_id)

    output = capsys.readouterr().out
    assert "Replayed an earlier completed continuation" in output
    assert written.read_text(encoding="utf-8") == written_at_first
    assert len(provider.received_requests) == requests_before
    written.unlink()


# --- MODIFY / REJECT / CANCEL ----------------------------------------------


def test_modify_executes_replacement_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    provider = _ScriptedCliProvider()
    approval_id = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)
    provider.queue(_final_response())

    modified_input_file = tmp_path / "modified.json"
    modified_input_file.write_text(
        json.dumps({"path": "modified.txt", "content": "replacement"}),
        encoding="utf-8",
    )
    main.modify_tool_call(approval_id, str(modified_input_file))
    capsys.readouterr()

    main.resume_after_approval_command(RUN_ID, approval_id)

    repo_root = Path(main.PROJECT_ROOT)
    assert not (repo_root / "b.txt").exists()
    written = repo_root / "modified.txt"
    assert written.exists()
    assert written.read_text(encoding="utf-8") == "replacement"
    written.unlink()


def test_reject_skips_handler_and_continues_normally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    provider = _ScriptedCliProvider()
    approval_id = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)
    provider.queue(_final_response())

    main.reject_tool_call(approval_id)
    capsys.readouterr()

    main.resume_after_approval_command(RUN_ID, approval_id)

    repo_root = Path(main.PROJECT_ROOT)
    assert not (repo_root / "b.txt").exists()
    run = RunRepository(tmp_path / "tasks").load(TASK_ID, RUN_ID)
    assert run.status in ("completed", "awaiting_review")


def test_cancel_stops_without_further_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    provider = _ScriptedCliProvider()
    approval_id = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)
    requests_before = len(provider.received_requests)

    main.cancel_tool_call(approval_id)
    capsys.readouterr()

    main.resume_after_approval_command(RUN_ID, approval_id)
    output = capsys.readouterr().out

    assert "cancelled" in output.lower()
    run = RunRepository(tmp_path / "tasks").load(TASK_ID, RUN_ID)
    assert run.status == "cancelled"
    assert run.id == RUN_ID
    # No further provider calls were made for CANCEL.
    assert len(provider.received_requests) == requests_before
    repo_root = Path(main.PROJECT_ROOT)
    assert not (repo_root / "b.txt").exists()


# --- a later gated call produces a second approval ------------------------


def test_second_gated_call_produces_new_approval_for_same_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    provider = _ScriptedCliProvider()
    approval_id_b = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)

    # Round 2: a fresh gated write_file call (C).
    provider.queue(
        _round_response(
            ("toolu_c", "write_file", {"path": "c.txt", "content": SECRET_C})
        )
    )
    main.approve_tool_call(approval_id_b)
    capsys.readouterr()

    main.resume_after_approval_command(RUN_ID, approval_id_b)
    output = capsys.readouterr().out

    assert "waiting_for_approval" in output.lower() or "paused again" in output

    run = RunRepository(tmp_path / "tasks").load(TASK_ID, RUN_ID)
    assert run.status == "waiting_for_approval"
    approval_id_c = run.metadata["approval_id"]
    assert approval_id_c != approval_id_b

    repo_root = Path(main.PROJECT_ROOT)
    assert (repo_root / "b.txt").exists()
    assert not (repo_root / "c.txt").exists()
    (repo_root / "b.txt").unlink()

    # Retrying the earlier approval replays its own cached transition
    # (RUN_WAITING_FOR_APPROVAL, pointing at C) - it does not raise,
    # and it does not touch C.
    main.resume_after_approval_command(RUN_ID, approval_id_b)
    assert not (repo_root / "c.txt").exists()

    # Resolve C and finish.
    provider.queue(_final_response())
    main.approve_tool_call(approval_id_c)
    main.resume_after_approval_command(RUN_ID, approval_id_c)

    written_c = repo_root / "c.txt"
    assert written_c.exists()
    assert written_c.read_text(encoding="utf-8") == SECRET_C
    written_c.unlink()


# --- fresh CLI composition retains the Run's approval rules ---------------


def test_fresh_composition_retains_run_rules_even_if_config_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    provider = _ScriptedCliProvider()
    approval_id_b = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)

    provider.queue(
        _round_response(
            ("toolu_c", "write_file", {"path": "c.txt", "content": SECRET_C})
        )
    )
    main.approve_tool_call(approval_id_b)

    # Simulate the live config changing (or vanishing) between the
    # original `run` and this later `resume-after-approval` - a fresh
    # CLI invocation (new process) would re-read this file from
    # scratch. Overwrite the live policy file with an EMPTY rule set.
    policy_path = tmp_path / "approval_policy.json"
    _write_approval_policy(policy_path, tool_names=())
    monkeypatch.setattr(
        main,
        "settings",
        _build_settings(tmp_path, approval_policy_path=policy_path),
    )

    main.resume_after_approval_command(RUN_ID, approval_id_b)

    # C still required approval - the Run's OWN snapshot governed
    # continuation, not the now-empty live config.
    run = RunRepository(tmp_path / "tasks").load(TASK_ID, RUN_ID)
    assert run.status == "waiting_for_approval"

    repo_root = Path(main.PROJECT_ROOT)
    assert not (repo_root / "c.txt").exists()
    (repo_root / "b.txt").unlink(missing_ok=True)


# --- ordinary resume cannot bypass an incomplete continuation attempt -----


def test_ordinary_resume_cannot_bypass_incomplete_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.run_continuation_attempt_errors import (
        RunContinuationBlockedError,
    )

    provider = _ScriptedCliProvider()
    approval_id = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)
    main.approve_tool_call(approval_id)

    tasks_dir = tmp_path / "tasks"
    stuck_claim = RunContinuationAttemptRecord(
        schema_version=ATTEMPT_RECORD_SCHEMA_VERSION,
        task_id=TASK_ID,
        run_id=RUN_ID,
        approval_id=approval_id,
        status=RunContinuationAttemptStatus.CLAIMED,
    )
    RunContinuationAttemptRepository(tasks_dir).create_exclusive(
        stuck_claim
    )

    with pytest.raises(RunContinuationBlockedError):
        main.resume_run(RUN_ID)

    run = RunRepository(tasks_dir).load(TASK_ID, RUN_ID)
    assert run.status == "waiting_for_approval"


# --- empty configuration preserves existing behavior ----------------------


def test_empty_configuration_preserves_existing_ungated_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _ScriptedCliProvider()
    provider.queue(
        _round_response(
            ("toolu_a", "read_file", {"path": "missing.txt"}),
            ("toolu_b", "write_file", {"path": "b.txt", "content": SECRET_B}),
        ),
        _final_response(),
    )
    _wire(tmp_path, monkeypatch, provider=provider, tool_names=())

    main.run_task(TASK_ID)

    run = RunRepository(tmp_path / "tasks").load(TASK_ID, RUN_ID)
    assert run.status in ("completed", "awaiting_review")

    repo_root = Path(main.PROJECT_ROOT)
    written = repo_root / "b.txt"
    assert written.exists()
    written.unlink()


# --- invalid configuration fails before execution -------------------------


def test_invalid_configuration_fails_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.approval_policy_config import ApprovalPolicyConfigError

    provider = _ScriptedCliProvider()
    _wire(tmp_path, monkeypatch, provider=provider)

    bad_policy_path = tmp_path / "approval_policy.json"
    _write_json(
        bad_policy_path,
        {
            "rules": [
                {
                    "tool_name": "not_a_real_tool",
                    "risk_level": "medium",
                    "reason": "x",
                }
            ]
        },
    )
    monkeypatch.setattr(
        main,
        "settings",
        _build_settings(tmp_path, approval_policy_path=bad_policy_path),
    )

    with pytest.raises(ApprovalPolicyConfigError):
        main.run_task(TASK_ID)

    assert provider.received_requests == []
    repo_root = Path(main.PROJECT_ROOT)
    assert not (repo_root / "b.txt").exists()


# --- secrets stay out of inspection/decision/error output -----------------


def test_secrets_stay_out_of_all_output_and_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    provider = _ScriptedCliProvider()
    approval_id = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)
    capsys.readouterr()

    main.list_tool_approvals()
    main.show_tool_approval(approval_id)
    main.approve_tool_call(approval_id)
    main.show_tool_approval(approval_id)

    output = capsys.readouterr().out
    assert SECRET_B not in output

    # Scoped to the approval-specific audit events this stage controls
    # (approval_requested/approval_resolved/approval_applied) - not the
    # whole events.jsonl file, which also carries the LLM executor's
    # own pre-existing "tool_call"/"tool_result" events (established
    # well before this stage, logging raw input/output by design for
    # debugging - a separate, already-existing audit mechanism this
    # stage does not change).
    events_path = (
        tmp_path / "tasks" / TASK_ID / "runs" / RUN_ID / "events.jsonl"
    )
    approval_events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        and json.loads(line).get("type")
        in {
            "approval_requested",
            "approval_resolved",
            "approval_applied",
        }
    ]
    assert approval_events
    for event in approval_events:
        assert SECRET_B not in json.dumps(event)


# --- provider never initialized for read-only / decision / replay --------


def test_read_only_commands_do_not_initialize_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _ScriptedCliProvider()
    approval_id = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)

    monkeypatch.setattr(
        "src.executor_factory.create_llm_provider",
        _poisoned_create_llm_provider,
    )

    main.list_tool_approvals()
    main.show_tool_approval(approval_id)


def test_decision_recording_does_not_initialize_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _ScriptedCliProvider()
    approval_id = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)

    monkeypatch.setattr(
        "src.executor_factory.create_llm_provider",
        _poisoned_create_llm_provider,
    )

    main.approve_tool_call(approval_id)


def test_cached_replay_does_not_initialize_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _ScriptedCliProvider()
    approval_id = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)
    provider.queue(_final_response())
    main.approve_tool_call(approval_id)
    main.resume_after_approval_command(RUN_ID, approval_id)

    repo_root = Path(main.PROJECT_ROOT)
    (repo_root / "b.txt").unlink(missing_ok=True)

    monkeypatch.setattr(
        "src.executor_factory.create_llm_provider",
        _poisoned_create_llm_provider,
    )

    # A cached replay must not need the provider at all.
    main.resume_after_approval_command(RUN_ID, approval_id)


def test_cancel_replay_does_not_initialize_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _ScriptedCliProvider()
    approval_id = _pause_on_write_file(tmp_path, monkeypatch, provider=provider)
    main.cancel_tool_call(approval_id)
    main.resume_after_approval_command(RUN_ID, approval_id)

    monkeypatch.setattr(
        "src.executor_factory.create_llm_provider",
        _poisoned_create_llm_provider,
    )

    # Replaying an already-cancelled continuation must not need the
    # provider either.
    main.resume_after_approval_command(RUN_ID, approval_id)


def test_help_does_not_initialize_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.executor_factory.create_llm_provider",
        _poisoned_create_llm_provider,
    )

    parser = main.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
