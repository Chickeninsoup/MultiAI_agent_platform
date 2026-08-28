# Agent Lifecycle Policy

Status: **frozen** (5E-4E-2). This document does not introduce new
behavior — it records invariants that stages 5E-4A through 5E-4E-1A
already established in code, so future changes can be checked against
a fixed reference instead of re-deriving intent from the diff history.

## Overview

The system separates four distinct concepts that are easy to
conflate because they all answer some version of "which agent":

| Concept | Class | Scope | Owner |
|---|---|---|---|
| AgentTemplate | `src/agents/agent_template.py` | Global, persistent | User |
| AgentDefinition | `src/models.py` | Global, persistent | User / `AgentRegistry` |
| TaskAgent | `src/agents/task_agent.py` | One Task | Task |
| Runtime Handler (`LLMAgentHandler`) | `src/agent_handlers/llm_agent_handler.py` | One execution call | Execution Run |

Each has an independent lifecycle. **The system must not confuse
Task membership (TaskAgent) with Agent identity (AgentDefinition),**
and must not let either leak into the lifetime of a Runtime Handler.

## 1. AgentTemplate policy

`AgentTemplate` (`src/agents/agent_template_repository.py`) is a
user-authored asset — a reusable description ("Backend Developer",
"Security Reviewer") that outlives any single Task and can be
assigned to many Tasks over time.

**MUST**
- Persist independently of any Task.
- Be addressable only by `template_id`.

**MUST NOT**
- Be deleted as a side effect of Task completion or
  `TaskAgentCleanupService.cleanup()`. Nothing in the cleanup path
  touches `AgentTemplateRepository`, and it must stay that way.

## 2. AgentDefinition policy

`AgentDefinition` (`src/models.py`) is the executable agent identity:
`id`, `template_id`, model/credential/tool-policy configuration, and
limits. It is what `AgentRuntimeFactory` resolves into a live
handler.

**MUST**
- Belong to exactly one `AgentTemplate`, via a required, non-empty
  `template_id` field (5E-4E-1A). `AgentDefinition.from_dict` raises
  if `template_id` is missing — there is no orphan `AgentDefinition`.
- Keep `id` globally unique.
- Be reusable across Tasks, sequentially: an `AgentDefinition` can be
  assigned to Task A, released, then assigned to Task B, without
  being recreated.

Assignment does not mutate the `AgentDefinition`. What actually
changes is external, tracked ownership state in
`TaskAgentRegistry.owner_task_id(agent_id)`:

```
None -> task-a (assign) -> None (cleanup) -> task-b (reassign)
```

**MUST NOT**
- Be deleted by `TaskAgentCleanupService` or any Task-completion path.
  Cleanup only removes `TaskAgent` rows (see §3); the persistent
  asset is untouched.

## 3. TaskAgent policy

`TaskAgent` (`src/agents/task_agent.py`) is Task-scoped membership: it
says "this `AgentDefinition` is currently assigned to this Task,"
nothing more. It is created only through
`TaskAgentAssignmentService.assign()` (`src/agents/task_agent_assignment_service.py`),
which is the sole sanctioned boundary — callers must never call
`TaskAgentRegistry.assign_agent()` directly.

**MUST**
- Be removed only by `TaskAgentCleanupService.cleanup()`, and only
  once the owning Task's status is `"completed"`.
- Be isolated per Task: `TaskAgentRegistry.list_agents(task_id)` for
  one Task must never include another Task's `TaskAgent` rows.

**MUST NOT**
- Removal of a `TaskAgent` must never be treated as, or implemented
  as, deletion of the underlying `AgentDefinition`.

## 4. Runtime Handler policy

A Runtime Handler (`LLMAgentHandler`, built by
`AgentRuntimeFactory.create_handlers(task_id)`) is the object that
actually executes a message against an Agent.

**MUST**
- Be constructed fresh, scoped to one `create_handlers(task_id)` call,
  which itself is driven only by whatever `TaskAgentRegistry`
  currently reports for that Task.

**MUST NOT**
- Be cached or kept alive outside the execution/routing call that
  needed it. There is no global handler registry; a handler's
  lifetime never outlives the Task-agent membership it was built
  from.

## 5. Ownership summary

| Object | Owned by |
|---|---|
| AgentTemplate | User |
| AgentDefinition | User / `AgentRegistry` |
| TaskAgent | Task |
| Runtime Handler | Execution Run |

## 6. Cleanup rules

On Task completion, `TaskAgentCleanupService.cleanup(task_id)`:

- Removes only that Task's `TaskAgent` membership/ownership rows.
- Never touches `AgentDefinition` (`AgentRegistry`/`AgentRepository`).
- Never touches `AgentTemplate` (`AgentTemplateRepository`).
- Never touches any other Task's `TaskAgent` rows.

## 7. Global invariants

**Invariant 1 — Agent identity**
```
TaskAgent.agent_id == AgentDefinition.id
```
Enforced at assignment time by `TaskAgentAssignmentService`, which
looks the agent up through `AgentRegistry` before creating a
`TaskAgent`.

**Invariant 2 — Template consistency**
```
TaskAgent.template_id == AgentDefinition.template_id
```
Enforced by `TaskAgentAssignmentService._require_template_matches`
(5E-4E-1A): assignment is rejected with `AgentTemplateMismatchError`
if the caller's `template_id` doesn't match the `AgentDefinition`'s
own `template_id`. This is what keeps what the Planner sees (via
`AgentTemplate`, through `TaskPlanningContextFactory`) consistent
with what actually executes (via `AgentDefinition`, through
`AgentRuntimeFactory`).

**Invariant 3 — Cleanup isolation**
```
cleanup(Task A) does not modify:
  - Task B's TaskAgent rows
  - any AgentDefinition
  - any AgentTemplate
```

**Invariant 4 — Execution isolation**
```
A Runtime Handler must only exist inside the scope of the
create_handlers() call (or execution) that built it.
```

These four invariants are locked by
`tests/architecture/test_agent_lifecycle_policy.py`, which exists to
catch regressions in this policy, not to test implementation details.
