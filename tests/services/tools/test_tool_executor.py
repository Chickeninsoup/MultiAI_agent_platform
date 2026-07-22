from pathlib import Path

from src.domain.tools.tool_call import ToolCall
from src.services.tools.handlers.read_file_tool import ReadFileTool
from src.services.tools.tool_executor import ToolExecutor

from src.services.tools.tool_policy import (
    ToolPolicy,
    ToolPolicyEntry,
)

from src.services.tools.handlers.list_files_tool import (
    ListFilesTool,
)

from src.services.tools.handlers.git_diff_tool import GitDiffTool
from src.services.tools.handlers.git_status_tool import GitStatusTool

def create_executor(
    repository_root: Path,
    *,
    enabled_tools: set[str] | None = None,
    max_output_chars: int = 1000,
) -> ToolExecutor:
    enabled = enabled_tools or {"read_file"}

    tool_policy = ToolPolicy(
        default="deny",
        tools={
            tool_name: ToolPolicyEntry(enabled=True)
            for tool_name in enabled
        },
    )

    return ToolExecutor(
        repository_root=repository_root,
        handlers=[
            ReadFileTool(),
            ListFilesTool(),
            GitStatusTool(),
            GitDiffTool(),
        ],
        tool_policy=tool_policy,
        max_output_chars=max_output_chars,
    )


def test_executes_registered_enabled_tool(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    target_file = repository_root / "example.txt"
    target_file.write_text(
        "alpha\nbeta",
        encoding="utf-8",
    )

    executor = create_executor(repository_root)

    result = executor.execute(
        ToolCall(
            id="tool-call-1",
            name="read_file",
            input={"path": "example.txt"},
        )
    )

    assert result.success is True
    assert result.output == "1: alpha\n2: beta"


def test_execute_records_duration_ms_for_every_result(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    target_file = repository_root / "example.txt"
    target_file.write_text("alpha", encoding="utf-8")

    executor = create_executor(repository_root)

    success_result = executor.execute(
        ToolCall(
            id="tool-call-1",
            name="read_file",
            input={"path": "example.txt"},
        )
    )

    assert isinstance(success_result.metadata["duration_ms"], int)
    assert success_result.metadata["duration_ms"] >= 0
    # existing handler metadata (e.g. truncated) is preserved alongside it
    assert "truncated" in success_result.metadata

    failure_result = executor.execute(
        ToolCall(
            id="tool-call-2",
            name="unknown_tool",
            input={},
        )
    )

    assert isinstance(failure_result.metadata["duration_ms"], int)


def test_unknown_tool_returns_failure(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    executor = create_executor(repository_root)

    result = executor.execute(
        ToolCall(
            id="tool-call-2",
            name="unknown_tool",
            input={},
        )
    )

    assert result.success is False
    assert result.error_code == "UNKNOWN_TOOL"


def test_disabled_tool_returns_failure(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    executor = create_executor(
        repository_root,
        enabled_tools={"other_tool"},
    )

    result = executor.execute(
        ToolCall(
            id="tool-call-3",
            name="read_file",
            input={"path": "example.txt"},
        )
    )

    assert result.success is False
    assert result.error_code == "TOOL_DISABLED"


def test_invalid_input_returns_failure(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    executor = create_executor(repository_root)

    result = executor.execute(
        ToolCall(
            id="tool-call-4",
            name="read_file",
            input={},
        )
    )

    assert result.success is False
    assert result.error_code == "INVALID_TOOL_INPUT"


def test_path_escape_returns_failure(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    outside_file = tmp_path / "secret.txt"
    outside_file.write_text(
        "secret",
        encoding="utf-8",
    )

    executor = create_executor(repository_root)

    result = executor.execute(
        ToolCall(
            id="tool-call-5",
            name="read_file",
            input={"path": "../secret.txt"},
        )
    )

    assert result.success is False
    assert result.error_code == "PATH_OUTSIDE_REPOSITORY"


def test_get_definitions_returns_only_enabled_tools(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    executor = create_executor(repository_root)

    definitions = executor.get_definitions()

    assert len(definitions) == 1
    assert definitions[0].name == "read_file"


def test_duplicate_tool_registration_is_rejected(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    try:
        ToolExecutor(
            repository_root=repository_root,
            handlers=[
                ReadFileTool(),
                ReadFileTool(),
                ListFilesTool(),
                GitStatusTool(),
                GitDiffTool(),
            ],
            tool_policy=ToolPolicy(
                default="deny",
                tools={
                    "read_file": ToolPolicyEntry(enabled=True),
                    "list_files": ToolPolicyEntry(enabled=True),
                    "git_status": ToolPolicyEntry(enabled=True),
                    "git_diff": ToolPolicyEntry(enabled=True),
                },
            ),
        )
    except ValueError as error:
        assert "Duplicate tool registration" in str(error)
    else:
        raise AssertionError(
            "Expected duplicate registration to fail."
        )


def test_executes_list_files_tool(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    (repository_root / "example.txt").write_text(
        "hello",
        encoding="utf-8",
    )

    executor = create_executor(
        repository_root,
        enabled_tools={
            "read_file",
            "list_files",
        },
    )

    result = executor.execute(
        ToolCall(
            id="tool-call-list-1",
            name="list_files",
            input={},
        )
    )

    assert result.success is True
    assert result.output == "example.txt"


def test_executes_git_status_tool(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    import subprocess

    subprocess.run(
        ["git", "init"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    )

    executor = create_executor(
        repository_root,
        enabled_tools={
            "read_file",
            "list_files",
            "git_status",
            "git_diff",
        },
    )

    result = executor.execute(
        ToolCall(
            id="tool-call-git-status",
            name="git_status",
            input={},
        )
    )

    assert result.success is True
    assert result.tool_name == "git_status"