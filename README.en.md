# Claude Agent Platform

A private Python platform for managing a "Task → Plan → Run → Agent" workflow. Agents execute tasks through the Anthropic Claude API and **can actually call tools** (read files, list directories, check git status/diff; certain Agents can also create/modify files and run restricted test commands) rather than just guessing an answer from a static snapshot. High-risk tool calls, file changes produced by a Run, and blocking failures during plan execution each go through their own independent human-approval gate.

> Early prototype stage, personal project, iterating quickly. This README has two parts: **Part 1** is a hands-on guide to setting up and using this multi-agent platform; **Part 2** is the current engineering status — what's done, what's in progress, and what's planned next.

---

# Part 1: Setup & Usage Guide

## 1. Core Concepts

The platform organizes work around four entities:

- **Task**: A long-lived unit of work, e.g. "review the project architecture." A Task can contain multiple Runs, which share a single `background.md` (task background that accumulates as each Run completes).
- **Agent**: A reusable execution role configuration — system prompt, default model, resource limits (token/memory/timeout), and a tool-permission policy (`tool-policy.json`). An Agent isn't bound to a single Task; it can be reused across multiple Tasks over time (`agents/agent-general`, `agents/agent-coder`).
- **Run**: One concrete execution under a Task. Each Run has its own input (`input.md`), output (`output.md`), and summary (`summary.md`), executed by a single Agent, which may make multiple rounds of tool calls during execution and may pause if it trips an approval gate.
- **TaskPlan**: A Task can first be broken down by the `ManagerAgent` into a multi-step plan with dependencies (each step assigned to a specific Agent), which, once approved by a human, is scheduled and executed in dependency order. This is a layer of orchestration above "one Run runs one tool-calling loop," used to decompose complex work that needs multiple Agents collaborating.

## 2. Two Execution Modes

Controlled by `EXECUTION_MODE` in `.env`:

| Mode | Description |
|---|---|
| `simulated` | Calls no model at all; `SimulatedRunExecutor` produces deterministic placeholder output. Used to exercise the pipeline and write tests without spending API credits. |
| `llm` | Makes real calls to the Anthropic API (`claude-sonnet-5`); Agents can use real tools to execute multi-round tasks. |

## 3. Installation & Configuration

```bash
# 1. Create a virtualenv and install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# pytest isn't in requirements.txt yet, install it separately
.venv/bin/pip install pytest

# 2. Configure environment variables
cp .env.example .env
# Edit .env: at minimum, fill in ANTHROPIC_API_KEY for llm mode
```

**Environment variables** (see `.env.example`; all have defaults, `ANTHROPIC_API_KEY` is required in `llm` mode):

| Variable | Default | Description |
|---|---|---|
| `EXECUTION_MODE` | `simulated` | `simulated` or `llm` |
| `LLM_PROVIDER` | `anthropic` | Only `anthropic` is supported today |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | |
| `LLM_TIMEOUT_SECONDS` | `60` | |
| `LLM_MAX_RETRIES` | `2` | |
| `LLM_MAX_TOKENS` | `4096` | Output cap per round; bump to 16000+ to leave room for thinking |
| `LLM_MAX_TOOL_ROUNDS` | `8` | Max tool-calling rounds allowed per Run |
| `LLM_MAX_TOTAL_TOKENS` | `100000` | Total token cap for a Run (across all tool-calling rounds) |
| `DEBUG_LOG_FULL_OUTPUT` | `false` | When `true`, `tool_result` events in `events.jsonl` also include the tool's full output |
| `TEST_POLICY_PATH` | `src/config/test_policy.json` | Path, relative to `project_root`, to the `run_test` command whitelist file |

## 4. Command Reference

All commands are `python -m src.main <command> ...` (the `.venv/bin/` prefix is omitted below). Grouped into five workflows.

### 4a. Basics: create and execute

```bash
# List all tasks
python -m src.main list

# Create a new Task and its first Run (does not execute it)
python -m src.main init-task <task-id> <agent-id> "<title>" \
  --description "<description, defaults to the title>" \
  --input "<input text for the first Run, defaults to the title>"

# Execute a task's current Run
python -m src.main run <task-id>

# Resume a Run stuck in in_progress/interrupted (creates a new Run to retry, never reuses the old run_id)
python -m src.main resume <run-id>
```

### 4b. Plan orchestration & approval (Plan level, before execution)

Breaking a Task into multiple steps assigned to different Agents requires human approval before it's actually scheduled:

```bash
# Generate a pending TaskPlan for a Task (generates only, does not execute)
python -m src.main plan <task-id> "<describe the work in natural language>"

# List all plans awaiting approval
python -m src.main plans

# Approve and execute immediately (if the whole plan succeeds, this triggers task completion)
python -m src.main approve-plan <task-id>

# Reject, without executing
python -m src.main reject-plan <task-id>
```

### 4c. Change review (Run level, after execution)

When a Run finishes normally and actually changed files (today only `agent-coder` triggers this), it stops at `awaiting_review` for a human to confirm, instead of going straight to `completed`:

```bash
# See what files a Run changed and its test results, then approve/reject
python -m src.main review <run-id>
```

### 4d. Tool-call approval (ToolCall level, during execution)

Before a tool configured as "requires approval" is actually invoked, the Run pauses in place (state becomes `waiting_for_approval`); once a human makes a decision, `resume-after-approval` **continues the same Run** (it never creates a new one). The gate's rules come from `src/config/approval_policy.json`, which defaults to an empty rule list (nothing configured means nothing ever triggers this gate — identical to behavior before this gate existed).

**Step 1: configure which tools require approval** (`src/config/approval_policy.json`; `tool_name` must be a real, registered tool name):

```json
{
  "rules": [
    {
      "tool_name": "write_file",
      "risk_level": "medium",
      "reason": "writes files inside the repository"
    }
  ]
}
```

`risk_level` must be one of `low`/`medium`/`high`. Any malformed rule (an unknown tool name, a mistyped risk level, a duplicate `tool_name`, an empty `reason`) fails loudly before the Run even starts — it never silently degrades into an empty policy. This configuration is **fixed** for the lifetime of a Run: at start, the rules in effect are snapshotted into `tasks/<task-id>/runs/<run-id>/approval_rules.json`, so even if `approval_policy.json` is later edited or deleted, `resume-after-approval` continuing this Run reads its own snapshot, never the changed live config.

**Step 2: start a Run that will trip the gate** (here, `agent-coder` is asked to write a file):

```bash
python -m src.main init-task task-20260101-001 agent-coder "write a file" --input "create greeting.txt with content 'hi'"
python -m src.main run task-20260101-001
```

The output shows `Status: waiting_for_approval`, an `Approval ID`, and a reminder of exactly which commands to run next.

**Step 3: inspect and decide**:

```bash
# List all pending tool-call approval requests (optionally filtered by --run-id)
python -m src.main list-tool-approvals [--run-id <run-id>]

# Show safe metadata for one approval request: tool name, risk level, reason, input preview
# (only reviewed-safe fields — e.g. write_file shows path but never content), whether it's been
# decided, and whether it's been applied/continued yet
python -m src.main show-tool-approval <approval-id>

# Record a human decision (records only — does not execute the tool or resume the Run)
python -m src.main approve-tool-call <approval-id> [--explanation "..."]
python -m src.main reject-tool-call <approval-id> [--explanation "..."]
python -m src.main modify-tool-call <approval-id> --modified-input-file <path.json>
python -m src.main cancel-tool-call <approval-id> [--explanation "..."]
```

`modify-tool-call` deliberately requires the replacement tool input to be passed as a JSON file (`--modified-input-file`) rather than a raw command-line JSON string, so it never ends up in shell history. What each decision actually does (only takes effect at the next `resume-after-approval` step): `approve` runs the tool exactly as proposed; `modify` runs it with the file's content as a **complete replacement** input (never merged with the original); `reject` never runs the tool, and continues the conversation with a fixed rejection result instead; `cancel` terminates the whole Run (state becomes `cancelled`) — no further tool calls or model requests ever happen.

**Step 4: explicitly continue** (both IDs matter — `approval-id` must be the one this decision actually belongs to; passing the wrong one never silently resumes some other pending approval instead):

```bash
python -m src.main resume-after-approval <run-id> <approval-id>
```

Possible outcomes:
- `Continued run ... Status: completed` (or `awaiting_review`) — finished.
- `Continued run ... Status: cancelled` — corresponds to `cancel-tool-call`.
- `Continued run ... Status: waiting_for_approval` with a **new** `Approval ID` — a later tool call in the same Run also tripped a rule; repeat steps 3–4 for this new approval (retrying the earlier, already-resolved approval_id just replays its own earlier recorded outcome — it never touches the new one).
- `Replayed an earlier completed continuation ...` — this approval's continuation already ran to completion before; this call only replays the recorded outcome, without re-executing any tool or calling the model again.
- An error mentioning "an incomplete continuation attempt" / "already owned elsewhere" — this Run's continuation is either currently owned by another process, or an earlier continuation attempt was interrupted partway through. Neither case is retried or expires automatically — it needs a human to confirm what actually happened before deciding what to do next (not to delete any claim file, and not to use the plain `resume` command to bypass this — `resume` performs the exact same check and cannot be used to get around it either).

### 4e. Query & diagnostics (read-only)

```bash
# List all Runs across all Tasks
python -m src.main runs

# View a single Run's timeline (every LLM call/tool call), changes, and test results
python -m src.main inspect <run-id>
```

> The platform actually has **three** different human-in-the-loop gates at different granularities, which are easy to confuse: **plan approval** (4b, before execution, decides "should this plan run at all"), **change review** (4c, after execution, decides "should this Run's changes be accepted"), and **tool-call approval** (4d, during execution, decides "can this specific tool call go ahead"). There is also a fourth gate, **runtime approval** (triggered when a step fails during plan scheduling and is classified as `BLOCKED`, persisted in `tasks/<task-id>/runtime_approval.json`), which currently has no CLI at all and can only be driven via code/tests — see "Future Plans" in Part 2.

## 5. Project Structure

```
src/
├── models.py                  # Domain models: TaskDefinition / RunDefinition / AgentDefinition / ...
├── repositories.py             # Persistence layer: reads/writes JSON/Markdown/JSONL files (no database)
├── run_service.py              # Orchestrates a Run's full lifecycle (execute/resume/resume_after_approval)
├── run_query_service.py        # Read-only query side: list_runs()/inspect_run()
├── llm_executor.py             # LLMRunExecutor: multi-round tool-calling loop, returns LLMRunResult
├── llm_agent_run_executor.py   # Adapter layer wiring Task/Run/Agent into LLMRunExecutor
├── run_events.py               # Real-time events.jsonl writer (RunEventSink protocol)
├── llm/                        # Provider-agnostic request/response types + the Anthropic implementation
├── domain/tools/                # ToolDefinition / ToolCall / ToolResult
├── domain/events/                # RunEvent / EventRepository / TimelineBuilder
├── services/tools/                # Tool dispatch, policy, restricted test execution, the seven tool handlers
├── review/                      # Run-level human review: ChangeSnapshot / review_policy / ReviewService
├── approval_*.py / tool_approval_*.py / run_continuation_*.py
│                                 # Tool-call-level human approval gate + Run continuation checkpoint (see Part 1, 4d)
├── run_service_composition.py  # The single production composition root for this gate (every CLI command goes through here, nothing is reassembled per-command)
├── schema_aware_tool_input_previewer.py  # Per-tool, hand-reviewed safe previews — never falls back to dumping the whole input
├── process_file_lock.py        # A process-level file lock (fcntl.flock), mutually exclusive per run_id
├── agent_registry.py / message_router.py        # Agent discovery + message delivery
├── task_plan.py / task_dependency_resolver.py / task_scheduler.py
│                                 # TaskPlan model + dependency ordering + scheduling + retries
├── agents/                       # Task-Scoped Agent lifecycle: Template/TaskAgent/Registry/...
├── context/                      # ContextSelector/ContextTrimmer (static context) + history/ (conversation history compression)
├── planning/                     # Planner protocol, ClaudePlanner, PlanValidator, PlanRepairLoop, ...
├── recovery_*.py / execution_checkpoint*.py / runtime_approval_*.py
│                                 # The recovery decision chain after a plan-execution failure (RETRY/REPAIR_PLAN/REQUEST_APPROVAL/ABORT)
└── cli/                          # Pure display layer: formats strings, never prints, no business logic
```

Configuration and data directories:

```
agents/<agent-id>/
├── agent.json / system-prompt.md / tool-policy.json

src/config/
├── test_policy.json       # run_test's command whitelist
└── approval_policy.json   # tool-call approval rules (empty rule list by default — see Part 1, 4d for a worked example)

tasks/<task-id>/
├── task.json / background.md / plan.json / approval.json / runtime_approval.json / checkpoint.json
├── approvals/<approval-id>/
│   ├── request.json / resolution.json   # ApprovalRequest / the recorded human decision
│   └── application.json                 # ApprovalApplicationService's execution result (claim + outcome)
└── runs/run-NNN/
    ├── run.json / input.md / output.md / summary.md
    ├── approval_rules.json      # the approval rules in effect when this Run started (continuation reads this, not the live config)
    ├── checkpoint.json          # the RunContinuationCheckpoint at the moment of pausing (messages + pending tool calls)
    ├── continuation_attempts/<approval-id>.json  # the claim + result for each resume-after-approval attempt
    ├── continuation.lock        # this Run's process-level file lock (fcntl.flock — not a data file)
    ├── events.jsonl            # per-round audit events, appended in real time
    └── change_snapshot.json    # ChangeSnapshot (what the review command reads)
```

## 6. Running Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

> `pytest` needs to run in the same environment (`.venv`) that has `anthropic`/`python-dotenv` installed, otherwise tests touching the Anthropic Provider will fail to collect with `ModuleNotFoundError`.

## 7. How to confirm a real tool call actually happened

Unit tests all use a `FakeProvider`, which proves `LLMRunExecutor`/`ToolExecutor`'s own logic is sound, but **cannot prove** that a tool call actually happened against the real Anthropic API in a given Run — the model's final answer text is not trustworthy evidence by itself. Verification methods from weakest to strongest:

1. **Cross-check content**: compare what the model claims a tool returned against running the same thing manually (e.g. compare `ls -a .` against `list_files`'s result).
2. **Design a "forced dependency" task**: make a later tool call's parameters depend on the real return value of an earlier one, where that value is something the model couldn't have guessed in advance (e.g. "list a directory, then read the Nth file alphabetically," where N has to skip over a `__pycache__/` that only exists at runtime).
3. **Add temporary round-level logging**: inside `LLMRunExecutor.execute()`'s loop (`src/llm_executor.py`), temporarily print each round's `response.stop_reason`/`tool_calls` — these are raw API fields the model can't fabricate. Remember to remove the logging afterward.
4. **The Anthropic console**: https://console.anthropic.com's Usage/Logs pages show whether a given API key's requests actually included `tools` and whether responses contained `tool_use` — third-party evidence independent of this project's own code.

The most reliable combination is 2 + 3. This method has been used to verify a complete autonomous fix loop of `read_file` → `patch_file` → `run_test` (`tasks/task-run-test-loop`'s run-001: `add()` was deliberately broken so a test failed, and the model was only told "a test is failing, fix it" — it read the files, located the bug, patched it, and ran the test to confirm, with no hints given about the answer).

---

# Part 2: Project Status

## Done

| Stage | What's there |
|---|---|
| **Tool-calling foundation** (5B) | Four read-only tools — `list_files`/`read_file`/`git_status`/`git_diff`; `PathGuard` enforcing repository boundaries; `LLMRunExecutor` implementing the "request model → execute tool → feed result back → request again" loop (with `max_tool_rounds`/`max_total_tokens` safety limits); real-time audit events in `events.jsonl` (`llm_response`/`tool_call`/`tool_result`/`run_completed`/`run_failed`); the Run state machine extended with `interrupted`/`failed`, with a `resume` command that creates a new Run to retry a crashed state. |
| **Write capability & autonomous fix loop** (5C) | Three tools — `write_file` (create/overwrite, atomic write + sha256), `patch_file` (unique-match text replacement sharing the same write kernel), `run_test` (whitelisted commands, `shell=False`, a failing test does not count as a tool failure) — enabled only for `agent-coder`; `file_mutation` audit events; **Run-level human review** — `ChangeSnapshot` + the `awaiting_review` state + the `review` command (approve/reject); a read-only **query side** — `RunQueryService` plus the `runs`/`inspect` commands, fully separated from the execute/review command side. Verified end-to-end against the real API multiple times, including a complete read-file → fix-code → run-test → confirm-pass loop. |
| **Task orchestration** (5D) | `ManagerAgent` decomposes a request into a `TaskPlan` with dependencies; `PlanValidator` checks it (unknown agent / not assigned / missing dependency / dependency cycle); **plan-level human approval** via the `plan`/`plans`/`approve-plan`/`reject-plan` commands; `TaskDependencyResolver` topologically sorts dependencies into "waves," `TaskScheduler` runs waves in parallel internally and serially between waves, failures retry through `RetryManager`/`RetryPolicy`, and steps whose dependencies didn't succeed are marked `SKIPPED` outright. |
| **Task-Scoped Agent architecture** (5E-4) | Splits "the reusable Agent asset" (`AgentTemplate`/`AgentDefinition`, global and persistent) from "which Task this Agent currently belongs to" (`TaskAgent`, a temporary per-Task membership record) into two independent lifecycles; four invariants frozen in `docs/architecture/agent_lifecycle_policy.md` and locked by regression tests; `MessageRouter` acts as a second runtime line of defense, refusing to deliver messages to an Agent that's no longer assigned to a given Task. |
| **Claude-based structured planning + plan self-repair** (5E-1~5E-3) | `ClaudePlanner` (actually calls the model to produce a structured `TaskPlan`, satisfying the same `Planner` protocol as `RuleBasedPlanner`, with unit and integration tests, **but not yet set as the default Planner** — it must be injected explicitly); `PlanRepairLoop` — when plan validation fails or an execution-time failure occurs, it auto-generates a repair request, re-plans, and re-validates, up to `max_attempts` times. |
| **Static context optimization** | `ContextSelector`/`ContextTrimmer`/`ContextBudget` — scores files by keyword overlap to select relevant context, replacing the earlier hardcoded set of 5 fixed files; paired with **History Compression** (conversation-history compression, see `src/context/history/`) to address context growing unbounded across multi-round tool calls. |
| **Execution recovery & replanning** (5E-5) | The full failure-decision chain `FailureClassifier` → `RecoveryPlanner` → `RecoveryOrchestrator` → `RecoveryExecutor` (`TEMPORARY_ERROR` → retry, `PLAN_ERROR` → replan, `BLOCKED` → human approval, `FATAL` → abandon); a runtime approval gate (`runtime_approval.json`); `TaskPlanResumeService`, which strips completed steps from a checkpoint, rewrites dependencies, and continues scheduling. The whole chain has integration-test coverage, **but is not wired into any CLI command yet** — it can only be driven via code/tests. |
| **Tool-call-level human approval gate + Run continuation** (5E-5D-6) | Full usage walkthrough in Part 1, 4d. Summary: `RuleBasedToolApprovalPolicy` (an `ApprovalRule`: tool name + risk level + reason, sourced from `src/config/approval_policy.json` and fully validated by `approval_policy_config.py`) decides whether a `ToolCall` needs human approval; on a match, `ToolApprovalGate` intercepts inside the tool-calling loop, creates an `ApprovalRequest`, and persists the full context at the moment of pausing into a `RunContinuationCheckpoint` (`run_id`-scoped — a different, non-shared model from the plan-level `ExecutionCheckpoint`, which is `task_id`/`plan_id`-scoped); the Run's state becomes `waiting_for_approval`. The `approve/reject/modify/cancel-tool-call` commands only record a decision (`ApprovalDecisionService`); `list/show-tool-approval` provide read-only queries (`SchemaAwareToolInputPreviewer` hand-reviews, per tool schema, which fields are safe to display — an unknown tool or an unreviewed field is always explicitly reported as "omitted," never falls back to `repr()`/`json.dumps()` of the whole input). `resume-after-approval <run-id> <approval-id>` drives `ApprovalContinuationPreparationService` (validates all four records are still consistent) + `ApprovalApplicationService` (actually executes or skips the tool) to continue the same Run — it may pause again with a new `ApprovalRequest`, or finish normally. `RunContinuationAttemptRepository` + `process_file_lock.py` (an `fcntl.flock` process-level lock, mutually exclusive per `run_id`, paired with persisted `CLAIMED`/`COMPLETED` records — the lock excludes *live* concurrent races, the records block *automatic replay* after a crashed process) together guarantee a Run's continuation can't be duplicated or bypassed. `run_service_composition.py` is the single production composition root — `ApprovalApplicationService`'s `ToolExecutor` uses exactly the same workspace/ToolPolicy/tool registry as the executor actually continuing that Run. `_LazyLLMProvider` defers Anthropic credential validation until a request is actually about to be sent, so `--help`, read-only queries, recording a decision, replaying an already-completed continuation, and CANCEL all work with no API key configured. |

Roughly **1500+ tests** (`pytest tests/` passes in full; run it as `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest tests/` so that the `run_test` tool's own subprocesses can find a working `python` — otherwise a handful of unrelated subprocess tests fail purely from a `PATH` environment issue, not from this code).

## Future Plans / Known Limitations

- Runtime approval (`runtime_approval.json`, triggered by a `BLOCKED` failure during plan scheduling) still has no CLI command — the platform now has three human gates wired into the CLI (plan / change / tool-call); this fourth one isn't yet.
- The execution-recovery layer (`RecoveryOrchestrator`/`RecoveryExecutor`) has no CLI integration at all; `RecoveryAction.ABORT` currently just silently skips, with no real termination logic; there's no `CheckpointWriter` — no production code automatically generates an `ExecutionCheckpoint` after plan execution, so the recovery path works but triggering it requires manually constructing a checkpoint.
- `ClaudePlanner` is implemented and fully tested, but `ManagerAgent` still defaults to `RuleBasedPlanner` — no production path automatically uses real model-based planning.
- `patch_file` can only replace a single, exactly-matched block of text — it doesn't support applying a multi-hunk unified diff in one call; `write_file` has no append capability.
- The tool-call approval gate's persistence (claim files, continuation-attempt records) is all plain file writes (temp file + `rename`), with no `fsync` — this guarantees surviving a killed/crashed *process*, not a power loss at the exact moment of a write. If a continuation is interrupted between "the process holds the lock" and "marked complete," it leaves a `CLAIMED` record that **permanently** blocks automatic continuation (a deliberate, conservative choice — it never expires or gets taken over automatically); a human has to confirm what actually happened and decide what to do next — there is currently no command or procedure for deleting or taking over a `CLAIMED` record.
- The process-level file lock (`process_file_lock.py`) is based on POSIX `fcntl.flock`, so it only works on Linux/macOS; on an unsupported platform it fails explicitly rather than silently degrading to "no lock at all."
- `run_test` can only run pre-registered whole commands (e.g. `pytest -q`), not a single test file or function.
- No database, and no general multi-process concurrent-write protection (the `process_file_lock` added in this round of changes only fixes one specific race in the continuation scenario, not a general solution).
- The `review` command has no Reviewer Agent and shows no actual diff content (`ChangeSnapshot.diff_path` is always `null` — no code generates `diff.patch`).
- `RuleBasedContextSizeEstimator` only estimates by character-count order of magnitude and only looks at metadata, never file contents — static-context trimming drops whole files by count, not a precise token-budget cutoff.
- `AgentTemplateRepository` is currently an in-memory-only implementation with no persistence — it's lost on process restart.
- Only one LLM provider (Anthropic) is supported; the `LLMProvider` protocol itself is provider-agnostic, so in principle it could be extended to support multiple providers/API keys (not started yet).
- The containerized Agent Runtime prototype (`runtime/` + `scripts/`, an earlier technical-exploration draft) is not yet integrated with the main execution pipeline.
