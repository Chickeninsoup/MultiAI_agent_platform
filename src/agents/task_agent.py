from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskAgent:
    """An Agent instance bound to exactly one Task.

    task_id is what makes this a TaskAgent rather than an
    AgentTemplate - it's what TaskAgentRegistry filters on to
    guarantee Task A can never see Task B's agents. template_id
    traces this instance back to the AgentTemplate the user created
    it from.

    Frozen lifecycle policy (5E-4E): of the four Agent-related
    objects in this system - AgentTemplate (persistent, user-owned),
    AgentDefinition (persistent, the real executable asset a template
    maps to), TaskAgent (this class - ephemeral, one row per Task
    assignment), and LLMAgentHandler (ephemeral, one per execution
    call) - only TaskAgent and LLMAgentHandler are Task-scoped.
    TaskAgentCleanupService, run once a Task completes, deletes only
    this TaskAgent's membership/ownership row in TaskAgentRegistry -
    never the underlying AgentDefinition or AgentTemplate. That's why
    an agent_id's owner_task_id can go task-a -> None (cleanup) ->
    task-b (reassigned) without the Agent ever being recreated: the
    persistent asset outlives every Task it's ever served.
    """

    agent_id: str
    task_id: str
    template_id: str
    status: str = "active"
