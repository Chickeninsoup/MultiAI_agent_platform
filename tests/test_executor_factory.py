


















import json
from pathlib import Path

from src.executor_factory import create_tool_executor

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REAL_TEST_POLICY_PATH = (
    _PROJECT_ROOT / "src" / "config" / "test_policy.json"
)


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
        test_policy_path=_REAL_TEST_POLICY_PATH,
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


def test_create_tool_executor_disables_write_file_by_default(
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
                    "write_file": {
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
        test_policy_path=_REAL_TEST_POLICY_PATH,
    )

    tool_names = {
        definition.name
        for definition in executor.get_definitions()
    }

    assert "write_file" not in tool_names


def test_create_tool_executor_enables_write_file_for_coder_agent(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    agent_directory = tmp_path / "agent-coder"
    agent_directory.mkdir()

    policy_path = agent_directory / "tool-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "default": "deny",
                "tools": {
                    "write_file": {
                        "enabled": True,
                        "max_write_bytes": 10,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    executor = create_tool_executor(
        repository_root=repository_root,
        agent_directory=agent_directory,
        test_policy_path=_REAL_TEST_POLICY_PATH,
    )

    tool_names = {
        definition.name
        for definition in executor.get_definitions()
    }

    assert "write_file" in tool_names

    from src.domain.tools.tool_call import ToolCall

    result = executor.execute(
        ToolCall(
            id="tool-call-1",
            name="write_file",
            input={
                "path": "too_long.txt",
                "content": "this content is too long",
            },
        )
    )

    assert result.success is False
    assert result.error_code == "WRITE_SIZE_LIMIT_EXCEEDED"


def test_create_tool_executor_disables_patch_file_by_default(
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
                    "patch_file": {
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
        test_policy_path=_REAL_TEST_POLICY_PATH,
    )

    tool_names = {
        definition.name
        for definition in executor.get_definitions()
    }

    assert "patch_file" not in tool_names


def test_create_tool_executor_enables_patch_file_for_coder_agent(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    agent_directory = tmp_path / "agent-coder"
    agent_directory.mkdir()

    policy_path = agent_directory / "tool-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "default": "deny",
                "tools": {
                    "patch_file": {
                        "enabled": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    executor = create_tool_executor(
        repository_root=repository_root,
        agent_directory=agent_directory,
        test_policy_path=_REAL_TEST_POLICY_PATH,
    )

    tool_names = {
        definition.name
        for definition in executor.get_definitions()
    }

    assert "patch_file" in tool_names

    from src.domain.tools.tool_call import ToolCall

    target = repository_root / "test.py"
    target.write_text("hello\n", encoding="utf-8")

    result = executor.execute(
        ToolCall(
            id="tool-call-1",
            name="patch_file",
            input={
                "path": "test.py",
                "old_text": "hello",
                "new_text": "hi",
            },
        )
    )

    assert result.success is True
    assert result.metadata["operation"] == "patch"
    assert target.read_text(encoding="utf-8") == "hi\n"


def test_real_agent_coder_policy_exposes_mutation_tools(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    project_root = Path(__file__).resolve().parent.parent

    executor = create_tool_executor(
        repository_root=repository_root,
        agent_directory=project_root / "agents" / "agent-coder",
        test_policy_path=_REAL_TEST_POLICY_PATH,
    )

    tool_names = {
        definition.name
        for definition in executor.get_definitions()
    }

    assert tool_names == {
        "list_files",
        "read_file",
        "git_status",
        "git_diff",
        "write_file",
        "patch_file",
        "run_test",
    }


def test_real_agent_general_policy_hides_mutation_tools(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    project_root = Path(__file__).resolve().parent.parent

    executor = create_tool_executor(
        repository_root=repository_root,
        agent_directory=project_root / "agents" / "agent-general",
        test_policy_path=_REAL_TEST_POLICY_PATH,
    )

    tool_names = {
        definition.name
        for definition in executor.get_definitions()
    }

    assert tool_names == {
        "list_files",
        "read_file",
        "git_status",
        "git_diff",
    }
    assert "write_file" not in tool_names
    assert "patch_file" not in tool_names
    assert "run_test" not in tool_names


def test_create_tool_executor_disables_run_test_by_default(
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
                    "run_test": {
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
        test_policy_path=_REAL_TEST_POLICY_PATH,
    )

    tool_names = {
        definition.name
        for definition in executor.get_definitions()
    }

    assert "run_test" not in tool_names


def test_create_tool_executor_enables_run_test_for_coder_agent(
    tmp_path: Path,
) -> None:
    # The registered "compile" command is `.venv/bin/python -m
    # compileall src`, relative to repository_root — so this has to
    # run against the real project root (which has a .venv), not a
    # throwaway tmp_path directory.
    repository_root = _PROJECT_ROOT

    agent_directory = tmp_path / "agent-coder"
    agent_directory.mkdir()

    policy_path = agent_directory / "tool-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "default": "deny",
                "tools": {
                    "run_test": {
                        "enabled": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    executor = create_tool_executor(
        repository_root=repository_root,
        agent_directory=agent_directory,
        test_policy_path=_REAL_TEST_POLICY_PATH,
    )

    tool_names = {
        definition.name
        for definition in executor.get_definitions()
    }

    assert "run_test" in tool_names

    from src.domain.tools.tool_call import ToolCall

    result = executor.execute(
        ToolCall(
            id="tool-call-1",
            name="run_test",
            input={"test_name": "compile"},
        )
    )

    assert result.success is True
    assert result.metadata["exit_code"] == 0
    assert result.metadata["timed_out"] is False
