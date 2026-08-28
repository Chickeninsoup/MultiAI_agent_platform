import argparse
from pathlib import Path

from src.agent_registry import AgentRegistry
from src.agent_runtime_factory import AgentRuntimeFactory
from src.agents.agent_template_repository import (
    AgentTemplateRepository,
)
from src.agents.task_agent_cleanup_service import (
    TaskAgentCleanupService,
)
from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.cli.run_display import format_run_inspection, format_run_list
from src.config.settings import Settings
from src.context_builder import RunContextBuilder
from src.domain.events.event_repository import EventRepository
from src.domain.events.timeline_builder import TimelineBuilder
from src.executor_factory import create_run_executor
from src.manager_agent import ManagerAgent
from src.planning.approval_repository import ApprovalRepository
from src.planning.persistent_approval_service import (
    PersistentApprovalService,
)
from src.planning.plan_approval_service import PlanApprovalService
from src.planning.plan_execution_service import PlanExecutionService
from src.planning.task_completion_service import TaskCompletionService
from src.planning.plan_repository import PlanRepository
from src.planning.plan_review_service import PlanReviewService
from src.planning.plan_service import PlanService
from src.planning.plan_validator import PlanValidator
from src.planning.task_planning_context_factory import (
    TaskPlanningContextFactory,
)
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
from src.task_service import TaskAlreadyExistsError, TaskService


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
task_agent_registry = TaskAgentRegistry()
agent_runtime_factory = AgentRuntimeFactory(
    agent_registry=agent_registry,
    task_agent_registry=task_agent_registry,
    task_service=task_service,
    run_service=run_service,
)

manager_agent = ManagerAgent()
agent_template_repository = AgentTemplateRepository()
task_agent_team_lifecycle = TaskAgentTeamLifecycle(task_agent_registry)
task_planning_context_factory = TaskPlanningContextFactory(
    task_agent_registry, agent_template_repository
)
plan_review_service = PlanReviewService(
    PlanValidator(agent_registry, task_agent_registry)
)
plan_approval_service = PlanApprovalService()

plan_repository = PlanRepository(TASKS_DIR)
approval_repository = ApprovalRepository(TASKS_DIR)
plan_service = PlanService(
    plan_review_service,
    plan_repository,
    manager_agent,
    task_planning_context_factory,
    task_agent_team_lifecycle,
)
persistent_approval_service = PersistentApprovalService(
    approval_repository, plan_approval_service
)
plan_execution_service = PlanExecutionService(
    plan_repository,
    approval_repository,
    plan_review_service,
    agent_runtime_factory,
    task_agent_registry,
    TaskDependencyResolver(),
    TaskPlanConverter(),
)
task_completion_service = TaskCompletionService(task_repository)
task_agent_cleanup_service = TaskAgentCleanupService(
    task_repository, task_agent_registry, task_agent_team_lifecycle
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


def init_task(
    task_id: str,
    agent_id: str,
    title: str,
    *,
    description: str | None,
    input_text: str | None,
    created_by: str,
    workspace_id: str,
    priority: str,
    tags: list[str],
) -> None:
    task, run = task_service.create_task_and_run(
        task_id=task_id,
        title=title,
        description=description or title,
        agent_id=agent_id,
        input_text=input_text or title,
        created_by=created_by,
        workspace_id=workspace_id,
        priority=priority,
        tags=tags,
    )

    print(f"Task created: {task.id}")
    print(f"Run created:  {run.id}")
    print()
    print(f"Run with: python -m src.main run {task.id}")


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


_PLAN_STATUS_LABELS = {"pending": "PENDING_APPROVAL"}


def _format_plan_status(status: str) -> str:
    return _PLAN_STATUS_LABELS.get(status, status.upper())


def plan_task(task_id: str, request: str) -> None:
    record = plan_service.create_plan(task_id, request)
    review = plan_service.create_review(record.plan)

    print(review.summary)
    print()
    print("Plan created.")
    print()
    print(f"Task: {record.task_id}")
    print(f"Status: {_format_plan_status(record.status)}")
    print()
    print(f"Use: approve-plan {record.task_id}")
    print(f"Or:  reject-plan {record.task_id}")


def list_pending_plans() -> None:
    records = plan_service.get_pending_plans()

    if not records:
        print("No pending plans.")
        return

    for record in records:
        step_count = len(record.plan.steps)
        summary = (
            record.plan.steps[0].description
            if record.plan.steps
            else "(no steps)"
        )

        print(record.task_id)
        print(summary)
        print(f"{step_count} step(s)")
        print(record.status)
        print()


def approve_plan(task_id: str) -> None:
    record = plan_service.get_plan(task_id)

    if record is None:
        print(f"No plan found for task: {task_id}")
        return

    review = plan_service.create_review(record.plan)
    persistent_approval_service.approve_and_save(review)
    plan_service.update_status(task_id, "approved")

    print(f"Plan approved: {task_id}")
    print()
    print("Execution started.")
    print()

    execution_result = plan_execution_service.execute(task_id)

    _print_step_results(execution_result.step_results)

    task_completed = task_completion_service.complete_if_successful(
        task_id, execution_result
    )

    if task_completed:
        task_agent_cleanup_service.cleanup(task_id)

    plan_service.update_status(task_id, "executed")


def reject_plan(task_id: str) -> None:
    record = plan_service.get_plan(task_id)

    if record is None:
        print(f"No plan found for task: {task_id}")
        return

    review = plan_service.create_review(record.plan)
    persistent_approval_service.reject_and_save(review)
    plan_service.update_status(task_id, "rejected")

    print(f"Plan rejected: {task_id}")


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

    init_task_parser = subparsers.add_parser(
        "init-task",
        help=(
            "Create a new Task and its first Run (run-001) without "
            "executing it. Use 'run' to execute it afterward."
        ),
    )

    init_task_parser.add_argument(
        "task_id",
        help="Task ID to create, for example task-20260821-001.",
    )

    init_task_parser.add_argument(
        "agent_id",
        help="Agent ID to assign the task and its first run to.",
    )

    init_task_parser.add_argument(
        "title",
        help="Short task title.",
    )

    init_task_parser.add_argument(
        "--description",
        default=None,
        help="Task description. Defaults to the title.",
    )

    init_task_parser.add_argument(
        "--input",
        dest="input_text",
        default=None,
        help="Input text for the first run. Defaults to the title.",
    )

    init_task_parser.add_argument(
        "--created-by",
        default="cli",
        help="Creator identifier recorded on the task. Defaults to 'cli'.",
    )

    init_task_parser.add_argument(
        "--workspace-id",
        default="workspace-main",
        help="Workspace ID. Defaults to 'workspace-main'.",
    )

    init_task_parser.add_argument(
        "--priority",
        default="normal",
        help="Task priority. Defaults to 'normal'.",
    )

    init_task_parser.add_argument(
        "--tags",
        default="",
        help="Comma-separated tags, for example 'bug,urgent'.",
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
            "Generate a TaskPlan for a request and save it as "
            "pending approval. Does not execute - use approve-plan."
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

    subparsers.add_parser(
        "plans",
        help="List all plans awaiting approval.",
    )

    approve_plan_parser = subparsers.add_parser(
        "approve-plan",
        help=(
            "Approve a pending plan and execute it immediately."
        ),
    )

    approve_plan_parser.add_argument(
        "task_id",
        help="Task ID whose plan to approve, for example task-001.",
    )

    reject_plan_parser = subparsers.add_parser(
        "reject-plan",
        help="Reject a pending plan without executing it.",
    )

    reject_plan_parser.add_argument(
        "task_id",
        help="Task ID whose plan to reject, for example task-001.",
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
        elif args.command == "init-task":
            init_task(
                args.task_id,
                args.agent_id,
                args.title,
                description=args.description,
                input_text=args.input_text,
                created_by=args.created_by,
                workspace_id=args.workspace_id,
                priority=args.priority,
                tags=[tag for tag in args.tags.split(",") if tag],
            )
        elif args.command == "run":
            run_task(args.task_id)
        elif args.command == "plan":
            plan_task(args.task_id, args.request)
        elif args.command == "plans":
            list_pending_plans()
        elif args.command == "approve-plan":
            approve_plan(args.task_id)
        elif args.command == "reject-plan":
            reject_plan(args.task_id)
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
    except (
        FileNotFoundError,
        ValueError,
        KeyError,
        RuntimeError,
        TaskAlreadyExistsError,
    ) as error:
        parser.exit(
            status=1,
            message=f"Error: {error}\n",
        )


if __name__ == "__main__":
    main()
