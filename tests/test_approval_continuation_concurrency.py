"""Independent-process concurrency evidence for 5E-5D-6B/6C.

The in-process threading.Barrier tests already in
tests/test_approval_application_service.py and
tests/test_run_service_resume_after_approval.py prove the
create_exclusive()-based claims are safe against concurrent *threads*
within one process. They do not prove safety against concurrent
*processes* (separate Python interpreters, separate memory, racing on
the same files via the filesystem alone) - this module does, using
real multiprocessing.Process workers released simultaneously by a
multiprocessing.Barrier (deterministic synchronization, not a sleep-
based approximation of one).

Every worker function here is a module-level function (not a closure)
because multiprocessing must be able to pickle and re-import it in the
child process.
"""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path
from typing import Any

from src.approval_application_repository import (
    ApprovalApplicationRepository,
)
from src.approval_application_service import ApprovalApplicationService
from src.approval_continuation_preparation_service import (
    ApprovalContinuationPreparationService,
)
from src.approval_decision import ApprovalDecision
from src.approval_request import ApprovalRequest, RiskLevel
from src.approval_request_repository import ApprovalRequestRepository
from src.approval_resolution import ApprovalResolution
from src.approval_resolution_repository import (
    ApprovalResolutionRepository,
)
from src.approval_store import ApprovalStore
from src.context_builder import RunContextBuilder
from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult
from src.llm.types import LLMMessage
from src.repositories import AgentRepository, RunRepository, TaskRepository
from src.run_continuation_attempt_repository import (
    RunContinuationAttemptRepository,
)
from src.run_continuation_attempt_status import (
    RunContinuationAttemptStatus,
)
from src.run_continuation_checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    RunContinuationCheckpoint,
)
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)
from src.run_service import RunService
from src.services.tools.tool_executor import ToolExecutor
from src.services.tools.tool_policy import ToolPolicy, ToolPolicyEntry

NOW = "2026-01-01T00:00:00Z"
TASK_ID = "task-1"
RUN_ID = "run-007"
APPROVAL_ID = "approval-1"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _log_call(log_path: Path, tool_call_id: str) -> None:
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(tool_call_id + "\n")


class _FileLoggingHandler:
    """Records each call by appending its id to a plain text file on
    disk - the only way a parent test process can observe what a
    *child* process's handler did, since child processes do not share
    memory with the parent or each other."""

    def __init__(self, name: str, log_path: Path) -> None:
        self.definition = ToolDefinition(
            name=name, description="test tool", input_schema={}
        )
        self._log_path = log_path

    def execute(
        self,
        *,
        tool_call_id: str,
        tool_input: dict[str, Any],
        repository_root: Path,
        max_output_chars: int,
    ) -> ToolResult:
        _log_call(self._log_path, tool_call_id)

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.definition.name,
            success=True,
            output=f"{self.definition.name} ok",
        )


# --- 6B retrofit: ApprovalApplicationService across real processes ------


def _write_application_scenario(
    tasks_dir: Path,
    *,
    task_id: str = TASK_ID,
    run_id: str = RUN_ID,
    approval_id: str = APPROVAL_ID,
    tool_call_id: str = "toolu_1",
    resolve: bool = True,
) -> None:
    _write_json(
        tasks_dir / task_id / "task.json",
        {
            "id": task_id,
            "title": "Test task",
            "description": "A task used for testing.",
            "workspace_id": "workspace-1",
            "status": "in_progress",
            "priority": "normal",
            "created_by": "user-1",
            "assigned_agents": ["agent-test"],
            "created_at": NOW,
            "updated_at": NOW,
            "started_at": NOW,
            "completed_at": None,
            "abandoned_at": None,
            "current_run_id": run_id,
            "run_count": 1,
            "completion_criteria": [],
            "tags": [],
        },
    )
    _write_json(
        tasks_dir / task_id / "runs" / run_id / "run.json",
        {
            "id": run_id,
            "task_id": task_id,
            "agent_id": "agent-test",
            "status": "waiting_for_approval",
            "created_at": NOW,
            "updated_at": NOW,
            "started_at": NOW,
            "completed_at": None,
        },
    )

    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    tool_call = ToolCall(
        id=tool_call_id, name="write_file", input={"path": "a.py"}
    )
    approval_store.create(
        ApprovalRequest(
            approval_id=approval_id,
            run_id=run_id,
            proposed_action=tool_call,
            reason="writes a file",
            risk_level=RiskLevel.MEDIUM,
            input_preview="write a.py",
        )
    )

    checkpoint_repository = RunContinuationCheckpointRepository(
        tasks_dir
    )
    checkpoint_repository.save(
        RunContinuationCheckpoint(
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            task_id=task_id,
            run_id=run_id,
            approval_id=approval_id,
            messages=(LLMMessage(role="user", content="do the task"),),
            pending_round_tool_calls=(tool_call,),
            pending_tool_call_index=0,
            pending_tool_call_id=tool_call_id,
            completed_tool_results=(),
            llm_rounds=1,
            tool_rounds=1,
            cumulative_tool_calls=1,
            total_input_tokens=10,
            total_output_tokens=5,
            max_tool_rounds=8,
            max_total_tokens=100_000,
            created_at=NOW,
        )
    )

    if resolve:
        approval_store.resolve(
            approval_id,
            ApprovalResolution(
                approval_id=approval_id,
                decision=ApprovalDecision.APPROVE,
            ),
        )


def _application_worker(
    tasks_dir_str: str,
    log_path_str: str,
    barrier: Any,
    result_queue: Any,
) -> None:
    tasks_dir = Path(tasks_dir_str)
    log_path = Path(log_path_str)

    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    run_repository = RunRepository(tasks_dir)
    checkpoint_repository = RunContinuationCheckpointRepository(
        tasks_dir
    )
    preparation_service = ApprovalContinuationPreparationService(
        run_repository, checkpoint_repository, approval_store
    )
    application_repository = ApprovalApplicationRepository(tasks_dir)
    tool_executor = ToolExecutor(
        repository_root=tasks_dir,
        handlers=[_FileLoggingHandler("write_file", log_path)],
        tool_policy=ToolPolicy(
            default="deny",
            tools={"write_file": ToolPolicyEntry(enabled=True)},
        ),
    )
    application_service = ApprovalApplicationService(
        preparation_service, application_repository, tool_executor
    )

    barrier.wait(timeout=10)

    try:
        outcome = application_service.apply(TASK_ID, RUN_ID, APPROVAL_ID)
        result_queue.put(("ok", outcome.tool_result.success))
    except Exception as exc:  # noqa: BLE001
        result_queue.put(("error", type(exc).__name__, str(exc)))


def test_two_processes_cannot_both_apply_the_same_approval(
    tmp_path: Path,
) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_application_scenario(tasks_dir)
    log_path = tmp_path / "handler_calls.log"

    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    result_queue: Any = ctx.Queue()

    processes = [
        ctx.Process(
            target=_application_worker,
            args=(str(tasks_dir), str(log_path), barrier, result_queue),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    results = [result_queue.get(timeout=5) for _ in range(2)]

    calls = (
        log_path.read_text(encoding="utf-8").splitlines()
        if log_path.exists()
        else []
    )
    assert calls == ["toolu_1"]

    # Exactly one dispatch happened. The winner always gets a
    # successful outcome; a loser that checked in *before* the winner
    # finished persisting its outcome correctly sees
    # ApprovalApplicationBlockedError instead (the application claim
    # does not block forever - a later retry would see the completed
    # outcome - it blocks *this* overlapping attempt, which is exactly
    # the property under test).
    ok_results = [r for r in results if r[0] == "ok"]
    error_results = [r for r in results if r[0] == "error"]
    assert len(ok_results) + len(error_results) == 2
    assert len(ok_results) >= 1
    assert all(success for _kind, success in ok_results)
    for error_result in error_results:
        assert error_result[1] == "ApprovalApplicationBlockedError"


# --- 6C: RunService.resume_after_approval across real processes ---------


def _write_agent(agents_dir: Path, agent_id: str = "agent-test") -> None:
    agent_dir = agents_dir / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "system-prompt.md").write_text(
        "You are a test agent.", encoding="utf-8"
    )
    (agent_dir / "tool-policy.json").write_text("{}", encoding="utf-8")
    _write_json(
        agent_dir / "agent.json",
        {
            "id": agent_id,
            "name": agent_id,
            "description": "A test agent.",
            "owner": "owner-1",
            "status": "ready",
            "role": "general",
            "template_id": "general",
            "default_model": "fake-model",
            "credential_id": "cred-1",
            "system_prompt_path": "system-prompt.md",
            "tool_policy_path": "tool-policy.json",
            "default_workspace_id": "workspace-1",
            "capabilities": [],
            "limits": {
                "memory_mb": 512,
                "cpus": 1,
                "timeout_seconds": 60,
                "max_input_tokens": 1000,
                "max_output_tokens": 1000,
            },
            "created_at": NOW,
            "updated_at": NOW,
        },
    )


class _ImmediateFinishExecutor:
    """An ApprovalContinuationCapableExecutor whose
    resume_after_approval() consumes the pending outcome directly and
    reports the Run complete, without a real LLM loop - this test is
    about RunContinuationAttemptRepository's cross-process claim, not
    about the tool-call loop (already covered by the in-process
    threading test and the A->B->C integration tests)."""

    def __init__(self, log_path: Path) -> None:
        self._log_path = log_path

    def execute(self, context):  # pragma: no cover - unused here
        raise NotImplementedError

    def resume_after_approval(self, context, checkpoint, outcome):
        from src.models import RunExecutionResult

        assert outcome.tool_result is not None
        _log_call(self._log_path, outcome.tool_result.tool_call_id)

        return RunExecutionResult(
            output_markdown="done",
            summary_markdown="done",
            metadata={
                "llm_rounds": checkpoint.llm_rounds,
                "tool_rounds": checkpoint.tool_rounds,
                "tool_calls": checkpoint.cumulative_tool_calls + 1,
                "total_input_tokens": checkpoint.total_input_tokens,
                "total_output_tokens": checkpoint.total_output_tokens,
            },
        )


def _build_run_service(
    tasks_dir: Path,
    agents_dir: Path,
    executor: Any,
) -> RunService:
    task_repository = TaskRepository(tasks_dir)
    run_repository = RunRepository(tasks_dir)
    agent_repository = AgentRepository(agents_dir)
    approval_store = ApprovalStore(
        ApprovalRequestRepository(tasks_dir),
        ApprovalResolutionRepository(tasks_dir),
    )
    checkpoint_repository = RunContinuationCheckpointRepository(
        tasks_dir
    )
    preparation_service = ApprovalContinuationPreparationService(
        run_repository, checkpoint_repository, approval_store
    )
    application_repository = ApprovalApplicationRepository(tasks_dir)
    tool_executor = ToolExecutor(
        repository_root=tasks_dir,
        handlers=[],
        tool_policy=ToolPolicy(
            default="deny",
            tools={"write_file": ToolPolicyEntry(enabled=True)},
        ),
    )
    application_service = ApprovalApplicationService(
        preparation_service, application_repository, tool_executor
    )
    attempt_repository = RunContinuationAttemptRepository(tasks_dir)
    context_builder = RunContextBuilder(
        project_root=tasks_dir,
        task_repository=task_repository,
        run_repository=run_repository,
        agent_repository=agent_repository,
    )

    return RunService(
        task_repository,
        run_repository,
        agent_repository,
        context_builder,
        executor,
        tasks_dir,
        approval_continuation_preparation_service=preparation_service,
        approval_application_service=application_service,
        run_continuation_attempt_repository=attempt_repository,
    )


def _run_continuation_worker(
    tasks_dir_str: str,
    agents_dir_str: str,
    log_path_str: str,
    barrier: Any,
    result_queue: Any,
    run_id: str = RUN_ID,
    approval_id: str = APPROVAL_ID,
) -> None:
    tasks_dir = Path(tasks_dir_str)
    agents_dir = Path(agents_dir_str)
    log_path = Path(log_path_str)

    run_service = _build_run_service(
        tasks_dir, agents_dir, _ImmediateFinishExecutor(log_path)
    )

    barrier.wait(timeout=10)

    try:
        result = run_service.resume_after_approval(run_id, approval_id)
        result_queue.put(("ok", result.status))
    except Exception as exc:  # noqa: BLE001
        result_queue.put(("error", type(exc).__name__, str(exc)))


class _SlowFinishExecutor:
    """Like _ImmediateFinishExecutor, but signals started_event once
    inside resume_after_approval() (meaning create_exclusive() and the
    run_guard() lock are already held) and then blocks on
    release_event before finishing - gives a test a deterministic
    window in which this worker is *known* to own the Run's guard."""

    def __init__(
        self, log_path: Path, started_event: Any, release_event: Any
    ) -> None:
        self._log_path = log_path
        self._started_event = started_event
        self._release_event = release_event

    def execute(self, context):  # pragma: no cover - unused here
        raise NotImplementedError

    def resume_after_approval(self, context, checkpoint, outcome):
        from src.models import RunExecutionResult

        self._started_event.set()
        self._release_event.wait(timeout=10)

        assert outcome.tool_result is not None
        _log_call(self._log_path, outcome.tool_result.tool_call_id)

        return RunExecutionResult(
            output_markdown="done",
            summary_markdown="done",
            metadata={
                "llm_rounds": checkpoint.llm_rounds,
                "tool_rounds": checkpoint.tool_rounds,
                "tool_calls": checkpoint.cumulative_tool_calls + 1,
                "total_input_tokens": checkpoint.total_input_tokens,
                "total_output_tokens": checkpoint.total_output_tokens,
            },
        )


def _slow_owner_worker(
    tasks_dir_str: str,
    agents_dir_str: str,
    log_path_str: str,
    started_event: Any,
    release_event: Any,
    result_queue: Any,
) -> None:
    tasks_dir = Path(tasks_dir_str)
    agents_dir = Path(agents_dir_str)
    log_path = Path(log_path_str)

    run_service = _build_run_service(
        tasks_dir,
        agents_dir,
        _SlowFinishExecutor(log_path, started_event, release_event),
    )

    try:
        result = run_service.resume_after_approval(RUN_ID, APPROVAL_ID)
        result_queue.put(("ok", result.status))
    except Exception as exc:  # noqa: BLE001
        result_queue.put(("error", type(exc).__name__, str(exc)))


def _contender_worker(
    tasks_dir_str: str,
    agents_dir_str: str,
    started_event: Any,
    candidate_approval_id: str,
    result_queue: Any,
) -> None:
    tasks_dir = Path(tasks_dir_str)
    agents_dir = Path(agents_dir_str)

    run_service = _build_run_service(
        tasks_dir, agents_dir, _ImmediateFinishExecutor(tasks_dir / "unused.log")
    )

    assert started_event.wait(timeout=10)

    try:
        result = run_service.resume_after_approval(
            RUN_ID, candidate_approval_id
        )
        result_queue.put(("ok", result.status))
    except Exception as exc:  # noqa: BLE001
        result_queue.put(("error", type(exc).__name__, str(exc)))


class _StallForeverExecutor:
    """Signals claim_created_event once resume_after_approval() is
    invoked - meaning create_exclusive() already succeeded and this
    process now owns both the OS lock and the persisted CLAIMED record
    - then blocks indefinitely. The test kills this process while it
    is stalled, simulating a crash after the claim exists but before
    any further progress."""

    def __init__(self, claim_created_event: Any) -> None:
        self._claim_created_event = claim_created_event

    def execute(self, context):  # pragma: no cover - unused here
        raise NotImplementedError

    def resume_after_approval(self, context, checkpoint, outcome):
        self._claim_created_event.set()

        while True:
            import time

            time.sleep(0.05)


def _stall_after_claim_worker(
    tasks_dir_str: str,
    agents_dir_str: str,
    claim_created_event: Any,
) -> None:
    tasks_dir = Path(tasks_dir_str)
    agents_dir = Path(agents_dir_str)

    run_service = _build_run_service(
        tasks_dir, agents_dir, _StallForeverExecutor(claim_created_event)
    )

    run_service.resume_after_approval(RUN_ID, APPROVAL_ID)


def test_two_processes_cannot_both_continue_the_same_source_approval(
    tmp_path: Path,
) -> None:
    tasks_dir = tmp_path / "tasks"
    agents_dir = tmp_path / "agents"
    _write_application_scenario(tasks_dir)
    _write_agent(agents_dir)
    run_repository = RunRepository(tasks_dir)
    run_repository.write_input(TASK_ID, RUN_ID, "do the task")
    log_path = tmp_path / "handler_calls.log"

    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    result_queue: Any = ctx.Queue()

    processes = [
        ctx.Process(
            target=_run_continuation_worker,
            args=(
                str(tasks_dir),
                str(agents_dir),
                str(log_path),
                barrier,
                result_queue,
            ),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    results = [result_queue.get(timeout=5) for _ in range(2)]

    calls = (
        log_path.read_text(encoding="utf-8").splitlines()
        if log_path.exists()
        else []
    )
    assert calls == ["toolu_1"]

    ok_results = [r for r in results if r[0] == "ok"]
    error_results = [r for r in results if r[0] == "error"]
    assert len(ok_results) + len(error_results) == 2
    assert len(ok_results) >= 1
    for _kind, status in ok_results:
        assert status == "completed"
    for error_result in error_results:
        assert error_result[1] == "RunContinuationBlockedError"


# --- 6C-1: Run-wide exclusivity across real processes ------------------


def test_different_approval_ids_blocked_while_owner_holds_lock(
    tmp_path: Path,
) -> None:
    """While one process is inside resume_after_approval() for the
    Run's real pending approval, a second process asking about a
    *different* (here: nonexistent) candidate approval_id for the
    *same* run_id must be refused immediately - before it ever creates
    its own attempt record or reaches application/tool/provider code -
    not merely serialized behind the first. Once the owner finishes
    and releases the guard, a stale candidate id still cannot create
    an executable attempt: it is validated against current state, not
    silently granted a fresh chapter just because the lock is free."""

    tasks_dir = tmp_path / "tasks"
    agents_dir = tmp_path / "agents"
    _write_application_scenario(tasks_dir)
    _write_agent(agents_dir)
    RunRepository(tasks_dir).write_input(TASK_ID, RUN_ID, "do the task")
    log_path = tmp_path / "handler_calls.log"

    ctx = mp.get_context("spawn")
    started_event = ctx.Event()
    release_event = ctx.Event()
    owner_queue: Any = ctx.Queue()
    contender_queue: Any = ctx.Queue()

    owner = ctx.Process(
        target=_slow_owner_worker,
        args=(
            str(tasks_dir),
            str(agents_dir),
            str(log_path),
            started_event,
            release_event,
            owner_queue,
        ),
    )
    owner.start()

    assert started_event.wait(timeout=10)

    contender = ctx.Process(
        target=_contender_worker,
        args=(
            str(tasks_dir),
            str(agents_dir),
            started_event,
            "approval-different-candidate",
            contender_queue,
        ),
    )
    contender.start()
    contender.join(timeout=15)
    assert contender.exitcode == 0

    contender_result = contender_queue.get(timeout=5)
    assert contender_result[0] == "error"
    assert contender_result[1] == "RunContinuationBlockedError"

    # The contender never got far enough to dispatch anything, or to
    # create its own attempt record for the candidate id.
    assert not log_path.exists()
    attempt_repository = RunContinuationAttemptRepository(tasks_dir)
    assert (
        attempt_repository.try_load(
            TASK_ID, RUN_ID, "approval-different-candidate"
        )
        is None
    )

    # Let the owner finish.
    release_event.set()
    owner.join(timeout=15)
    assert owner.exitcode == 0
    owner_result = owner_queue.get(timeout=5)
    assert owner_result[0] == "ok"
    assert owner_result[1] == "completed"
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "toolu_1"
    ]

    # The guard is free now - but a stale candidate id is still
    # rejected by state validation, not silently accepted.
    run_service = _build_run_service(
        tasks_dir, agents_dir, _ImmediateFinishExecutor(log_path)
    )
    with_error = None
    try:
        run_service.resume_after_approval(
            RUN_ID, "approval-different-candidate"
        )
    except Exception as exc:  # noqa: BLE001
        with_error = exc
    assert with_error is not None
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "toolu_1"
    ]


def test_different_runs_proceed_concurrently(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    agents_dir = tmp_path / "agents"
    run_a, run_b = "run-a", "run-b"
    approval_a, approval_b = "approval-a", "approval-b"

    _write_application_scenario(
        tasks_dir,
        task_id=TASK_ID,
        run_id=run_a,
        approval_id=approval_a,
        tool_call_id="toolu_a",
    )
    _write_application_scenario(
        tasks_dir,
        task_id=TASK_ID,
        run_id=run_b,
        approval_id=approval_b,
        tool_call_id="toolu_b",
    )
    _write_agent(agents_dir)
    run_repository = RunRepository(tasks_dir)
    run_repository.write_input(TASK_ID, run_a, "do the task")
    run_repository.write_input(TASK_ID, run_b, "do the task")
    log_path = tmp_path / "handler_calls.log"

    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    result_queue: Any = ctx.Queue()

    processes = [
        ctx.Process(
            target=_run_continuation_worker,
            args=(
                str(tasks_dir),
                str(agents_dir),
                str(log_path),
                barrier,
                result_queue,
                run_id,
                approval_id,
            ),
        )
        for run_id, approval_id in (
            (run_a, approval_a),
            (run_b, approval_b),
        )
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    results = [result_queue.get(timeout=5) for _ in range(2)]

    # Two independent Runs never contend for each other's guard -
    # both succeed, both dispatch.
    assert all(r[0] == "ok" for r in results)
    assert all(r[1] == "completed" for r in results)
    assert sorted(
        log_path.read_text(encoding="utf-8").splitlines()
    ) == ["toolu_a", "toolu_b"]


def test_owner_terminated_after_claim_releases_lock_but_blocks_retry(
    tmp_path: Path,
) -> None:
    tasks_dir = tmp_path / "tasks"
    agents_dir = tmp_path / "agents"
    _write_application_scenario(tasks_dir)
    _write_agent(agents_dir)
    RunRepository(tasks_dir).write_input(TASK_ID, RUN_ID, "do the task")

    ctx = mp.get_context("spawn")
    claim_created_event = ctx.Event()

    owner = ctx.Process(
        target=_stall_after_claim_worker,
        args=(str(tasks_dir), str(agents_dir), claim_created_event),
    )
    owner.start()

    assert claim_created_event.wait(timeout=10)

    # The persisted claim is already durable by the time
    # resume_after_approval() was even invoked (create_exclusive()
    # happens synchronously beforehand) - kill the "crashed" owner now.
    owner.kill()
    owner.join(timeout=10)
    assert not owner.is_alive()

    attempt_repository = RunContinuationAttemptRepository(tasks_dir)
    stuck = attempt_repository.try_load(TASK_ID, RUN_ID, APPROVAL_ID)
    assert stuck is not None
    assert stuck.status is RunContinuationAttemptStatus.CLAIMED

    log_path = tmp_path / "handler_calls.log"
    retry_service = _build_run_service(
        tasks_dir, agents_dir, _ImmediateFinishExecutor(log_path)
    )

    # The OS lock was released (the kernel did this when the process
    # died) - a retry does not hang waiting for it - but the durable
    # CLAIMED record still blocks automatic replay, for the same
    # approval_id...
    with_error = None
    try:
        retry_service.resume_after_approval(RUN_ID, APPROVAL_ID)
    except Exception as exc:  # noqa: BLE001
        with_error = exc
    assert type(with_error).__name__ == "RunContinuationBlockedError"

    # ...and for a different candidate approval_id too, via
    # find_incomplete().
    with_error_different = None
    try:
        retry_service.resume_after_approval(
            RUN_ID, "approval-different-candidate"
        )
    except Exception as exc:  # noqa: BLE001
        with_error_different = exc
    assert (
        type(with_error_different).__name__
        == "RunContinuationBlockedError"
    )

    assert not log_path.exists()
