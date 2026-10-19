from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.approval_application_repository import (
    ApprovalApplicationRepository,
)
from src.approval_application_service import ApprovalApplicationService
from src.approval_continuation_preparation_service import (
    ApprovalContinuationPreparationService,
)
from src.approval_inspection_service import ApprovalInspectionService
from src.approval_policy_config import load_approval_rules
from src.approval_request_repository import ApprovalRequestRepository
from src.approval_resolution_repository import (
    ApprovalResolutionRepository,
)
from src.approval_rule import ApprovalRule
from src.approval_store import ApprovalStore
from src.config.settings import Settings
from src.context_builder import RunContextBuilder
from src.executor_factory import (
    KNOWN_TOOL_NAMES,
    create_run_executor,
    create_tool_executor,
)
from src.repositories import AgentRepository, RunRepository, TaskRepository
from src.rule_based_tool_approval_policy import (
    RuleBasedToolApprovalPolicy,
)
from src.run_approval_rule_snapshot import load as load_approval_rule_snapshot
from src.run_continuation_attempt_repository import (
    RunContinuationAttemptRepository,
)
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)
from src.run_events import JsonlRunEventSink, RunEventSink
from src.run_service import RunService
from src.schema_aware_tool_input_previewer import (
    SchemaAwareToolInputPreviewer,
)
from src.tool_approval_gate import ToolApprovalGate


def load_configured_approval_rules(
    settings: Settings, project_root: Path
) -> list[ApprovalRule]:
    """Loads and fully validates this process's live approval-policy
    configuration (5E-5D-6D) - see src/approval_policy_config.py for
    the file format and validation rules. An empty "rules": [] file
    (the shipped default, src/config/approval_policy.json) returns an
    empty list, preserving the exact ungated behavior every Run had
    before this feature existed - gating is opt-in, never silently
    assumed."""

    policy_path = project_root / settings.approval_policy_path

    return load_approval_rules(
        policy_path, known_tool_names=KNOWN_TOOL_NAMES
    )


class _TaskResolvingRunEventSink:
    """A RunEventSink that resolves each event's own run_id to its
    owning task_id *at emit time*, then appends to that Run's actual
    events.jsonl (5E-5D-6D) - not a fixed single destination file,
    because the ApprovalStore this sink is attached to is shared
    across every Run in the process (built once, at CLI composition
    time, before any specific Run is known), while approval_requested/
    approval_resolved events must each land in the events.jsonl of
    whichever Run actually produced them.

    An event with no resolvable owning task (an orphaned run_id, or a
    run_id the store has simply never heard of) is silently dropped
    rather than raising - matching ApprovalStore.create()/resolve()'s
    own existing contract that an event_sink's job is strictly
    best-effort audit, never a gate on whether the underlying
    request/resolution write itself succeeds (NullRunEventSink already
    establishes that any event may safely go nowhere).
    """

    def __init__(
        self,
        task_repository: TaskRepository,
        run_repository: RunRepository,
    ) -> None:
        self._task_repository = task_repository
        self._run_repository = run_repository

    def emit(self, event: dict) -> None:
        run_id = event.get("run_id")

        if not run_id:
            return

        task_id = self._find_task_id_for_run(run_id)

        if task_id is None:
            return

        JsonlRunEventSink(
            self._run_repository.get_events_file(task_id, run_id),
            truncate_existing=False,
        ).emit(event)

    def _find_task_id_for_run(self, run_id: str) -> str | None:
        for task in self._task_repository.list_all():
            if run_id in self._run_repository.list_run_ids(task.id):
                return task.id

        return None


def build_approval_store(
    tasks_dir: Path,
    task_repository: TaskRepository,
    run_repository: RunRepository,
) -> ApprovalStore:
    return ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
        event_sink=_TaskResolvingRunEventSink(
            task_repository, run_repository
        ),
    )


def build_tool_approval_gate(
    approval_store: ApprovalStore,
    approval_rules: list[ApprovalRule],
) -> ToolApprovalGate | None:
    """None for an empty rule list (5E-5D-6D) - "an empty configuration
    preserves existing ungated behavior for new Runs": LLMRunExecutor/
    LLMAgentRunExecutor already treat approval_gate=None as "no gating
    at all", so an empty policy produces that exact prior behavior
    rather than a gate that is merely never triggered."""

    if not approval_rules:
        return None

    policy = RuleBasedToolApprovalPolicy(approval_rules)
    previewer = SchemaAwareToolInputPreviewer()

    return ToolApprovalGate(policy, previewer, approval_store)


@dataclass(frozen=True)
class ProductionComposition:
    """Every production collaborator this CLI's approval workflow
    needs, built once per process (5E-5D-6D) - a small shared bundle
    so main.py's individual command functions construct nothing
    duplicated themselves; see build_run_service_for_continuation()
    for the one thing deliberately built fresh per call instead
    (ApprovalApplicationService's Run-specific ToolExecutor)."""

    settings: Settings
    project_root: Path
    tasks_dir: Path
    task_repository: TaskRepository
    run_repository: RunRepository
    agent_repository: AgentRepository
    context_builder: RunContextBuilder
    approval_rules: list[ApprovalRule]
    approval_store: ApprovalStore
    checkpoint_repository: RunContinuationCheckpointRepository
    attempt_repository: RunContinuationAttemptRepository
    application_repository: ApprovalApplicationRepository
    preparation_service: ApprovalContinuationPreparationService
    inspection_service: ApprovalInspectionService
    run_service: RunService


def build_production_composition(
    *,
    settings: Settings,
    project_root: Path,
    tasks_dir: Path,
    task_repository: TaskRepository,
    run_repository: RunRepository,
    agent_repository: AgentRepository,
    context_builder: RunContextBuilder,
) -> ProductionComposition:
    """The one production composition root for 5E-5D-6D - called once,
    at CLI startup, in src/main.py. Building this never requires LLM
    provider credentials (executor_factory._LazyLLMProvider defers
    that until a real provider call is actually made), so every
    command - including ones that never execute anything - can safely
    construct it.
    """

    approval_rules = load_configured_approval_rules(
        settings, project_root
    )
    approval_store = build_approval_store(
        tasks_dir, task_repository, run_repository
    )
    approval_gate = build_tool_approval_gate(
        approval_store, approval_rules
    )
    checkpoint_repository = RunContinuationCheckpointRepository(
        tasks_dir
    )
    attempt_repository = RunContinuationAttemptRepository(tasks_dir)
    application_repository = ApprovalApplicationRepository(tasks_dir)

    executor = create_run_executor(
        settings=settings,
        agent_repository=agent_repository,
        run_repository=run_repository,
        project_root=project_root,
        approval_gate=approval_gate,
        continuation_checkpoint_repository=(
            checkpoint_repository if approval_gate is not None else None
        ),
        approval_rules=(
            approval_rules if approval_gate is not None else None
        ),
    )

    preparation_service = ApprovalContinuationPreparationService(
        run_repository, checkpoint_repository, approval_store
    )

    inspection_service = ApprovalInspectionService(
        approval_store,
        application_repository,
        attempt_repository,
        task_repository,
        run_repository,
    )

    run_service = RunService(
        task_repository=task_repository,
        run_repository=run_repository,
        agent_repository=agent_repository,
        context_builder=context_builder,
        executor=executor,
        project_root=project_root,
        approval_continuation_preparation_service=preparation_service,
        # approval_application_service is deliberately left
        # unconfigured on this shared instance (5E-5D-6D) -
        # ApprovalApplicationService needs a ToolExecutor built from
        # the SPECIFIC Run being continued's own agent (same
        # workspace/ToolPolicy/handler registry/limits the executor
        # would use for that Run), which is not known until a
        # resume-after-approval call names a run_id. See
        # build_run_service_for_continuation() below, which builds a
        # second RunService, reusing this same executor/
        # preparation_service/attempt_repository, adding only a
        # freshly-built, Run-specific ApprovalApplicationService.
        approval_application_service=None,
        run_continuation_attempt_repository=attempt_repository,
    )

    return ProductionComposition(
        settings=settings,
        project_root=project_root,
        tasks_dir=tasks_dir,
        task_repository=task_repository,
        run_repository=run_repository,
        agent_repository=agent_repository,
        context_builder=context_builder,
        approval_rules=approval_rules,
        approval_store=approval_store,
        checkpoint_repository=checkpoint_repository,
        attempt_repository=attempt_repository,
        application_repository=application_repository,
        preparation_service=preparation_service,
        inspection_service=inspection_service,
        run_service=run_service,
    )


def build_run_service_for_continuation(
    composition: ProductionComposition,
    task_id: str,
    run_id: str,
) -> RunService:
    """Builds the one-off RunService used for a single
    resume-after-approval call (5E-5D-6D).

    Rebuilds its own executor/approval_gate from this Run's own
    persisted approval-rule snapshot (resolve_run_approval_rules()),
    NOT from composition.approval_rules (this process's *current* live
    APPROVAL_POLICY_PATH read) - this is the one thing that must never
    be reused as-is from composition: every CLI invocation is a fresh
    process, so composition itself is rebuilt from scratch, from
    whatever the live config file says *right now*, on every single
    command - including this one. If this function used
    composition.approval_rules/composition.run_service's executor
    directly, a config file edited or deleted between the original
    `run` and a later `resume-after-approval` would silently change
    which calls get gated for the rest of an in-flight Run. Using the
    Run's own snapshot instead is what makes "approval configuration
    survives a pause and a fresh CLI invocation" and "do not resume
    with empty rules merely because ... a configuration file vanished"
    both hold.

    ApprovalApplicationService's ToolExecutor is built fresh, here,
    using create_tool_executor() with this specific run's agent_directory
    and composition.project_root as repository_root - the identical
    construction LLMAgentRunExecutor.execute()/resume_after_approval()
    themselves use internally (see that class's own
    _resolve_repository_root(), always composition.project_root today) -
    never an unrestricted default ToolExecutor. Its event_sink is a
    fresh JsonlRunEventSink pointed at *this* run's own events.jsonl
    (truncate_existing=False, matching every other append-only sink
    this stack uses for an existing Run), so its "approval_applied"
    event lands in the same place every other event for this Run
    already does.

    composition.preparation_service/attempt_repository ARE reused
    as-is - both are keyed by (and read fresh from disk per call)
    task_id/run_id/approval_id, not by any in-memory policy state, so
    sharing them carries none of the staleness risk the executor/gate
    rebuild above exists to avoid.
    """

    run = composition.run_repository.load(task_id, run_id)
    agent_directory = composition.agent_repository.get_agent_dir(
        run.agent_id
    )

    run_rules = resolve_run_approval_rules(composition, task_id, run_id)
    approval_gate = build_tool_approval_gate(
        composition.approval_store, run_rules
    )

    executor = create_run_executor(
        settings=composition.settings,
        agent_repository=composition.agent_repository,
        run_repository=composition.run_repository,
        project_root=composition.project_root,
        approval_gate=approval_gate,
        continuation_checkpoint_repository=(
            composition.checkpoint_repository
            if approval_gate is not None
            else None
        ),
    )

    tool_executor = create_tool_executor(
        repository_root=composition.project_root,
        agent_directory=agent_directory,
        test_policy_path=(
            composition.project_root
            / composition.settings.test_policy_path
        ),
    )

    event_sink: RunEventSink = JsonlRunEventSink(
        composition.run_repository.get_events_file(task_id, run_id),
        truncate_existing=False,
    )

    application_service = ApprovalApplicationService(
        composition.preparation_service,
        composition.application_repository,
        tool_executor,
        event_sink=event_sink,
    )

    return RunService(
        task_repository=composition.task_repository,
        run_repository=composition.run_repository,
        agent_repository=composition.agent_repository,
        context_builder=composition.context_builder,
        executor=executor,
        project_root=composition.project_root,
        approval_continuation_preparation_service=(
            composition.preparation_service
        ),
        approval_application_service=application_service,
        run_continuation_attempt_repository=(
            composition.attempt_repository
        ),
    )


def resolve_run_approval_rules(
    composition: ProductionComposition, task_id: str, run_id: str
) -> list[ApprovalRule]:
    """Returns the ApprovalRules actually in effect for one Run's
    lifetime (5E-5D-6D) - "approval configuration survives a pause and
    a fresh CLI invocation". A Run's own durable snapshot
    (src/run_approval_rule_snapshot.py, written once at that Run's
    execute()-start) is authoritative whenever it exists; this
    composition's *current*, possibly since-changed or since-deleted,
    live APPROVAL_POLICY_PATH configuration is used only as a fallback
    for a Run that predates this feature (no snapshot was ever
    written for it) - never the reverse. This is what makes "do not
    resume with empty rules merely because ... a configuration file
    vanished" hold: resume_after_approval()'s own continuation path
    never calls this function at all (ToolApprovalGate's policy is
    already fixed, baked into composition.run_service's executor at
    CLI-startup time, for the whole process's lifetime) - this helper
    exists only for *display* (showing which rules govern a given Run,
    e.g. from a future inspection command), not for reconstructing
    gating behavior itself.
    """

    run_directory = composition.run_repository.get_run_dir(
        task_id, run_id
    )
    snapshot = load_approval_rule_snapshot(run_directory)

    if snapshot is not None:
        return snapshot

    return composition.approval_rules
