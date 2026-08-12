from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent_registry import AgentRegistry
from src.repositories import AgentRepository


def _write_agent(
    agents_dir: Path,
    agent_id: str,
    *,
    role: str = "general",
) -> None:
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
                "role": role,
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


def test_list_agents_returns_all_registered_agents(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-a", role="general")
    _write_agent(agents_dir, "agent-b", role="coder")

    registry = AgentRegistry(AgentRepository(agents_dir))

    agents = registry.list_agents()

    assert {agent.id for agent in agents} == {"agent-a", "agent-b"}


def test_list_agents_returns_empty_when_none_registered(
    tmp_path: Path,
) -> None:
    registry = AgentRegistry(AgentRepository(tmp_path / "agents"))

    assert registry.list_agents() == []


def test_get_agent_returns_matching_definition(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-a", role="coder")

    registry = AgentRegistry(AgentRepository(agents_dir))

    agent = registry.get_agent("agent-a")

    assert agent.id == "agent-a"
    assert agent.role == "coder"


def test_get_agent_raises_for_unknown_agent_id(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    registry = AgentRegistry(AgentRepository(agents_dir))

    with pytest.raises(FileNotFoundError):
        registry.get_agent("does-not-exist")


def test_list_agents_against_real_agents_directory() -> None:
    project_root = Path(__file__).resolve().parent
    registry = AgentRegistry(
        AgentRepository(project_root.parent / "agents")
    )

    agents = registry.list_agents()

    ids = {agent.id for agent in agents}
    assert "agent-general" in ids
    assert "agent-coder" in ids

    coder = registry.get_agent("agent-coder")
    assert coder.has_capability("file_writing")

    general = registry.get_agent("agent-general")
    assert not general.has_capability("file_writing")
