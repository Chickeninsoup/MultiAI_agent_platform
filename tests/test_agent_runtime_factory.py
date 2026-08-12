from __future__ import annotations

import json
from pathlib import Path

from src.agent_handlers.llm_agent_handler import LLMAgentHandler
from src.agent_message import AgentMessage
from src.agent_registry import AgentRegistry
from src.agent_runtime_factory import AgentRuntimeFactory
from src.message_router import MessageRouter
from src.repositories import AgentRepository


class _FakeTask:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class _FakeResult:
    def __init__(self) -> None:
        self.run_id = "run-001"
        self.status = "completed"
        self.output_path = "output.md"


class FakeTaskService:
    def create_task_and_run(self, **kwargs):
        return _FakeTask(kwargs["task_id"]), None


class FakeRunService:
    def execute(self, task_id: str):
        return _FakeResult()


def _write_agent(agents_dir: Path, agent_id: str) -> None:
    agent_dir = agents_dir / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent.json").write_text(
        json.dumps(
            {
                "id": agent_id,
                "name": agent_id,
                "description": "A test agent.",
                "owner": "owner-1",
                "status": "ready",
                "role": "general",
                "default_model": "claude-model-placeholder",
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
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )


def _factory(agents_dir: Path) -> AgentRuntimeFactory:
    registry = AgentRegistry(AgentRepository(agents_dir))
    return AgentRuntimeFactory(registry, FakeTaskService(), FakeRunService())


def test_create_handlers_returns_one_handler_per_registered_agent(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-coder")
    _write_agent(agents_dir, "agent-general")

    handlers = _factory(agents_dir).create_handlers()

    assert {handler.agent_id for handler in handlers} == {
        "agent-coder",
        "agent-general",
    }


def test_create_handlers_returns_llm_agent_handlers(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-coder")

    handlers = _factory(agents_dir).create_handlers()

    assert isinstance(handlers[0], LLMAgentHandler)


def test_create_handlers_returns_empty_list_when_no_agents(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    assert _factory(agents_dir).create_handlers() == []


def test_handlers_wire_into_message_router(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-coder")
    _write_agent(agents_dir, "agent-general")

    router = MessageRouter(_factory(agents_dir).create_handlers())

    message = AgentMessage(
        sender_id="manager",
        receiver_id="agent-coder",
        task_id="task-001",
        content="fix bug",
        context={},
    )

    response = router.send(message)

    assert response == (
        "Run run-001 finished with status 'completed'. "
        "Output: output.md"
    )


def test_new_agent_in_registry_is_picked_up_without_factory_changes(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-coder")

    factory = _factory(agents_dir)
    assert len(factory.create_handlers()) == 1

    _write_agent(agents_dir, "agent-researcher")

    assert len(factory.create_handlers()) == 2
