> Snapshot exported 2026-08-13 from Claude's auto-memory store
> (`~/.claude/projects/-Users-hukaikun-claude-agent-platform/memory/`).
> That location is the live/canonical source and keeps updating every
> session; this copy is a point-in-time export for browsing inside
> the repo and will drift out of date. Re-copy when you want it fresh.

- [Agent/Task/Run refactor](agent_task_run_refactor.md) — RESOLVED: LLMAgentRunExecutor split into src/llm_agent_run_executor.py is done and on main
- [Token usage tracking gap](token_usage_tracking_gap.md) — RESOLVED: LLMRunExecutor now returns cumulative LLMRunResult, not last-round LLMResponse
- [Observability + recovery (5B-5, 5B-6)](observability_stage_5b5.md) — COMPLETE: usage/events.jsonl/CLI summary, run state machine + error classification + resume command
- [write_file tool (5C-1)](write_file_tool_5c1.md) — COMPLETE, superseded by 5C-2: safe write kernel, policy-gated to agent-coder, sha256 file_mutation audit events
- [patch_file tool (5C-2)](patch_file_tool_5c2.md) — COMPLETE, superseded by 5C-3: unique-match text replace, shared file_writer.py kernel
- [run_test tool (5C-3)](run_test_tool_5c3.md) — COMPLETE, superseded by 5C-4: whitelisted-command subprocess runner, verified live as a full read_file->patch_file->run_test fix loop
- [Human review gate (5C-4)](human_review_gate_5c4.md) — COMPLETE, superseded by 5C-5: ChangeSnapshot + awaiting_review status + review CLI (approve/reject)
- [Run event query layer (5C-5)](run_event_query_layer_5c5.md) — COMPLETE: RunEvent/EventRepository/TimelineBuilder + RunQueryService (command/query split) + runs/inspect CLI. Platform now has run/resume/review/runs/inspect.
- [Task Orchestration (5D-4)](task_orchestration_5d4.md) — 4A-4E-3 DONE: model/resolver/scheduler/parallel/skip-gating/RetryPolicy abstraction (unused). Only 4E-4 RetryManager (actual retry loop) left open.
- [Runtime context problem](run_context_builder_token_explosion.md) — ROOT-CAUSED, unfixed: two defects - (A) no ContextSelector, 5 hardcoded irrelevant files; (B) cumulative multi-round token budget, not a single-context-size issue. Fix order agreed, not started.
