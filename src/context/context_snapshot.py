from __future__ import annotations

from dataclasses import dataclass, field

from src.context.context_file import ContextFile


@dataclass(frozen=True)
class ContextSnapshot:
    """The set of ContextFiles (and project tree) selected for a run.

    A pure data model (5D-6B-1) - it doesn't render itself into text
    or know how big it is. project_tree stays a plain str because a
    directory layout is still useful for orientation even when full
    file contents aren't selected; it's not exempt from a future
    budget, just not modeled as ContextFiles since it isn't one.
    Nothing builds or consumes this yet - RunContextBuilder is
    untouched until 5D-6B-4 wires it in.
    """

    files: list[ContextFile] = field(default_factory=list)
    project_tree: str = ""
