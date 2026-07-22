import json
from pathlib import Path

from src.models import (
    AgentDefinition,
    RunDefinition,
    RunExecutionContext,
    TaskDefinition,
)
from src.repositories import (
    AgentRepository,
    RunRepository,
    TaskRepository,
    TextRepository,
)

DEFAULT_CONTEXT_FILES = (
    "src/main.py",
    "src/models.py",
    "src/repositories.py",
    "src/run_service.py",
    "src/execution.py",
)


EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

EXCLUDED_FILE_NAMES = {
    ".env",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
}


class RunContextBuilder:
    """Build deterministic, read-only context for one run."""

    def __init__(
        self,
        project_root: Path,
        task_repository: TaskRepository,
        run_repository: RunRepository,
        agent_repository: AgentRepository,
        *,
        context_files: tuple[str, ...] = DEFAULT_CONTEXT_FILES,
        tree_max_depth: int = 3,
        max_file_characters: int = 20_000,
        max_snapshot_characters: int = 120_000,
    ) -> None:
        if tree_max_depth <= 0:
            raise ValueError(
                "Tree maximum depth must be positive"
            )

        if max_file_characters <= 0:
            raise ValueError(
                "Maximum file characters must be positive"
            )

        if max_snapshot_characters <= 0:
            raise ValueError(
                "Maximum snapshot characters must be positive"
            )

        self._project_root = project_root
        self._task_repository = task_repository
        self._run_repository = run_repository
        self._agent_repository = agent_repository
        self._context_files = context_files
        self._tree_max_depth = tree_max_depth
        self._max_file_characters = max_file_characters
        self._max_snapshot_characters = (
            max_snapshot_characters
        )

    def build(
        self,
        task: TaskDefinition,
        run: RunDefinition,
        agent: AgentDefinition,
    ) -> RunExecutionContext:
        run_input = self._run_repository.read_input(
            task.id,
            run.id,
        )

        agent_system_prompt = (
            self._agent_repository.read_system_prompt(
                agent.id
            )
        )

        tool_policy = (
            self._agent_repository.load_tool_policy(
                agent.id
            )
        )

        task_background = self._read_task_background(
            task.id
        )


        context_files = self._resolve_context_files(run)

        project_snapshot = self._build_project_snapshot(
            context_files
        )

        return RunExecutionContext(
            task=task,
            run=run,
            agent=agent,
            run_input=run_input,
            agent_system_prompt=agent_system_prompt,
            task_background=task_background,
            tool_policy=tool_policy,
            project_snapshot=project_snapshot,
        )

    def _read_task_background(self, task_id: str) -> str:
        background_file = (
            self._task_repository.get_background_file(
                task_id
            )
        )

        if not background_file.exists():
            return ""

        return TextRepository.read(background_file)

    def _resolve_context_files(
        self,
        run: RunDefinition,
    ) -> tuple[str, ...]:
        raw_context_files = run.metadata.get(
            "context_files"
        )

        if raw_context_files is None:
            return self._context_files

        if not isinstance(raw_context_files, list):
            raise ValueError(
                "Run metadata context_files must be a list"
            )

        resolved_files: list[str] = []

        for item in raw_context_files:
            if not isinstance(item, str):
                raise ValueError(
                    "Every context_files item must be "
                    "a string"
                )

            normalized_path = item.strip()

            if not normalized_path:
                raise ValueError(
                    "Context file path must not be empty"
                )

            self._validate_context_path(
                normalized_path
            )

            if normalized_path not in resolved_files:
                resolved_files.append(normalized_path)

        if not resolved_files:
            raise ValueError(
                "context_files must contain at least "
                "one file"
            )

        return tuple(resolved_files)

    def _validate_context_path(
        self,
        relative_path: str,
    ) -> None:
        path = Path(relative_path)

        if path.is_absolute():
            raise ValueError(
                f"Context path must be relative: "
                f"{relative_path}"
            )

        if ".." in path.parts:
            raise ValueError(
                f"Context path may not escape the "
                f"project root: {relative_path}"
            )

        if self._is_excluded(path):
            raise ValueError(
                f"Context path is excluded: "
                f"{relative_path}"
            )

        resolved_path = (
            self._project_root / path
        ).resolve()

        try:
            resolved_path.relative_to(
                self._project_root.resolve()
            )
        except ValueError as error:
            raise ValueError(
                f"Context path escapes project root: "
                f"{relative_path}"
            ) from error

    def _build_project_snapshot(
        self,
        context_files: tuple[str, ...],
    ) -> str:
        sections = [
            "# Project Snapshot",
            "",
            "## Snapshot Policy",
            "",
            f"- Selected files: {len(context_files)}",
            (
                "- Maximum characters per file: "
                f"{self._max_file_characters}"
            ),
            (
                "- Maximum snapshot characters: "
                f"{self._max_snapshot_characters}"
            ),
            "",
            "## Selected Context Files",
            "",
            *(
                f"- `{relative_path}`"
                for relative_path in context_files
            ),
            "",
            "## Project Tree",
            "",
            "```text",
            self._build_project_tree(),
            "```",
        ]

        current_length = sum(
            len(section) for section in sections
        )

        for relative_path in context_files:
            if (
                current_length
                >= self._max_snapshot_characters
            ):
                break

            section = self._build_file_section(
                relative_path
            )

            remaining_characters = (
                self._max_snapshot_characters
                - current_length
            )

            if len(section) > remaining_characters:
                truncation_notice = (
                    "\n\n[Snapshot truncated because "
                    "the total context budget was "
                    "reached]"
                )

                allowed_length = max(
                    0,
                    remaining_characters
                    - len(truncation_notice),
                )

                section = (
                    section[:allowed_length]
                    + truncation_notice
                )

            sections.extend(
                [
                    "",
                    section,
                ]
            )

            current_length += len(section)

        return "\n".join(sections)

    def _build_project_tree(self) -> str:
        entries: list[str] = []

        for path in sorted(self._project_root.rglob("*")):
            relative_path = path.relative_to(
                self._project_root
            )

            if self._is_excluded(relative_path):
                continue

            if len(relative_path.parts) > self._tree_max_depth:
                continue

            indentation = "  " * (
                len(relative_path.parts) - 1
            )

            display_name = relative_path.name

            if path.is_dir():
                display_name += "/"

            entries.append(
                f"{indentation}{display_name}"
            )

        return "\n".join(entries)

    def _build_file_section(
        self,
        relative_path: str,
    ) -> str:
        file_path = self._project_root / relative_path

        if not file_path.exists():
            return (
                f"## File: `{relative_path}`\n\n"
                "_File does not exist._"
            )

        if not file_path.is_file():
            return (
                f"## File: `{relative_path}`\n\n"
                "_Path is not a regular file._"
            )

        content = TextRepository.read(file_path)

        if len(content) > self._max_file_characters:
            content = (
                content[:self._max_file_characters]
                + "\n\n[File truncated by context builder]"
            )

        return (
            f"## File: `{relative_path}`\n\n"
            "```text\n"
            f"{content.rstrip()}\n"
            "```"
        )

    @staticmethod
    def format_tool_policy(
        tool_policy: dict[str, object],
    ) -> str:
        return json.dumps(
            tool_policy,
            indent=2,
            ensure_ascii=False,
        )

    @staticmethod
    def _is_excluded(relative_path: Path) -> bool:
        if relative_path.name in EXCLUDED_FILE_NAMES:
            return True

        if relative_path.suffix in EXCLUDED_SUFFIXES:
            return True

        return any(
            part in EXCLUDED_DIRECTORY_NAMES
            for part in relative_path.parts
        )

