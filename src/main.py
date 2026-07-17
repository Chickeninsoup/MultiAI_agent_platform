import argparse
from pathlib import Path

from src.config.settings import Settings
from src.context_builder import RunContextBuilder
from src.executor_factory import create_run_executor
from src.repositories import (
    AgentRepository,
    RunRepository,
    TaskRepository,
)
from src.run_service import RunService


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = PROJECT_ROOT / "tasks"
AGENTS_DIR = PROJECT_ROOT / "agents"
ENV_FILE = PROJECT_ROOT / ".env"

settings = Settings.load(ENV_FILE)

task_repository = TaskRepository(TASKS_DIR)
run_repository = RunRepository(TASKS_DIR)
agent_repository = AgentRepository(AGENTS_DIR)

context_builder = RunContextBuilder(
    project_root=PROJECT_ROOT,
    task_repository=task_repository,
    run_repository=run_repository,
    agent_repository=agent_repository,
)

executor = create_run_executor(settings)

run_service = RunService(
    task_repository=task_repository,
    run_repository=run_repository,
    agent_repository=agent_repository,
    context_builder=context_builder,
    executor=executor,
)


def list_tasks() -> None:
    tasks = task_repository.list_all()

    if not tasks:
        print("No tasks found.")
        return

    for task in tasks:
        print(
            f"{task.id} | "
            f"{task.status} | "
            f"{task.current_run_id or '-'} | "
            f"{task.title}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Manage tasks and runs in the AI agent platform."
        )
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    subparsers.add_parser(
        "list",
        help="List all tasks.",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Execute the current run for a task.",
    )

    run_parser.add_argument(
        "task_id",
        help="Task ID, for example task-20260713-001.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "list":
            list_tasks()
        elif args.command == "run":
            run_service.execute(args.task_id)
    except (FileNotFoundError, ValueError, KeyError, RuntimeError) as error:
        parser.exit(
            status=1,
            message=f"Error: {error}\n",
        )


if __name__ == "__main__":
    main()
