from __future__ import annotations

import json
from pathlib import Path

from src.agent_handlers.llm_agent_handler import LLMAgentHandler
from src.agent_message import AgentMessage
from src.agent_registry import AgentRegistry
from src.agent_runtime_factory import AgentRuntimeFactory
from src.agents.task_agent import TaskAgent
from src.agents.task_agent_registry import TaskAgentRegistry
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
                "template_id": "general",
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


def _factory(
    agents_dir: Path, task_agent_registry: TaskAgentRegistry | None = None
) -> AgentRuntimeFactory:
    registry = AgentRegistry(AgentRepository(agents_dir))
    return AgentRuntimeFactory(
        registry,
        task_agent_registry or TaskAgentRegistry(),
        FakeTaskService(),
        FakeRunService(),
    )


def test_create_handlers_returns_only_agents_assigned_to_the_task(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-coder")
    _write_agent(agents_dir, "agent-general")

    task_agent_registry = TaskAgentRegistry()
    task_agent_registry.assign_agent(
        TaskAgent(
            agent_id="agent-coder", task_id="task-a", template_id="coder"
        )
    )

    handlers = _factory(agents_dir, task_agent_registry).create_handlers(
        "task-a"
    )

    assert {handler.agent_id for handler in handlers} == {"agent-coder"}


def test_create_handlers_returns_llm_agent_handlers(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-coder")

    task_agent_registry = TaskAgentRegistry()
    task_agent_registry.assign_agent(
        TaskAgent(
            agent_id="agent-coder", task_id="task-a", template_id="coder"
        )
    )

    handlers = _factory(agents_dir, task_agent_registry).create_handlers(
        "task-a"
    )

    assert isinstance(handlers[0], LLMAgentHandler)


def test_create_handlers_returns_empty_list_when_no_agents_assigned(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    assert (
        _factory(agents_dir).create_handlers("task-a") == []
    )


def test_globally_registered_but_unassigned_agent_is_invisible(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-coder")
    _write_agent(agents_dir, "agent-unassigned")

    task_agent_registry = TaskAgentRegistry()
    task_agent_registry.assign_agent(
        TaskAgent(
            agent_id="agent-coder", task_id="task-a", template_id="coder"
        )
    )

    handlers = _factory(agents_dir, task_agent_registry).create_handlers(
        "task-a"
    )

    assert {handler.agent_id for handler in handlers} == {"agent-coder"}


def test_task_a_and_task_b_runtimes_are_isolated(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-a")
    _write_agent(agents_dir, "agent-b")

    task_agent_registry = TaskAgentRegistry()
    task_agent_registry.assign_agent(
        TaskAgent(
            agent_id="agent-a", task_id="task-a", template_id="coder"
        )
    )
    task_agent_registry.assign_agent(
        TaskAgent(
            agent_id="agent-b", task_id="task-b", template_id="coder"
        )
    )
    factory = _factory(agents_dir, task_agent_registry)

    handlers_a = factory.create_handlers("task-a")
    handlers_b = factory.create_handlers("task-b")

    assert {handler.agent_id for handler in handlers_a} == {"agent-a"}
    assert {handler.agent_id for handler in handlers_b} == {"agent-b"}


def test_released_task_has_no_runtime_handlers(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-coder")

    task_agent_registry = TaskAgentRegistry()
    task_agent_registry.assign_agent(
        TaskAgent(
            agent_id="agent-coder", task_id="task-a", template_id="coder"
        )
    )
    factory = _factory(agents_dir, task_agent_registry)
    assert len(factory.create_handlers("task-a")) == 1

    task_agent_registry.remove_task_agents("task-a")

    assert factory.create_handlers("task-a") == []


def test_handlers_wire_into_message_router(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-coder")
    _write_agent(agents_dir, "agent-general")

    task_agent_registry = TaskAgentRegistry()
    task_agent_registry.assign_agent(
        TaskAgent(
            agent_id="agent-coder", task_id="task-a", template_id="coder"
        )
    )

    router = MessageRouter(
        _factory(agents_dir, task_agent_registry).create_handlers(
            "task-a"
        ),
        task_agent_registry,
    )

    message = AgentMessage(
        sender_id="manager",
        receiver_id="agent-coder",
        task_id="task-a",
        content="fix bug",
        context={},
    )

    response = router.send(message)

    assert response == (
        "Run run-001 finished with status 'completed'. "
        "Output: output.md"
    )
