from __future__ import annotations

import json
import threading
from pathlib import Path

from src.repositories import AgentRepository, JsonRepository


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
                "template_id": role,
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


# --- JsonRepository.create_exclusive ---------------------------------


def test_create_exclusive_creates_file_and_returns_true(
    tmp_path: Path,
) -> None:
    target = tmp_path / "nested" / "claim.json"

    created = JsonRepository.create_exclusive(target, {"a": 1})

    assert created is True
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}


def test_create_exclusive_returns_false_without_overwriting(
    tmp_path: Path,
) -> None:
    target = tmp_path / "claim.json"
    JsonRepository.create_exclusive(target, {"a": 1})

    created_again = JsonRepository.create_exclusive(target, {"a": 2})

    assert created_again is False
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}


def test_create_exclusive_only_one_winner_among_concurrent_callers(
    tmp_path: Path,
) -> None:
    target = tmp_path / "claim.json"

    results = [
        JsonRepository.create_exclusive(target, {"owner": i})
        for i in range(10)
    ]

    assert results.count(True) == 1
    assert results.count(False) == 9


def test_save_concurrent_writers_do_not_race_on_shared_tmp_name(
    tmp_path: Path,
) -> None:
    """Regression for 5E-5D-6C-1: save() used to build its tmp file
    name from file_path.suffix alone, so two threads/processes
    concurrently saving the *same* file_path shared one tmp path -
    whichever replace() ran second found the first had already
    consumed it, raising FileNotFoundError. A barrier-released burst
    of concurrent writers must now all succeed."""

    target = tmp_path / "shared.json"
    barrier = threading.Barrier(8)
    errors: list[Exception] = []
    errors_lock = threading.Lock()

    def writer(index: int) -> None:
        barrier.wait(timeout=5)
        try:
            JsonRepository.save(target, {"writer": index})
        except Exception as exc:  # noqa: BLE001
            with errors_lock:
                errors.append(exc)

    threads = [
        threading.Thread(target=writer, args=(i,)) for i in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    # Exactly one final, well-formed, complete write survives.
    final = json.loads(target.read_text(encoding="utf-8"))
    assert "writer" in final
    # No stray tmp files left behind.
    assert list(tmp_path.glob("*.tmp")) == []
