---
name: run-event-query-layer-5c5
description: "Stage 5C-5 (A-D) COMPLETE: RunEvent/EventRepository/TimelineBuilder (domain layer) -> RunQueryService (command/query split from RunService) -> runs/inspect CLI commands with a separate pure-function display layer. Next stage not yet defined."
metadata:
  node_type: memory
  type: project
  originSessionId: f3032f95-4fae-4ce6-8128-c86c03e5234d
---

Continuation of [[human-review-gate-5c4]]. Same workflow (sub-stage → tests + compileall → real-data smoke test → ask before commit/push). All of 5C-5A–D done 2026-07-24/26, single commit `57941b2` ("feat: add run event query/inspection layer (5C-5)"), pushed to `origin/main`.

## What was built

- **`src/domain/events/`** (new domain package, alongside the existing `domain/tools/`): `run_event.py` (`RunEvent` — `event_type`/`timestamp`/`run_id`/`data: dict[str, Any]`, `data` keeps the *full* raw JSON payload, not a stripped subset, specifically so future consumers like a Reviewer Agent aren't limited by what this layer decided to keep), `event_repository.py` (`EventRepository.load_events(events_path, run_id) -> list[RunEvent]` — missing/empty file → `[]` not an error, missing `"type"` key → falls back to `"unknown"`, blank lines skipped), `timeline.py` (`RunTimeline(run_id, events)`, pure wrapper), `timeline_builder.py` (`TimelineBuilder.build()` — deliberately does **not** sort or reinterpret anything, just wraps the list as-is).
- **`RunQueryService`** (`src/run_query_service.py`, flat top-level file — matches the existing `run_service.py`/`run_errors.py`/`run_events.py` convention, *not* a new `runs/` package as the user's draft spec suggested; pointed this out explicitly and it stuck). Explicit **command/query split**: `RunService` executes and mutates state, `RunQueryService` only reads (`list_runs()`, `inspect_run()`) and never touches either. Deliberately does **not** share `RunService`'s private `_find_task_for_run` — reimplements the same few-line scan independently, since the query side shouldn't depend on the command side. `inspect_run()` returns `RunInspection` (small dataclass living in the same file, same precedent as `RunServiceResult` in `run_service.py`) combining `run.json` + a `RunTimeline` (built from `events.jsonl`, `[]` if missing) + a `ChangeSnapshot | None` (via `SnapshotRepository`, `None` if never persisted, e.g. any Run from before 5C-4C).
- **New CLI commands**: `python -m src.main runs` (all runs across all tasks; "N files changed" per run comes from `run.json`'s already-persisted `metadata.changed_files`, not a fresh `ChangeSnapshot` load — keeps listing cheap) and `python -m src.main inspect <run-id>` (timeline + changes + test results for one run). Display formatting lives in **`src/cli/run_display.py`** (new `src/cli/` package) as pure functions (`format_run_list()`/`format_run_inspection()` — data in, `str` out, no printing, no I/O) — kept deliberately separate from the domain/query layers specifically so a future Web UI/bot/API could reuse `RunQueryService` without inheriting the CLI's text formatting. This is where the "how do we display a `file_mutation` vs `tool_call` event" interpretation logic lives — intentionally *not* in `TimelineBuilder`, which stays dumb by design (confirmed correct by the user, framed as "don't let Timeline reinterpret events, that's a different layer's job").

## Real bug/gap found during this stage (not fixed, documented)

**`RunEvent.timestamp` is always `None` in practice** — checked real `events.jsonl` data and confirmed no event has ever had a `timestamp` field; `llm_executor.py` orders by `round`, not wall-clock time. `TimelineBuilder` was designed around this from the start (no sorting, relies on `events.jsonl`'s natural append order) rather than being retrofitted after discovering the gap — the user had already flagged this exact issue as a design constraint before 5C-5C started (see prior turn), so this stage's `TimelineBuilder` correctly avoided the trap of sorting by a field that's always `None`.

## `src/review/NOTES.md` — pre-5C-5 architecture checkpoint (recorded only, no code changes)

Before starting 5C-5, did a deliberate architecture review at the user's request, appended three findings to `src/review/NOTES.md` (not a new file — same doc used for the 5C-4B test_results shape note):
1. `review/` doesn't follow the `domain/`-vs-`services/` split that `tools/` already established (mixes `ChangeSnapshot`/`ReviewReport` data classes with `ChangeSnapshotBuilder`/`SnapshotRepository`/`ReviewService`/`review_policy` logic in one flat package). Suggested split if ever done: `domain/review/` for data, `services/review/` for logic.
2. `RunService` is accumulating responsibilities (408 lines, 7 methods spanning execution/resume/failure-classification/review-gate-decisions). Natural split if ever done: `ExecutionService` vs a review-gate service, but `get_run()` is genuinely shared/generic so the cut isn't perfectly clean — not worth doing speculatively.
3. **The one real coupling point**: `review_policy.py:11` hardcodes `if agent_id != "agent-coder": return False` — a future write-capable agent (e.g. `agent-researcher`) would silently never trigger `awaiting_review` unless someone remembers to update this string by hand. Also noted: `AgentDefinition.credential_id`/`default_workspace_id` are parsed but never consumed anywhere in the codebase — schema anticipates multi-credential/multi-workspace but no such behavior exists.

Also confirmed as a *positive* finding during that review: `executor_factory.py`/`context_builder.py` have zero hardcoded agent-id references, `AgentRepository` is pure directory convention — adding a new agent type is structurally just 3 new files, no Python changes, already proven once with `agent-coder`.

## Known non-bug quirk re-confirmed during real-data verification

The `run_id`-only-unique-within-a-task collision (`resume`/`review`/`get_run`/`inspect` all resolve to the alphabetically-first task containing a matching run_id) was hit again during manual `inspect run-001` testing — same pre-existing behavior documented since 5C-4D, not new. A stale README reference to `tasks/task-5c4d-review-cli-verification/background.md` (a manual-verification doc from 5C-4D that the user later deleted from disk, chose not to recreate) was caught and removed from the known-limitations bullet during this stage's README pass — worth knowing that doc no longer exists if anything else ever cites it.

## Status: platform now has the full command set the user outlined

```
python -m src.main run       # execute
python -m src.main resume    # recover
python -m src.main review    # approve/reject
python -m src.main runs      # query
python -m src.main inspect   # diagnose
```

## What's next

No next stage specified yet as of this memory's writing. Likely candidates based on accumulated `NOTES.md`/README known-limitations: a Reviewer Agent to fill `ReviewReport.summary`/`risks` (explicitly deferred since 5C-4), actual diff generation (`ChangeSnapshot.diff_path` is always `null` today, nothing writes `diff.patch`), or finally wiring `approved` runs to a real `git commit`. Also on the table per the architecture checkpoint: the `review/` domain/services split, or fixing `review_policy.py`'s hardcoded agent id to be capability-based instead of identity-based — both explicitly deferred, not urgent.
