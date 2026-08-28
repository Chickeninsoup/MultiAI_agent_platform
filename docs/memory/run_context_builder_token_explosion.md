---
name: run-context-builder-token-explosion
description: "Root-caused runtime context problem - two independent defects (context selection + token accounting), diagnosed via 5D-6A CLI smoke test, fix not yet started"
metadata: 
  node_type: memory
  type: project
  originSessionId: 409d8a81-f070-40b7-8a2c-35934359f45f
---

Discovered via a real end-to-end smoke test of the `plan` CLI command (`python -m src.main plan <task_id> "implement a login feature"`): a trivial request hit `Maximum total token limit exceeded` on agent-coder. Full diagnosis is done (read `src/context_builder.py` end to end + measured real output against the live project) - this is now a root-cause record, not just a symptom note.

**Location**: the builder is `src/context_builder.py` (top-level `RunContextBuilder`), not `src/runtime/` - there is no `src/runtime/` directory in this codebase.

**What's actually in context**: NOT the whole repo. `_build_project_snapshot` = a depth-3 project tree (3,618 chars / 178 lines) + the full text of 5 hardcoded files (`DEFAULT_CONTEXT_FILES` in `context_builder.py`: `src/main.py`, `src/models.py`, `src/repositories.py`, `src/run_service.py`, `src/execution.py`). Measured total: **47,886 chars ≈ 12k tokens**. This whole snapshot is embedded in the *first* user message (`llm_agent_run_executor.py`'s `_build_request`), alongside system prompt (~2.3k chars) and tool policy (~0.5k chars).

This is root-caused as **two independent defects**, not one "context explosion" - fixing only one leaves the other live:

**Defect A - Context Selection**: the 5 context files are hardcoded and have zero relationship to the task (`main.py`/`run_service.py` for a "login feature" request). `run.metadata["context_files"]` exists as a manual override path (with real path-safety validation in `_validate_context_path`) but nothing ever populates it automatically - there is no `ContextSelector`. Every run gets the same irrelevant ~12k-token dump regardless of what it's actually about.

**Defect B - Token Accounting**: `LLMRunExecutor` (`src/llm_executor.py:88-132`) checks `total_input_tokens + total_output_tokens > self._max_total_tokens` (default 100k, from `settings.llm_max_total_tokens`) as a **cumulative sum across every tool-use round**, and each round resends the *entire* growing `messages` history (the loop does `current_request = replace(request, messages=list(messages), ...)`). So the ~12k-token snapshot gets re-billed on every single round, compounding with tool results - a handful of read_file/list_files calls (which the agent is explicitly told to make when "the supplied project snapshot is insufficient" - true almost by construction here, since the snapshot is task-irrelevant) is enough to blow through 100k even though no single round's context is large. **`agent-coder.limits.max_input_tokens=50000` is a red herring** - it's not what this error path checks; that field only feeds into the `max_tokens` response-size parameter (`llm_agent_run_executor.py:221`), not this budget.

**Why:** surfaced by 5D-6A's [[task_orchestration_5d4]]-adjacent CLI integration (`src/main.py` `plan_task()`), which exercised the real `agent-coder` handler through `RunService.execute()` for the first time outside of Fake-agent tests.

**How to apply / planned fix order** (agreed with user, not started yet): git checkpoint first, then Context Runtime Fix as its own stage - (1) a real ContextSelector to replace the hardcoded file list, (2) a *per-request* context budget (cap what goes into any single message), while (3) deliberately KEEPING the existing cumulative run-level `max_total_tokens` check as-is - it's a legitimate cost/runaway-loop guard, not the bug, and must not be deleted while fixing Defect A/B. Then (4) a real smoke test to confirm. RetryManager (5D-4E-4) comes after this, not before.
