---
name: observability-stage-5b5
description: "Stage 5B-5 (observability/audit, 5A-5E) and 5B-6 (Run recovery/failure-state policy) both COMPLETE — cumulative usage, real-time events.jsonl, structured CLI summary, run state machine (in_progress/completed/interrupted/failed), error classification, resume command"
metadata: 
  node_type: memory
  type: project
  originSessionId: 84526302-59c2-4874-af7e-0eda41019e28
---

The user worked through a numbered staged plan for this AI agent platform (branch `refactor/agent-task-run-model`). Stage 5B-5 (observability, 5 sub-parts) is done; stage 5B-6 (Run recovery & failure-state policy) is also done as of 2026-07-23.

## Stage 5B-5 (observability) — summary, see git history for full detail
Cumulative `LLMRunResult` usage (5A), real-time `events.jsonl` via `RunEventSink`/`JsonlRunEventSink` (5D, superseding an earlier batch-write 5B design), `duration_ms`/error-code taxonomy on `ToolExecutor` (5C), structured `RunServiceResult`/`RunExecutionFailedError` CLI summary instead of ad-hoc prints (5E).

## Stage 5B-6 (Run recovery & failure-state policy) — done 2026-07-23

**State machine**: `in_progress → completed` (normal) / `in_progress → interrupted` (retryable failure) / `in_progress → failed` (not retryable). No `pending` state exists yet — runs are still hand-created directly as `in_progress` (there's no formal "create run" CLI command in this codebase; see [[agent-task-run-refactor]] for the manual run-NNN workflow used throughout this session). `interrupted → failed` ("abandon") is allowed by the model but has no CLI verb yet — manual `run.json` edit only.

**Error classification** (`src/run_errors.py`): `classify_error(exc) -> RunErrorCategory` (`Literal`, not Enum — matches this codebase's style of using `Literal` type aliases like `ExecutionMode` rather than `enum.Enum`), `is_retryable(category) -> bool`. Six categories, retryability confirmed by the user (recommended defaults accepted as-is): `LIMIT_EXCEEDED` (LLMRunLimitError) retryable, `PROVIDER_ERROR` (LLMRateLimitError/LLMConnectionError/LLMProviderError) retryable, `INTERRUPTED` retryable (set only by `resume`, never by `classify_error` — there's no exception for "process got killed"), `TOOL_ERROR` retryable-by-default but **currently unreachable** (ToolExecutor never lets exceptions propagate — always converts to failed ToolResult — so nothing is ever classified into this bucket today), `CONFIGURATION_ERROR` (LLMAuthenticationError/LLMConfigurationError/LLMPermissionError) NOT retryable, `INTERNAL_ERROR` NOT retryable (catch-all, including `LLMRequestError`).

**`RunService` changes** (`src/run_service.py`): `execute()` now only proceeds if `run.status == "in_progress"` (previously just checked not-completed) — re-running an `interrupted`/`failed` run via `run <task-id>` is now rejected with a message pointing at `resume`. On executor exception, `_fail_run()` classifies it, persists `run.json` with `status` set to `interrupted`/`failed` plus `metadata.error_category`/`error_message`/`retryable`, then raises `RunExecutionFailedError` (now carries `category`/`retryable` in addition to the 5E fields).

New `RunService.resume(run_id) -> RunServiceResult`:
1. `_find_task_for_run(run_id)` — **scans all tasks' `runs/` dirs** (`RunRepository.list_run_ids()`) since a bare run_id doesn't say which task owns it. O(n) in run count; documented as a known limitation, acceptable at current scale.
2. Only `{"in_progress", "interrupted"}` (module constant `RESUMABLE_STATUSES`) may be resumed.
3. If still `in_progress` at resume time (crash detection — a live process would have transitioned it), first flip it to `interrupted`.
4. **Chosen design was option B from the user's own proposal**: never reruns the same run_id. Creates a brand new run via `_next_run_id()` (scans existing `run-NNN` dirs, zero-padded, next sequential — not based on `task.run_count` in case that ever drifts), sets `metadata={"retry_of": old_run.id}`, copies `input.md` verbatim (`RunRepository.write_input()`, new method), updates `task.json.current_run_id`/`run_count`.
5. Immediately calls `self.execute(task.id)` on the new run (confirmed by the user: resume actually executes, not just stages a new run stub).

**`main.py`**: new `resume` subcommand (`python -m src.main resume <run-id>`) → `resume_run()` → shares `_print_run_result()` with `run_task()`. Failure printing now includes `Category: <X> (retryable: <bool>)` and, when retryable, a `Retry with: python -m src.main resume <run_id>` hint.

**Real E2E verification**: run-023 (a genuinely stuck `in_progress` run left over from *before* this feature existed — used as an authentic crash-detection test, not synthetic) → `resume run-023` correctly flipped it to `interrupted` and created run-024 (`retry_of: run-023`, same input.md, executed successfully). Separately, run-025 forced via `LLM_MAX_TOOL_ROUNDS=1` → confirmed real `LIMIT_EXCEEDED`/`interrupted`/`retryable: true` end to end, then `resume run-025` → run-026 (`retry_of: run-025`) completed normally, and run-025 itself was left untouched (not re-flipped) since it was already `interrupted`, not `in_progress`, at resume time.

**Why:** the user is building this incrementally, always wants real-CLI proof before moving to the next stage (see [[agent-task-run-refactor]]). Retryability defaults and the crash-detection/full-execution design choices were explicitly confirmed by the user rather than assumed.

**How to apply:** if extending further (e.g., a `pending` state, an `abandon` CLI verb, or making `TOOL_ERROR` reachable), keep the `Literal`-based category style and the "each Run = one attempt, retries are new Runs with `retry_of`" invariant — don't reintroduce same-run-id reruns.
