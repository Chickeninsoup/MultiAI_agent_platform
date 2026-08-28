from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlanningContext:
    """Extra information a Planner may use beyond the raw request text.

    Both fields default to empty, matching how RuleBasedPlanner
    doesn't need any of this - it exists for a future ClaudePlanner,
    which would fold these into its prompt (e.g. "Available agents:
    ..." / "Constraints: ..."). Deliberately just two plain
    list[str] fields for now: richer shapes (per-agent capabilities,
    structured constraints) can grow this once something actually
    reads them beyond a flat list.
    """

    available_agents: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
