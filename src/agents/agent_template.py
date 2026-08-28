from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentTemplate:
    """A user-authored Agent definition - not a running Agent.

    Deliberately has no task_id: a template ("Backend Engineer",
    "Security Reviewer") outlives any single Task and can be assigned
    to many of them over time. What actually runs against one Task is
    a TaskAgent created from this template, not the template itself.
    """

    template_id: str
    name: str
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
