import argparse
from pathlib import Path

from src.agent_registry import AgentRegistry
from src.agent_runtime_factory import AgentRuntimeFactory
from src.cli.run_display import format_run_inspection, format_run_list
from src.config.settings import Settings
from src.context_builder import RunContextBuilder
from src.domain.events.event_repository import EventRepository
from src.domain.events.timeline_builder import TimelineBuilder
from src.executor_factory import create_run_executor
from src.manager_agent import ManagerAgent
from src.message_router import MessageRouter
from src.planning.approved_plan_executor import ApprovedPlanExecutor
from src.planning.plan_approval_service import PlanApprovalService
from src.planning.plan_review_service import PlanReviewService
from src.planning.plan_validator import PlanValidator
from src.repositories import (
    AgentRepository,
    RunRepository,
    TaskRepository,
)
from src.review.review_service import ReviewService
from src.review.snapshot_repository import (
    SnapshotNotFoundError,
    SnapshotRepository,
)
from src.run_query_service import RunQueryService
from src.run_service import RunExecutionFailedError, RunService
from src.step_execution_result import StepExecutionResult
from src.task_dependency_resolver import TaskDependencyResolver
from src.task_plan_converter import TaskPlanConverter
from src.task_plan_executor import TaskPlanExecutor
from src.task_scheduler import TaskScheduler
from src.task_service import TaskService


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

executor = create_run_executor(
    settings=settings,
    agent_repository=agent_repository,
    run_repository=run_repository,
    project_root=PROJECT_ROOT,
)

run_service = RunService(
    task_repository=task_repository,
    run_repository=run_repository,
    agent_repository=agent_repository,
    context_builder=context_builder,
    executor=executor,
    project_root=PROJECT_ROOT,
)

snapshot_repository = SnapshotRepository()
review_service = ReviewService()

run_query_service = RunQueryService(
    task_repository=task_repository,
    run_repository=run_repository,
    event_repository=EventRepository(),
    snapshot_repository=snapshot_repository,
    timeline_builder=TimelineBuilder(),
)

agent_registry = AgentRegistry(agent_repository)
task_service = TaskService(
    task_repository=task_repository,
    run_repository=run_repository,
)
agent_runtime_factory = AgentRuntimeFactory(
    agent_registry=agent_registry,
    task_service=task_service,
    run_service=run_service,
)

manager_agent = ManagerAgent()
plan_review_service = PlanReviewService(PlanValidator(agent_registry))
plan_approval_service = PlanApprovalService()
approved_plan_executor = ApprovedPlanExecutor(
    TaskScheduler(
        TaskDependencyResolver(),
        TaskPlanExecutor(
            TaskPlanConverter(),
            MessageRouter(agent_runtime_factory.create_handlers()),
        ),
    )
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


def _print_run_result(result) -> None:
    if result.status == "completed":
        print(f"Completed run: {result.run_id}")
    else:
        print(f"Run {result.run_id}: {result.status}")

    print(f"Output:  {result.output_path}")
    print(f"Summary: {result.summary_path}")

    if result.events_path.exists():
        print(f"Events:  {result.events_path}")

    if result.llm_rounds is not None:
        print(
            f"Usage: {result.total_input_tokens} input / "
            f"{result.total_output_tokens} output tokens, "
            f"{result.llm_rounds} LLM round(s), "
            f"{result.tool_rounds} tool round(s), "
            f"{result.tool_calls} tool call(s)"
        )


def run_task(task_id: str) -> None:
    _print_run_result(run_service.execute(task_id))


def resume_run(run_id: str) -> None:
    _print_run_result(run_service.resume(run_id))


def review_run(run_id: str) -> None:
    task, run = run_service.get_run(run_id)

    print(f"Run: {run_id}")
    print()
    print("Status:")
    print(run.status)
    print()

    run_directory = run_repository.get_run_dir(task.id, run.id)

    try:
        snapshot = snapshot_repository.load(run_directory)
    except SnapshotNotFoundError:
        print("No change snapshot recorded for this run.")
        return

    approved = {"approved": True, "rejected": False}.get(run.status)
    report = review_service.build_report(
        snapshot=snapshot,
        approved=approved,
    )

    print("Changed files:")
    if report.changed_files:
        for path in report.changed_files:
            print(f"- {path}")
    else:
        print("(none)")
    print()

    print("Mutations:")
    print(snapshot.mutation_count)
    print()

    print("Tests:")
    if snapshot.test_results:
        for test_name, test_result in snapshot.test_results.items():
            print(f"{test_name}:")
            for key, value in test_result.items():
                print(f"  {key}: {value}")
    else:
        print("(none)")
    print()

    print("Diff:")
    if snapshot.diff_path:
        print(Path(snapshot.diff_path).read_text(encoding="utf-8"))
    else:
        print("(no diff recorded)")
    print()

    print("AI Summary:")
    print(report.summary or "Not generated yet.")

    if run.status != "awaiting_review":
        return

    print()
    answer = input("Approve? [y/N]: ").strip().lower()

    if answer in {"y", "yes"}:
        run_service.decide_review(run_id, approved=True)
        print("Approved.")
    elif answer in {"n", "no", "reject"}:
        run_service.decide_review(run_id, approved=False)
        print("Rejected.")
    else:
        print("No decision made. Run remains awaiting_review.")


def _print_step_results(results: list[StepExecutionResult]) -> None:
    print("Results:")
    for result in results:
        print(f"- {result.step_id}: {result.status.value.upper()}")
        if result.output is not None:
            print(f"  Output: {result.output}")
        if result.error is not None:
            print(f"  Error: {result.error}")


def plan_task(task_id: str, request: str) -> None:
    plan = manager_agent.plan(request, task_id=task_id)
    review = plan_review_service.create_review(plan)

    print(review.summary)
    print()

    if review.validation.valid:
        prompt = "Approve? [y/N]: "
    else:
        prompt = "Validation FAILED. Override and execute anyway? [y/N]: "

    answer = input(prompt).strip().lower()

    if answer in {"y", "yes"}:
        approval = plan_approval_service.approve(review)
        results = approved_plan_executor.execute(approval)
        print()
        _print_step_results(results)
    else:
        plan_approval_service.reject(review)
        print("Plan rejected.")


def list_runs() -> None:
    print(format_run_list(run_query_service.list_runs()))


def inspect_run(run_id: str) -> None:
    print(format_run_inspection(run_query_service.inspect_run(run_id)))


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

    plan_parser = subparsers.add_parser(
        "plan",
        help=(
            "Generate a TaskPlan for a request, show it for approval, "
            "and execute it once approved."
        ),
    )

    plan_parser.add_argument(
        "task_id",
        help="Task ID to create, for example task-20260812-001.",
    )

    plan_parser.add_argument(
        "request",
        help="Natural-language description of the work to plan.",
    )

    resume_parser = subparsers.add_parser(
        "resume",
        help=(
            "Retry a run that never reached a terminal state, as a "
            "new run."
        ),
    )

    resume_parser.add_argument(
        "run_id",
        help="Run ID to resume, for example run-023.",
    )

    review_parser = subparsers.add_parser(
        "review",
        help=(
            "View a run's recorded changes/test results and, if it "
            "is awaiting_review, approve or reject it."
        ),
    )

    review_parser.add_argument(
        "run_id",
        help="Run ID to review, for example run-030.",
    )

    subparsers.add_parser(
        "runs",
        help="List all runs across all tasks.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Show a run's timeline, changed files, and test results.",
    )

    inspect_parser.add_argument(
        "run_id",
        help="Run ID to inspect, for example run-030.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "list":
            list_tasks()
        elif args.command == "run":
            run_task(args.task_id)
        elif args.command == "plan":
            plan_task(args.task_id, args.request)
        elif args.command == "resume":
            resume_run(args.run_id)
        elif args.command == "review":
            review_run(args.run_id)
        elif args.command == "runs":
            list_runs()
        elif args.command == "inspect":
            inspect_run(args.run_id)
    except RunExecutionFailedError as error:
        print(f"Run failed: {error.run_id}")
        print(f"Status: {error.status}")
        print(f"Category: {error.category} (retryable: {error.retryable})")
        print(f"Error: {error.original_error}")

        if error.events_path.exists():
            print()
            print("Events preserved:")
            print(f"  {error.events_path}")

        if error.retryable:
            print()
            print(f"Retry with: python -m src.main resume {error.run_id}")

        parser.exit(status=1)
    except (FileNotFoundError, ValueError, KeyError, RuntimeError) as error:
        parser.exit(
            status=1,
            message=f"Error: {error}\n",
        )


if __name__ == "__main__":
    main()
