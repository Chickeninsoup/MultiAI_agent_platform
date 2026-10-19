import argparse
import json
from pathlib import Path
from typing import Any

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
from src.approval_decision import ApprovalDecision
from src.approval_decision_errors import ApprovalRunNotFoundError
from src.approval_decision_service import ApprovalDecisionService
from src.approval_request import ApprovalRequest
from src.approval_request_repository import ApprovalRequestRepository
from src.approval_resolution import ApprovalResolution
from src.approval_resolution_repository import (
    ApprovalResolutionRepository,
)
from src.approval_status import ApprovalStatus
from src.approval_store import ApprovalStore
from src.cli.approval_display import (
    format_approval_detail,
    format_approval_list,
)
from src.cli.run_display import format_run_inspection, format_run_list
from src.config.settings import Settings
from src.context_builder import RunContextBuilder
from src.domain.events.event_repository import EventRepository
from src.domain.events.timeline_builder import TimelineBuilder
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
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)
from src.run_events import JsonlRunEventSink
from src.run_query_service import RunQueryService
from src.run_service import RunExecutionFailedError
from src.step_execution_result import StepExecutionResult
from src.task_dependency_resolver import TaskDependencyResolver
from src.task_plan_converter import TaskPlanConverter
from src.task_service import TaskAlreadyExistsError, TaskService


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = PROJECT_ROOT / "tasks"
AGENTS_DIR = PROJECT_ROOT / "agents"
ENV_FILE = PROJECT_ROOT / ".env"

settings = Settings.load(ENV_FILE)

# Mutable module-level globals (5E-5D-6D) - task_repository/
# run_repository/agent_repository are read fresh by _build_composition()
# on every relevant command call below, not captured once into a
# frozen object at import time, so tests can monkeypatch them (the
# same convention tests/test_cli_tool_approval.py already relies on
# for _build_tool_approval_decision_service()) and have every command
# pick up the swap - including run/resume/review/resume-after-approval/
# list-tool-approvals/show-tool-approval, not just decision recording.
task_repository = TaskRepository(TASKS_DIR)
run_repository = RunRepository(TASKS_DIR)
agent_repository = AgentRepository(AGENTS_DIR)


def _build_composition():
    """The one production composition root for every approval-workflow
    CLI command (5E-5D-6D) - rebuilt fresh on every call, reading
    whatever task_repository/run_repository/agent_repository/TASKS_DIR/
    settings currently are, never cached. Building this never requires
    LLM provider credentials - see executor_factory._LazyLLMProvider -
    so every command, including ones that never execute or resume
    anything, can safely call this."""

    from src.run_service_composition import build_production_composition

    context_builder = RunContextBuilder(
        project_root=PROJECT_ROOT,
        task_repository=task_repository,
        run_repository=run_repository,
        agent_repository=agent_repository,
    )

    return build_production_composition(
        settings=settings,
        project_root=PROJECT_ROOT,
        tasks_dir=TASKS_DIR,
        task_repository=task_repository,
        run_repository=run_repository,
        agent_repository=agent_repository,
        context_builder=context_builder,
    )


# A separate, import-time-only composition for the Manager-Agent/
# TaskAgent orchestration subsystem (AgentRuntimeFactory/
# LLMAgentHandler below) - unrelated to this stage's CLI approval
# workflow (5E-5D-6D scope is explicitly the CLI commands; plan-level
# RecoveryExecutor/RuntimeApprovalService/TaskAgent orchestration
# behavior stays separate, per that stage's own instructions). Kept as
# a one-time eager build, matching that subsystem's own pre-existing
# eager-composition convention, rather than threading a fresh
# per-call composition through AgentRuntimeFactory/LLMAgentHandler's
# constructor-injection shape.
_orchestration_run_service = _build_composition().run_service

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
    run_service=_orchestration_run_service,
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

    if result.status == "waiting_for_approval":
        print()
        print(f"Approval ID: {result.approval_id}")
        print(
            "This run is paused: a tool call requires human "
            "approval before execution can continue."
        )
        print()
        print("Next steps:")
        print(
            "  Inspect: python -m src.main show-tool-approval "
            f"{result.approval_id}"
        )
        print(
            "  Decide:  python -m src.main approve-tool-call "
            f"{result.approval_id}"
        )
        print(
            "           (or reject-tool-call / modify-tool-call / "
            "cancel-tool-call)"
        )
        print(
            "  Continue: python -m src.main resume-after-approval "
            f"{result.run_id} {result.approval_id}"
        )


def run_task(task_id: str) -> None:
    _print_run_result(_build_composition().run_service.execute(task_id))


def resume_run(run_id: str) -> None:
    _print_run_result(_build_composition().run_service.resume(run_id))


def review_run(run_id: str) -> None:
    run_service = _build_composition().run_service
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


def _resolve_task_id_for_run(run_id: str) -> str | None:
    # Deliberately duplicates RunService._find_task_for_run() /
    # RunQueryService._find_task_for_run() / ApprovalDecisionService.
    # _find_task_id_for_run()'s exact scan rather than depending on any
    # of them - the same "each independent caller owns this lookup"
    # convention ApprovalDecisionService's own docstring documents.
    for task in task_repository.list_all():
        if run_id in run_repository.list_run_ids(task.id):
            return task.id

    return None


def _build_tool_approval_decision_service(
    approval_id: str,
) -> tuple[ApprovalDecisionService, ApprovalRequest, bool]:
    """Construct one ApprovalDecisionService for this approval_id, and
    report whether doing so required reading Task/Run/checkpoint state
    (the returned bool) - callers use that to avoid printing a Run
    status this call never actually checked.

    ApprovalDecisionService.resolve() (5E-5D-5A-1) already handles a
    RESOLVED request entirely off ApprovalStore's own projection,
    before touching Task, Run, or the continuation checkpoint at all -
    identical retries return the original resolution, conflicting
    ones raise, and neither path persists or emits anything. This
    composition must not reintroduce a Task/Run dependency the service
    deliberately removed: eagerly resolving run_id -> task_id (needed
    only to route a *new* event) for every call, including replays of
    an already-decided approval, would make a replay fail the moment
    the originating Run/Task became undiscoverable - even though the
    service itself would have handled that replay just fine.

    So the branch here mirrors the service's own PENDING/RESOLVED
    split, not a new policy of its own:

    - RESOLVED: resolve() will only ever read ApprovalStore's existing
      projection (return the original resolution, or raise
      ApprovalAlreadyResolvedError) - never call event_sink.emit(),
      never touch task_repository/run_repository/checkpoint_repository.
      A NullRunEventSink is safe here specifically *because* nothing
      on this path ever reaches it - not a general relaxation of "real
      composition never uses Null."
    - PENDING: this call is the one that will actually validate the
      Run/checkpoint and persist+emit a new resolution, so the real
      run_id -> task_id -> JsonlRunEventSink wiring (and its
      fail-closed ApprovalRunNotFoundError if no task owns the run)
      still runs exactly as before, before any write happens.

    The approval_id is the only input available up front, so status
    is learned via a throwaway ApprovalStore read (get() never emits,
    so this is safe either way) before the real store - the one
    actually passed to ApprovalDecisionService - is built.
    """

    request_repository = ApprovalRequestRepository(TASKS_DIR)
    resolution_repository = ApprovalResolutionRepository(TASKS_DIR)
    continuation_checkpoint_repository = (
        RunContinuationCheckpointRepository(TASKS_DIR)
    )

    peeked_request = ApprovalStore(
        request_repository, resolution_repository
    ).get(approval_id)

    if peeked_request.status is ApprovalStatus.RESOLVED:
        approval_store = ApprovalStore(
            request_repository, resolution_repository
        )

        decision_service = ApprovalDecisionService(
            approval_store,
            task_repository,
            run_repository,
            continuation_checkpoint_repository,
        )

        return decision_service, peeked_request, False

    task_id = _resolve_task_id_for_run(peeked_request.run_id)

    if task_id is None:
        raise ApprovalRunNotFoundError(
            f"No task owns run {peeked_request.run_id!r} referenced "
            f"by approval {approval_id!r} - refusing to record an "
            "unaudited decision"
        )

    event_sink = JsonlRunEventSink(
        run_repository.get_events_file(
            task_id, peeked_request.run_id
        ),
        truncate_existing=False,
    )

    approval_store = ApprovalStore(
        request_repository,
        resolution_repository,
        event_sink=event_sink,
    )

    decision_service = ApprovalDecisionService(
        approval_store,
        task_repository,
        run_repository,
        continuation_checkpoint_repository,
    )

    return decision_service, peeked_request, True


def _load_modified_input(path_str: str) -> dict[str, Any]:
    """Load a MODIFY decision's replacement tool input from a file
    rather than a raw command-line JSON string, so it never lands in
    shell history. Never echoes the file's contents, including in
    error messages - a bad file is reported by name only."""

    path = Path(path_str)

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(
            f"Could not read --modified-input-file: {path}"
        ) from error

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"--modified-input-file {path} does not contain valid JSON"
        ) from error

    if not isinstance(data, dict):
        raise ValueError(
            f"--modified-input-file {path} must contain a JSON object"
        )

    return data


def _print_tool_approval_result(
    resolution: ApprovalResolution,
    *,
    run_id: str,
    checked_run: bool,
) -> None:
    # Safe fields only - never proposed_action.input, modified_input,
    # or a full ApprovalRequest/ApprovalResolution repr.
    print(f"Approval ID: {resolution.approval_id}")
    print(f"Run ID:      {run_id}")
    print(f"Decision:    {resolution.decision.value}")
    print("Resolved:    true")
    print(f"Resolved at: {resolution.resolved_at}")

    if checked_run:
        # Only printed when this exact call re-validated the Run
        # itself (the still-PENDING path) - never claimed from a
        # cached or assumed value.
        print("Run status:  waiting_for_approval")
    else:
        print(
            "Run status:  not checked (decision already recorded; "
            "no Task/Run lookup was performed for this call)"
        )

    print("Resumed:     false")
    print("Executed:    false")
    print()

    if resolution.decision is ApprovalDecision.CANCEL:
        print(
            "Cancellation decision recorded. The Run has not been "
            "cancelled yet - applying this decision is a future "
            "resume step."
        )
    else:
        print(
            "Decision recorded. The tool call has not executed and "
            "the Run has not resumed - applying this decision is a "
            "future resume step."
        )


def _resolve_tool_approval(
    approval_id: str,
    decision: ApprovalDecision,
    *,
    modified_input: dict[str, Any] | None = None,
    explanation: str | None = None,
) -> None:
    decision_service, request, checked_run = (
        _build_tool_approval_decision_service(approval_id)
    )

    resolution = decision_service.resolve(
        approval_id,
        decision,
        modified_input=modified_input,
        explanation=explanation,
    )

    _print_tool_approval_result(
        resolution, run_id=request.run_id, checked_run=checked_run
    )


def approve_tool_call(
    approval_id: str, *, explanation: str | None = None
) -> None:
    _resolve_tool_approval(
        approval_id, ApprovalDecision.APPROVE, explanation=explanation
    )


def reject_tool_call(
    approval_id: str, *, explanation: str | None = None
) -> None:
    _resolve_tool_approval(
        approval_id, ApprovalDecision.REJECT, explanation=explanation
    )


def modify_tool_call(
    approval_id: str,
    modified_input_file: str,
    *,
    explanation: str | None = None,
) -> None:
    modified_input = _load_modified_input(modified_input_file)
    _resolve_tool_approval(
        approval_id,
        ApprovalDecision.MODIFY,
        modified_input=modified_input,
        explanation=explanation,
    )


def cancel_tool_call(
    approval_id: str, *, explanation: str | None = None
) -> None:
    _resolve_tool_approval(
        approval_id, ApprovalDecision.CANCEL, explanation=explanation
    )


def list_tool_approvals(run_id: str | None = None) -> None:
    composition = _build_composition()
    requests = composition.inspection_service.list_pending(
        run_id=run_id
    )
    print(format_approval_list(requests))


def show_tool_approval(approval_id: str) -> None:
    composition = _build_composition()
    inspection = composition.inspection_service.inspect(approval_id)
    print(format_approval_detail(inspection))


def _print_continuation_result(result, *, replayed: bool) -> None:
    """Distinguishes a freshly-driven continuation from a cached
    replay of an earlier completed one (5E-5D-6D) - "do not present
    historical state as a freshly checked current Run status": a
    replayed result's counters (llm_rounds/tool_rounds/tool_calls/
    token counts) are None (RunService._result_from_completed_attempt()
    does not reconstruct them - see that method's own docstring), so
    this never prints a stale/fabricated usage line for a replay,
    unlike _print_run_result()'s own `if result.llm_rounds is not
    None` guard already handles correctly either way.
    """

    if replayed:
        print(
            "Replayed an earlier completed continuation for run: "
            f"{result.run_id}"
        )
        print(
            "(This reflects what was already decided and applied "
            "previously - nothing was executed or called just now.)"
        )
    else:
        print(f"Continued run: {result.run_id}")

    print(f"Status:  {result.status}")
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

    if result.status == "cancelled":
        print()
        print(
            "The run was cancelled per the recorded CANCEL decision. "
            "No further tool calls or model requests were made."
        )
    elif result.status == "waiting_for_approval":
        print()
        print(f"Approval ID: {result.approval_id}")
        print(
            "This run is paused again: a further tool call requires "
            "human approval before execution can continue."
        )
        print()
        print("Next steps:")
        print(
            "  Inspect: python -m src.main show-tool-approval "
            f"{result.approval_id}"
        )
        print(
            "  Decide:  python -m src.main approve-tool-call "
            f"{result.approval_id}"
        )
        print(
            "           (or reject-tool-call / modify-tool-call / "
            "cancel-tool-call)"
        )
        print(
            "  Continue: python -m src.main resume-after-approval "
            f"{result.run_id} {result.approval_id}"
        )
    elif result.status in ("completed", "awaiting_review"):
        print()
        print("The run has finished.")


def resume_after_approval_command(run_id: str, approval_id: str) -> None:
    from src.run_continuation_attempt_status import (
        RunContinuationAttemptStatus,
    )
    from src.run_service_composition import (
        build_run_service_for_continuation,
    )

    task_id = _resolve_task_id_for_run(run_id)

    if task_id is None:
        raise ValueError(
            f"No task owns run {run_id!r} - cannot continue it"
        )

    composition = _build_composition()

    # Peeked only to decide how to LABEL the outcome below (replayed
    # vs freshly continued) - purely informational. The actual
    # coordination/correctness (claim ownership, idempotent replay,
    # blocking an incomplete attempt) is entirely RunService.
    # resume_after_approval()'s own job, not re-implemented here; a
    # race between this peek and that call affects only this label,
    # never correctness.
    existing_attempt = composition.attempt_repository.try_load(
        task_id, run_id, approval_id
    )
    replayed = (
        existing_attempt is not None
        and existing_attempt.status
        is RunContinuationAttemptStatus.COMPLETED
    )

    continuation_run_service = build_run_service_for_continuation(
        composition, task_id, run_id
    )
    result = continuation_run_service.resume_after_approval(
        run_id, approval_id
    )

    _print_continuation_result(result, replayed=replayed)


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

    _add_tool_approval_parsers(subparsers)

    resume_after_approval_parser = subparsers.add_parser(
        "resume-after-approval",
        help=(
            "Continue the SAME run after a human has resolved a "
            "pending action-level ToolCall approval."
        ),
    )

    resume_after_approval_parser.add_argument(
        "run_id",
        help="Run ID to continue, for example run-023.",
    )

    resume_after_approval_parser.add_argument(
        "approval_id",
        help=(
            "The source approval_id this attempt must resolve, for "
            "example approval-20260916-0001. A retry for one "
            "approval_id never implicitly resumes a different, later "
            "approval for the same run."
        ),
    )

    list_tool_approvals_parser = subparsers.add_parser(
        "list-tool-approvals",
        help="List pending action-level ToolCall approval requests.",
    )

    list_tool_approvals_parser.add_argument(
        "--run-id",
        dest="run_id",
        default=None,
        help="Only show pending approvals for this run.",
    )

    show_tool_approval_parser = subparsers.add_parser(
        "show-tool-approval",
        help=(
            "Show safe metadata for one approval request: its "
            "recorded decision (if any), and whether it has been "
            "applied or used to continue its run."
        ),
    )

    show_tool_approval_parser.add_argument(
        "approval_id",
        help="Approval ID to inspect.",
    )

    return parser


def _add_tool_approval_parsers(subparsers) -> None:
    """Register the four action-level ToolCall approval commands
    (approve/reject/modify/cancel-tool-call). Deliberately named to
    not collide with the plan-level approve-plan/reject-plan commands
    above, or with RuntimeApprovalService's recovery-approval concept
    (not wired into this CLI at all) - these resolve a single pending
    ApprovalRequest via ApprovalDecisionService only. They record a
    decision; they never execute a tool, call the provider, resume a
    Run, or create a new Run."""

    for name, decision_value, needs_input_file in (
        ("approve-tool-call", "approve", False),
        ("reject-tool-call", "reject", False),
        ("modify-tool-call", "modify", True),
        ("cancel-tool-call", "cancel", False),
    ):
        tool_approval_parser = subparsers.add_parser(
            name,
            help=(
                f"Record a human {decision_value.upper()} decision on "
                "a pending action-level ToolCall approval. Records "
                "only - does not execute the tool, call the provider, "
                "or resume the Run."
            ),
        )

        tool_approval_parser.add_argument(
            "approval_id",
            help=(
                "Approval ID to resolve, for example "
                "approval-20260916-0001."
            ),
        )

        tool_approval_parser.add_argument(
            "--explanation",
            default=None,
            help="Optional human-readable note recorded with this decision.",
        )

        if needs_input_file:
            tool_approval_parser.add_argument(
                "--modified-input-file",
                required=True,
                help=(
                    "Path to a UTF-8 JSON file containing the "
                    "replacement tool input object. Not accepted as "
                    "a raw command-line JSON string, so it never "
                    "lands in shell history."
                ),
            )


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
        elif args.command == "approve-tool-call":
            approve_tool_call(
                args.approval_id, explanation=args.explanation
            )
        elif args.command == "reject-tool-call":
            reject_tool_call(
                args.approval_id, explanation=args.explanation
            )
        elif args.command == "modify-tool-call":
            modify_tool_call(
                args.approval_id,
                args.modified_input_file,
                explanation=args.explanation,
            )
        elif args.command == "cancel-tool-call":
            cancel_tool_call(
                args.approval_id, explanation=args.explanation
            )
        elif args.command == "resume-after-approval":
            resume_after_approval_command(args.run_id, args.approval_id)
        elif args.command == "list-tool-approvals":
            list_tool_approvals(args.run_id)
        elif args.command == "show-tool-approval":
            show_tool_approval(args.approval_id)
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
