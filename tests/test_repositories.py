from __future__ import annotations

import json
from pathlib import Path

from src.repositories import AgentRepository


def _write_agent(
    agents_dir: Path,
    agent_id: str,
    *,
    role: str = "general",
    capabilities: list[str] | None = None,
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
                "capabilities": capabilities or [],
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


def test_list_all_returns_empty_when_agents_dir_missing(
    tmp_path: Path,
) -> None:
    repository = AgentRepository(tmp_path / "agents")

    assert repository.list_all() == []


def test_list_all_returns_empty_when_no_agents(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    repository = AgentRepository(agents_dir)

    assert repository.list_all() == []


def test_list_all_loads_every_agent(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-a", role="general")
    _write_agent(agents_dir, "agent-b", role="coder")

    repository = AgentRepository(agents_dir)

    agents = repository.list_all()

    assert {agent.id for agent in agents} == {"agent-a", "agent-b"}
    assert {agent.role for agent in agents} == {"general", "coder"}


def test_list_all_skips_directories_without_agent_json(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-a")
    (agents_dir / "not-an-agent").mkdir(parents=True)

    repository = AgentRepository(agents_dir)

    agents = repository.list_all()

    assert [agent.id for agent in agents] == ["agent-a"]


def test_list_all_skips_non_directory_entries(
    tmp_path: Path,
) -> None:
    agents_dir = tmp_path / "agents"
    _write_agent(agents_dir, "agent-a")
    (agents_dir / "README.md").write_text("stray file", encoding="utf-8")

    repository = AgentRepository(agents_dir)

    agents = repository.list_all()

    assert [agent.id for agent in agents] == ["agent-a"]


def test_list_all_against_real_agents_directory() -> None:
    project_root = Path(__file__).resolve().parent.parent
    repository = AgentRepository(project_root / "agents")

    agents = repository.list_all()

    assert {agent.id for agent in agents} == {
        "agent-general",
        "agent-coder",
    }
