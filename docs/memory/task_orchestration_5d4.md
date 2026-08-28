---
name: task-orchestration-5d4
description: "5D-4 Task Orchestration stage progress (dependency model, resolver, scheduler, parallel exec, failure recovery)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 409d8a81-f070-40b7-8a2c-35934359f45f
---

5D-4 breaks into: 4A Task Dependency Model → 4B Dependency Resolver → 4C Scheduler → 4D Parallel Execution → 4E Failure Recovery.

**5D-4A COMPLETE**: `TaskStep` in `src/task_plan.py` has `depends_on: list[str] = field(default_factory=list)`, stays `frozen=True`. Chose `list[str]` over `tuple[str,...]` deliberately (user's call) — plan is an internal runtime model, not yet serialized, so full immutability on the list wasn't worth the ripple into converter/tests/serialization. `tests/test_task_plan.py` covers default-empty, declared deps, frozen semantics — 7/7 passing.

**5D-4B COMPLETE**: `src/task_dependency_resolver.py` — `TaskDependencyResolver.resolve(plan) -> list[list[TaskStep]]`. Topologically layers steps into rounds (each round = deps satisfied by earlier rounds, same-round steps are mutually independent — the unit a future parallel scheduler dispatches together). Cycle/self-dependency detection raises `CyclicDependencyError(ValueError)`. `tests/test_task_dependency_resolver.py` 7/7: empty plan, independent-steps-one-round, linear chain, diamond dependency, direct cycle, self-dependency, error-is-ValueError-subclass.

**5D-4C COMPLETE**: chose "方案 A: Scheduler 调 Executor" (user's call). `src/task_scheduler.py` — `TaskScheduler(resolver, executor).run(plan) -> list[str]` calls `resolver.resolve(plan)` for waves, then `executor.execute_steps(wave, plan.task_id)` per wave sequentially, extending results. Scheduler only knows resolver+executor — never touches MessageRouter/AgentMessage, so swapping wave dispatch to parallel (5D-4D) or retried (5D-4E) won't touch this class.

Supporting changes: `TaskPlanConverter.step_to_message(step, task_id) -> AgentMessage` added (`to_messages` now built from it, behavior unchanged); `TaskPlanExecutor.execute_steps(steps, task_id) -> list[str]` added (`execute(plan)` now just calls `execute_steps(plan.steps, plan.task_id)`).

Tests: `tests/test_task_scheduler.py` (4, covers single-wave/dependent-waves/result-merge/empty-plan) + 2 new tests each on converter/executor for the new methods. 354/354 passing repo-wide (excluding pre-existing unrelated subprocess-env failures in test_test_runner.py/test_run_test_tool.py and the missing `anthropic` module collection error).

**5D-4D COMPLETE**: chose "方案 A: Scheduler 负责 wave 并行" (user's call, via AskUserQuestion) over Executor owning a `parallel=` flag — kept Executor single-purpose (dispatch one step) and concurrency-as-scheduling-policy in Scheduler. `TaskPlanExecutor.execute_step(step, task_id) -> str` added (dispatches exactly one step; `execute_steps` is now a sequential fallback built from it; Executor has zero concurrency awareness). `TaskScheduler._run_wave` uses `ThreadPoolExecutor(max_workers=len(wave))`, submits `executor.execute_step` per step, collects `future.result()` in submission order — so within-wave results always match step declaration order even though completion order isn't guaranteed. Waves still run one after another (next wave depends on previous finishing).

Tests: `tests/test_task_scheduler.py` rewritten to 6 tests — single-wave dispatch (asserted via set since concurrent call order isn't deterministic), dependent-steps-separate-waves, within-wave result-order preservation, cross-wave result merge, empty plan, and a real timing test (two 0.2s-sleep independent steps, asserts total elapsed < 0.35s to prove actual parallelism vs ~0.4s sequential). 356/356 passing repo-wide (same pre-existing unrelated failures excluded as before).

**5D-4E phase 1 COMPLETE** (StepExecutionResult + per-step failure capture): chose "只在 Scheduler 层包装" over the user's original suggestion of changing `TaskPlanExecutor.execute_step()` to return `StepExecutionResult` directly (user's call, via AskUserQuestion) — the Executor-return-type change would have broken `tests/integration/test_manager_execution_flow.py` (raw-str result assertions + a `pytest.raises(ValueError)` around `execute()`) since ManagerAgent calls `TaskPlanExecutor.execute()` directly, bypassing Scheduler entirely. Kept `TaskPlanExecutor` **fully untouched** — still returns `str`, still raises on failure. New `src/step_execution_result.py`: `StepExecutionResult(step_id, success, output=None, error=None)`, frozen dataclass, positioned as a workflow/Scheduler-level concept not a dispatch-level one.

`TaskScheduler._run_wave` now pairs `(step, future)`, wraps each `future.result()` in try/except, converts to `StepExecutionResult` (success or failure with `str(exc)` as error) instead of letting exceptions propagate. `run()` return type is now `list[StepExecutionResult]` (was `list[str]`).

Deliberate scope limit (documented in docstring + a dedicated test `test_run_continues_to_the_next_wave_after_a_failure`): Scheduler still runs every subsequent wave even after an earlier-wave failure — it does NOT check whether a step's dependency actually succeeded before dispatching it. Whether to skip downstream steps after a failed dependency, and retry logic, is left for the next 5D-4E sub-phase.

Tests: `tests/test_step_execution_result.py` (3) + 2 new tests added to `tests/test_task_scheduler.py` (partial-failure-within-a-wave preserves all 3 results in order; failure-then-continue-to-next-wave). 361/361 passing repo-wide (same pre-existing unrelated failures excluded as before).

**5D-4E-2 COMPLETE** (dependency-failure gating): `StepExecutionResult.success: bool` replaced with `status: StepStatus` (enum: SUCCESS/FAILED/SKIPPED) in `src/step_execution_result.py` — safe to change since nothing outside Scheduler/its own tests consumed the old field. `TaskScheduler._run_wave` now checks each step's `depends_on` against `results_by_id` before dispatch: if any dependency's status != SUCCESS (covers both FAILED and SKIPPED), the step is never submitted to the executor at all — it's recorded SKIPPED directly. Multi-level propagation (A fails → B skipped → C skipped) falls out for free from the `!= SUCCESS` check since SKIPPED also fails that check on the next round — no separate propagation logic needed.

Tests: 3 new in `tests/test_task_scheduler.py` (dependency-failure blocks downstream + asserts executor never called for the skipped step; independent step unaffected by a sibling's failure; 3-level chain propagation A→B→C all the way down) + `tests/test_step_execution_result.py` rewritten for the enum (4 tests). 364/364 passing repo-wide (same pre-existing unrelated failures excluded as before).

**5D-4E-3 COMPLETE** (retry abstraction only, no automatic retry): new `src/retry_policy.py` — `RetryPolicy(max_attempts: int = 1)`, frozen dataclass, nothing reads it yet. `StepExecutionResult` gained `attempt: int = 1` (`src/step_execution_result.py`) to distinguish a first-try outcome from a retried one later. Deliberately did NOT touch `TaskScheduler` (no retry loop) or `TaskStep` (no `retry_policy` field wired in yet — that's an optional future step, not done). Tests: `tests/test_retry_policy.py` (3: default, configurable, frozen) + 2 new in `tests/test_step_execution_result.py` (attempt defaults to 1, can be set). 369/369 passing repo-wide (same pre-existing unrelated failures excluded as before).

5D-4E-4 (an actual RetryManager that sits between Scheduler and Executor, executes the retry loop, and wires RetryPolicy onto TaskStep) is the only remaining piece of 5D-4E. Not started. Otherwise 5D-4 Task Orchestration is functionally complete: model → resolver → scheduler → parallel dispatch → failure/skip semantics → retry data model (unused).

**Why:** builds on [[agent_task_run_refactor]] and [[run_event_query_layer_5c5]] — this is the stage after 5C's run/resume/review/inspect layer, moving from "can run agents in sequence" to "understands execution order/parallelism/recovery."
**How to apply:** when resuming this work, check `src/task_plan_executor.py` and `src/task_plan_converter.py` first to see how far the resolver/scheduler work has progressed before assuming a stage is unstarted.
