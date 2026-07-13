import json
import argparse

from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = PROJECT_ROOT / "tasks"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def load_json(file_path: Path) -> dict:
    with file_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(file_path: Path, data: dict) -> None:
    with file_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def execute_run(task_id: str) -> None:
    task_dir = TASKS_DIR / task_id
    task_file = task_dir / "task.json"

    if not task_file.exists():
        raise FileNotFoundError(f"Task file not found: {task_file}")

    task = load_json(task_file)
    run_id = task.get("current_run_id")

    if not run_id:
        raise ValueError(f"Task {task_id} has no current_run_id")

    run_dir = task_dir / "runs" / run_id
    run_file = run_dir / "run.json"
   
    input_file = run_dir / "input.md"
    output_file = run_dir / "output.md"
    summary_file = run_dir / "summary-placeholder.md"

    if not run_file.exists():
        raise FileNotFoundError(f"Run file not found: {run_file}")

    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    run = load_json(run_file)

    if run.get("status") == "completed":
   	 raise ValueError(f"Run {run_id} has already been completed")

    run_input = input_file.read_text(encoding="utf-8")

    output = (
        "# Run Output\n\n"
        f"Run `{run_id}` completed successfully.\n\n"
        f"Agent: `{run['agent_id']}`\n\n"
        "## Input Received\n\n"
        f"{run_input}\n"
    )

    output_file.write_text(output, encoding="utf-8")
    summary = (
   	 "# Run Summary\n\n"
   	 f"- Run ID: `{run_id}`\n"
  	 f"- Agent ID: `{run['agent_id']}`\n"
   	 "- Status: `completed`\n"
   	 "- Summary: The initial task execution workflow completed successfully.\n"
   	 "- Important findings: Task and Run metadata can be read and updated.\n"
   	 "- Decisions made: Continue using file-based JSON metadata for the prototype.\n"
   	 "- Remaining work: Append this summary to the Task background.\n"
	)

    summary_file.write_text(summary, encoding="utf-8")

    completed_at = utc_now()

    run["status"] = "completed"
    run["updated_at"] = completed_at
    run["completed_at"] = completed_at
    save_json(run_file, run)

    task["updated_at"] = completed_at
    save_json(task_file, task)

    print(f"Completed run: {run_id}")
    print(f"Output written to: {output_file}")


def list_tasks() -> None:
    if not TASKS_DIR.exists():
        print("No tasks directory found.")
        return

    task_directories = sorted(
        path
        for path in TASKS_DIR.iterdir()
        if path.is_dir()
    )

    if not task_directories:
        print("No tasks found.")
        return

    for task_dir in task_directories:
        task_file = task_dir / "task.json"

        if not task_file.exists():
            continue

        task = load_json(task_file)

        task_id = task.get("id", task_dir.name)
        title = task.get("title", "Untitled")
        status = task.get("status", "unknown")
        current_run_id = task.get("current_run_id")

        print(
            f"{task_id} | "
            f"{status} | "
            f"{current_run_id or '-'} | "
            f"{title}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage tasks and runs in the AI agent platform."
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
             execute_run(args.task_id)
    except (FileNotFoundError, ValueError, KeyError) as error:
        parser.exit(status=1, message=f"Error: {error}\n")


if __name__ == "__main__":
    main()
