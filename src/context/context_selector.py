from pathlib import Path
from typing import Protocol

from src.context.context_snapshot import ContextSnapshot


class ContextSelector(Protocol):
    """Something that can pick relevant context for a task.

    Structural, matching this codebase's Planner/AgentHandler
    convention - RuleBasedContextSelector and any future
    embedding-based selector satisfy this by having a matching
    select(), with no explicit inheritance needed.
    """

    def select(
        self, task_description: str, repository_root: Path
    ) -> ContextSnapshot:
        ...
