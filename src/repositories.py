import json
import os
import uuid
from pathlib import Path
from typing import Any

from src.models import AgentDefinition, RunDefinition, TaskDefinition

class JsonRepository:
    """Read and write JSON documents from the local filesystem."""

    @staticmethod
    def create_exclusive(file_path: Path, data: dict[str, Any]) -> bool:
        """Atomically create file_path with data if and only if it does
        not already exist (5E-5D-6B) - the one primitive save() cannot
        provide: save() is always a create-or-overwrite (tmp file then
        os.replace()), which makes it unsuitable for claim acquisition,
        where two processes racing to create the same path must never
        both succeed.

        Built on os.open(path, O_CREAT | O_EXCL), not
        file_path.exists() followed by a plain save() - an
        exists()-then-write check-then-act has a race window between
        the check and the write that two concurrent processes can both
        pass through; O_EXCL makes "does this path already have a
        file" and "create it" a single atomic kernel syscall, so
        exactly one of two simultaneous callers can ever win.

        Returns True if this call created the file (the caller is the
        new, sole owner of whatever claim this file represents),
        False if a file already existed at that path (left completely
        untouched - this function never overwrites, truncates, or
        inspects an existing file's contents).

        This guarantees safety against *process-level* races on a
        POSIX filesystem (two processes, or two threads, calling this
        concurrently for the same path). It does not guarantee
        durability across power loss: the write below is not fsync'd,
        matching every other JsonRepository method in this file - "the
        process was interrupted" is covered, "the machine lost power
        mid-write" is not, for save() and create_exclusive() alike.

        A failure partway through writing content (after the exclusive
        create already succeeded) leaves a truncated or empty file in
        place rather than cleaning it up - deliberately: this function
        has no way to distinguish "a concurrent reader will never see
        this" from "a claim now exists that something else depends
        on," and silently removing a file a caller believes it just
        created would be far more dangerous than leaving a malformed
        one for a caller to detect and handle explicitly.
        """

        file_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            file_descriptor = os.open(
                str(file_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            return False

        with os.fdopen(file_descriptor, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
            file.write("\n")

        return True

    @staticmethod
    def load(file_path: Path) -> dict[str, Any]:
        if not file_path.exists():
            raise FileNotFoundError(f"JSON file not found: {file_path}")

        if not file_path.is_file():
            raise ValueError(f"JSON path is not a file: {file_path}")

        try:
            with file_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Invalid JSON in {file_path}: {error.msg}"
            ) from error

        if not isinstance(data, dict):
            raise ValueError(
                f"Expected a JSON object in {file_path}, "
                f"but received {type(data).__name__}"
            )

        return data

    @staticmethod
    def save(file_path: Path, data: dict[str, Any]) -> None:
        """Writes atomically via a tmp-file-then-replace() (so a
        reader never sees a partially-written file), where the tmp
        file's name is unique per call (pid + a random token), not a
        fixed f"{suffix}.tmp" - two processes concurrently save()-ing
        the *same* file_path (e.g. two Runs under one Task, both
        updating task.json at once - 5E-5D-6C-1) previously raced on
        that one shared tmp name: whichever process's replace() ran
        second would find the first process had already consumed
        (renamed away) the tmp file out from under it, raising
        FileNotFoundError. A unique name per call makes that race
        structurally impossible - each writer only ever touches its
        own tmp file."""

        file_path.parent.mkdir(parents=True, exist_ok=True)

        temporary_path = file_path.with_suffix(
            f"{file_path.suffix}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )

        try:
            with temporary_path.open("w", encoding="utf-8") as file:
                json.dump(
                    data,
                    file,
                    indent=2,
                    ensure_ascii=False,
                )
                file.write("\n")

            temporary_path.replace(file_path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise


class TextRepository:
    """Read and write UTF-8 text documents."""

    @staticmethod
    def read(file_path: Path) -> str:
        if not file_path.exists():
            raise FileNotFoundError(f"Text file not found: {file_path}")

        if not file_path.is_file():
            raise ValueError(f"Text path is not a file: {file_path}")

        return file_path.read_text(encoding="utf-8")

    @staticmethod
    def write(file_path: Path, content: str) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")


class TaskRepository:
    """Access task metadata and task-level files."""

    def __init__(self, tasks_dir: Path) -> None:
        self._tasks_dir = tasks_dir

    def get_task_dir(self, task_id: str) -> Path:
        return self._tasks_dir / task_id

    def get_task_file(self, task_id: str) -> Path:
        return self.get_task_dir(task_id) / "task.json"

    def get_background_file(self, task_id: str) -> Path:
        return self.get_task_dir(task_id) / "background.md"

    def load(self, task_id: str) -> TaskDefinition:
        data = JsonRepository.load(self.get_task_file(task_id))
        return TaskDefinition.from_dict(data)

    def save(self, task: TaskDefinition) -> None:
        JsonRepository.save(
            self.get_task_file(task.id),
            task.to_dict(),
        )

    def list_all(self) -> list[TaskDefinition]:
        if not self._tasks_dir.exists():
            return []

        tasks: list[TaskDefinition] = []

        for task_dir in sorted(self._tasks_dir.iterdir()):
            if not task_dir.is_dir():
                continue

            task_file = task_dir / "task.json"

            if not task_file.exists():
                continue

            data = JsonRepository.load(task_file)
            tasks.append(TaskDefinition.from_dict(data))

        return tasks


class RunRepository:
    """Access run metadata and run-level files."""

    def __init__(self, tasks_dir: Path) -> None:
        self._tasks_dir = tasks_dir

    def get_run_dir(self, task_id: str, run_id: str) -> Path:
        return self._tasks_dir / task_id / "runs" / run_id

    def get_run_file(self, task_id: str, run_id: str) -> Path:
        return self.get_run_dir(task_id, run_id) / "run.json"

    def get_input_file(self, task_id: str, run_id: str) -> Path:
        return self.get_run_dir(task_id, run_id) / "input.md"

    def get_output_file(self, task_id: str, run_id: str) -> Path:
        return self.get_run_dir(task_id, run_id) / "output.md"

    def get_summary_file(self, task_id: str, run_id: str) -> Path:
        return self.get_run_dir(task_id, run_id) / "summary.md"

    def get_events_file(self, task_id: str, run_id: str) -> Path:
        return self.get_run_dir(task_id, run_id) / "events.jsonl"

    def load(
        self,
        task_id: str,
        run_id: str,
    ) -> RunDefinition:
        data = JsonRepository.load(
            self.get_run_file(task_id, run_id)
        )
        return RunDefinition.from_dict(data)

    def save(self, run: RunDefinition) -> None:
        JsonRepository.save(
            self.get_run_file(run.task_id, run.id),
            run.to_dict(),
        )

    def read_input(self, task_id: str, run_id: str) -> str:
        return TextRepository.read(
            self.get_input_file(task_id, run_id)
        )

    def write_input(
        self,
        task_id: str,
        run_id: str,
        content: str,
    ) -> None:
        TextRepository.write(
            self.get_input_file(task_id, run_id),
            content,
        )

    def list_run_ids(self, task_id: str) -> list[str]:
        runs_dir = self._tasks_dir / task_id / "runs"

        if not runs_dir.exists():
            return []

        return sorted(
            entry.name
            for entry in runs_dir.iterdir()
            if entry.is_dir()
        )

    def write_output(
        self,
        task_id: str,
        run_id: str,
        content: str,
    ) -> None:
        TextRepository.write(
            self.get_output_file(task_id, run_id),
            content,
        )

    def write_summary(
        self,
        task_id: str,
        run_id: str,
        content: str,
    ) -> None:
        TextRepository.write(
            self.get_summary_file(task_id, run_id),
            content,
        )


class AgentRepository:
    """Access agent definitions and agent-owned configuration files."""

    def __init__(self, agents_dir: Path) -> None:
        self._agents_dir = agents_dir

    def get_agent_dir(self, agent_id: str) -> Path:
        return self._agents_dir / agent_id

    def get_agent_file(self, agent_id: str) -> Path:
        return self.get_agent_dir(agent_id) / "agent.json"

    def get_system_prompt_file(self, agent_id: str) -> Path:
        agent = self.load(agent_id)
        relative_path = agent.system_prompt_path

        return self.get_agent_dir(agent_id) / relative_path

    def get_tool_policy_file(self, agent_id: str) -> Path:
        agent = self.load(agent_id)
        relative_path = agent.tool_policy_path

        return self.get_agent_dir(agent_id) / relative_path

    def load(self, agent_id: str) -> AgentDefinition:
        data = JsonRepository.load(
            self.get_agent_file(agent_id)
        )
        return AgentDefinition.from_dict(data)

    def list_all(self) -> list[AgentDefinition]:
        if not self._agents_dir.exists():
            return []

        agents: list[AgentDefinition] = []

        for agent_dir in sorted(self._agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue

            agent_file = agent_dir / "agent.json"

            if not agent_file.exists():
                continue

            data = JsonRepository.load(agent_file)
            agents.append(AgentDefinition.from_dict(data))

        return agents

    def read_system_prompt(self, agent_id: str) -> str:
        return TextRepository.read(
            self.get_system_prompt_file(agent_id)
        )

    def load_tool_policy(self, agent_id: str) -> dict[str, Any]:
        return JsonRepository.load(
            self.get_tool_policy_file(agent_id)
        )
