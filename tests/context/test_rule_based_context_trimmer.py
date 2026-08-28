from __future__ import annotations

from src.context.context_budget import ContextBudget
from src.context.context_file import ContextFile
from src.context.context_snapshot import ContextSnapshot
from src.context.rule_based_context_trimmer import (
    RuleBasedContextTrimmer,
)


class FakeEstimator:
    """Estimates a snapshot's size as its file count, for
    deterministic trimming tests independent of any real char-count
    heuristic."""

    def estimate(self, snapshot: ContextSnapshot) -> int:
        return len(snapshot.files)


def _file(name: str) -> ContextFile:
    return ContextFile(path=f"src/{name}.py", reason="keyword match")


def test_snapshot_under_budget_is_unchanged() -> None:
    trimmer = RuleBasedContextTrimmer(FakeEstimator())
    snapshot = ContextSnapshot(files=[_file("a"), _file("b")])

    trimmed = trimmer.trim(snapshot, ContextBudget(max_tokens=10))

    assert trimmed == snapshot


def test_over_budget_snapshot_trims_later_files() -> None:
    trimmer = RuleBasedContextTrimmer(FakeEstimator())
    file_a, file_b, file_c = _file("a"), _file("b"), _file("c")
    snapshot = ContextSnapshot(files=[file_a, file_b, file_c])

    trimmed = trimmer.trim(snapshot, ContextBudget(max_tokens=2))

    assert trimmed.files == [file_a, file_b]


def test_trimming_preserves_selector_order() -> None:
    trimmer = RuleBasedContextTrimmer(FakeEstimator())
    file_a, file_b = _file("a"), _file("b")
    snapshot = ContextSnapshot(files=[file_a, file_b])

    trimmed = trimmer.trim(snapshot, ContextBudget(max_tokens=1))

    assert trimmed.files == [file_a]


def test_empty_snapshot_stays_empty() -> None:
    trimmer = RuleBasedContextTrimmer(FakeEstimator())

    trimmed = trimmer.trim(ContextSnapshot(), ContextBudget(max_tokens=5))

    assert trimmed == ContextSnapshot()


def test_project_tree_is_never_trimmed_even_over_budget() -> None:
    trimmer = RuleBasedContextTrimmer(FakeEstimator())
    snapshot = ContextSnapshot(
        files=[_file("a")], project_tree="src/\n  a.py"
    )

    trimmed = trimmer.trim(snapshot, ContextBudget(max_tokens=0))

    assert trimmed.project_tree == "src/\n  a.py"
    assert trimmed.files == []


def test_a_single_file_that_alone_exceeds_budget_is_dropped() -> None:
    class HugeFirstFileEstimator:
        def estimate(self, snapshot: ContextSnapshot) -> int:
            if snapshot.files and snapshot.files[0].path.endswith(
                "huge.py"
            ):
                return 1000
            return len(snapshot.files)

    trimmer = RuleBasedContextTrimmer(HugeFirstFileEstimator())
    huge = ContextFile(path="src/huge.py", reason="keyword match")
    small = _file("small")
    snapshot = ContextSnapshot(files=[huge, small])

    trimmed = trimmer.trim(snapshot, ContextBudget(max_tokens=5))

    assert trimmed.files == []
