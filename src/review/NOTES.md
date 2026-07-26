# Review module design notes

## `ChangeSnapshot.test_results` shape may need to evolve

Current shape (5C-4B), keyed by tool name, one entry per tool:

```json
{
  "run_test": {
    "exit_code": 0,
    "timed_out": false
  }
}
```

This only works because a Run currently calls `run_test` with at most one
meaningfully-tracked result. Once Runs can invoke multiple distinct test
commands (e.g. `pytest`, `compile`, `lint`) and we want to keep each
invocation's result instead of last-call-wins, this dict-keyed-by-tool-name
shape won't hold more than one result per tool.

Possible future shape — a list, one entry per test invocation:

```json
{
  "tests": [
    {"name": "pytest", "exit_code": 0},
    {"name": "compile", "exit_code": 0}
  ]
}
```

Not changing this now — 5C-4's current goal is the minimal end-to-end
review loop, not a fully general test-result schema. Revisit when a Run
actually needs to run more than one distinct test command and surface all
of their results (not just the last `run_test` call's).

## Architecture checkpoint (pre-5C-5), 2026-07-24

Before starting 5C-5, did a deliberate architecture review of the platform
as a whole (not just this module). Three areas checked; findings below.
Not acting on any of them now — recorded so they aren't forgotten.

### 1. `review/` doesn't follow the `domain/` vs `services/` split that `tools/` already established

`src/domain/tools/` holds pure data (`ToolDefinition`/`ToolCall`/`ToolResult`,
no behavior); `src/services/tools/` holds the logic (`ToolExecutor`,
`ToolPolicy`, handlers, `file_writer.py`, `path_guard.py`). `src/review/` is
a single flat package mixing both: `ChangeSnapshot`/`ReviewReport` are pure
data, but `ChangeSnapshotBuilder`/`SnapshotRepository`/`ReviewService`/
`review_policy.py` are logic — all living side by side.

If/when this gets cleaned up, the natural split:
- `domain/review/` — `ChangeSnapshot`, `ReviewReport`
- `services/review/` — `ChangeSnapshotBuilder`, `SnapshotRepository`,
  `ReviewService`, `review_policy.py`

Not done now — purely a consistency nit, not a correctness issue.

### 2. `RunService` is growing into multiple responsibilities

408 lines, 7 methods: `execute`/`resume`/`get_run`/`decide_review`/
`_fail_run`/`_find_task_for_run`/`_next_run_id`. `execute()` alone now does
four things: validate run/agent state → invoke the executor → build the
`ChangeSnapshot` and decide `awaiting_review` vs `completed` → persist and
assemble the result. This was flagged as a risk back in 5C-4A ("RunService
会变胖，但现在不要重构") — it has, in fact, grown since, but not past the
point of being readable.

Natural split if/when it's worth doing:
- `ExecutionService` — `execute`/`resume`/`_fail_run` + the two lookup
  helpers (`_find_task_for_run`/`_next_run_id`)
- a review-gate service — `get_run`/`decide_review`

Caution: `get_run()` is generic (just "find the task+run for this id"), not
review-specific — whichever side ends up owning it, the other will need to
call into it, so this isn't a completely clean cut. Don't split until
there's a second review-adjacent feature (e.g. a Reviewer Agent, or a
`RunStateManager` for more elaborate multi-stage approval) that makes the
current single class genuinely hard to work in — splitting on speculation
now just adds a cross-class dependency for no immediate benefit.

### 3. Agent extensibility: platform layer is clean, one hardcoded coupling point exists

Checked whether adding a new agent (`agent-researcher`, `agent-reviewer`,
`agent-manager`, ...) requires code changes. Good news:
`executor_factory.py`/`context_builder.py` have **zero** hardcoded
`"agent-coder"`/`"agent-general"` references; `AgentRepository.get_agent_dir()`
is pure directory convention (`agents_dir / agent_id`); `AgentDefinition.role`/
`capabilities` are free strings, not a closed enum. Adding a new agent is
structurally just three new files
(`agents/<id>/{agent.json,system-prompt.md,tool-policy.json}`) — no Python
changes needed. Already proven once, when `agent-coder` was added in 5C-1.

Two real gaps found, though:

- **`review_policy.py:11` hardcodes the agent id**:
  ```python
  if agent_id != "agent-coder":
      return False
  ```
  A new write-capable agent (e.g. `agent-researcher` with `write_file`
  enabled in its own `tool-policy.json`) would produce real file mutations
  that **never trigger `awaiting_review`**, because this check is on
  identity, not capability. This is not something that "just works" when a
  new agent is added — whoever adds the next write-capable agent has to
  remember to touch this file too. A capability-based check (e.g. "does
  this agent's tool-policy have any mutation-capable tool enabled") would
  be more robust, but that's a real design decision, not a drop-in fix —
  not changing it now.
- **`AgentDefinition.credential_id`/`default_workspace_id` are parsed but
  never consumed anywhere** outside `models.py`. The schema already
  anticipates per-agent credentials and workspace isolation, but no such
  behavior exists — every agent currently runs under the same
  `ANTHROPIC_API_KEY` from `.env`, with no workspace-level resource
  isolation. If a multi-user/multi-credential setup is ever needed (e.g.
  for `agent-manager` coordinating agents on behalf of different people),
  this needs actual design and implementation, not just "the field is
  already there."
