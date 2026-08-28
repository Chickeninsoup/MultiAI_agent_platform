from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlannedStep:
    """One step from a Planner's raw structured output - not a TaskStep.

    A separate shape from TaskStep on purpose: this is the contract a
    future ClaudePlanner parses untrusted LLM JSON output into first,
    before anything converts it into the trusted internal TaskStep/
    TaskPlan domain model. Keeping them distinct means "can this be
    parsed out of what Claude returned" and "is this a valid step in
    our domain" stay separate questions - RuleBasedPlanner doesn't
    need this at all, since it builds TaskStep directly.
    """

    step_id: str
    agent_id: str
    description: str
    depends_on: list[str] = field(default_factory=list)
