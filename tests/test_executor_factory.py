


















import json
from pathlib import Path

from src.executor_factory import create_tool_executor


def test_create_tool_executor_loads_agent_policy(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    agent_directory = tmp_path / "agent-general"
    agent_directory.mkdir()

    policy_path = agent_directory / "tool-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "default": "deny",
                "tools": {
                    "read_file": {
                        "enabled": True,
                    },
                    "list_files": {
                        "enabled": True,
                    },
                    "git_status": {
                        "enabled": False,
                    },
                    "git_diff": {
                        "enabled": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    executor = create_tool_executor(
        repository_root=repository_root,
        agent_directory=agent_directory,
    )

    definitions = executor.get_definitions()
    tool_names = {
        definition.name
        for definition in definitions
    }

    assert tool_names == {
        "read_file",
        "list_files",
    }
