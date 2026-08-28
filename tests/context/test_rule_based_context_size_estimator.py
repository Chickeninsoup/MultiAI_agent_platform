from __future__ import annotations

from src.context.context_file import ContextFile
from src.context.context_snapshot import ContextSnapshot
from src.context.rule_based_context_size_estimator import (
    RuleBasedContextSizeEstimator,
)


def test_empty_snapshot_floors_at_one() -> None:
    estimator = RuleBasedContextSizeEstimator()

    assert estimator.estimate(ContextSnapshot()) == 1


def test_tiny_non_empty_snapshot_still_floors_at_one() -> None:
    estimator = RuleBasedContextSizeEstimator()
    # "ab" is 2 chars -> 2 // 4 == 0, but the floor forces 1.
    snapshot = ContextSnapshot(project_tree="ab")

    assert estimator.estimate(snapshot) == 1


def test_estimate_divides_character_count_by_four() -> None:
    estimator = RuleBasedContextSizeEstimator()
    snapshot = ContextSnapshot(
        files=[ContextFile(path="ab", reason="cd")]
    )

    # rendered text: "" + "\n" + "ab\ncd" == "\nab\ncd" (6 chars)
    assert estimator.estimate(snapshot) == 6 // 4


def test_project_tree_contributes_to_the_estimate() -> None:
    estimator = RuleBasedContextSizeEstimator()
    without_tree = ContextSnapshot()
    with_tree = ContextSnapshot(project_tree="x" * 400)

    assert estimator.estimate(with_tree) > estimator.estimate(
        without_tree
    )


def test_more_files_increase_the_estimate() -> None:
    estimator = RuleBasedContextSizeEstimator()
    one_file = ContextSnapshot(
        files=[ContextFile(path="src/a.py", reason="keyword match: a")]
    )
    two_files = ContextSnapshot(
        files=[
            ContextFile(path="src/a.py", reason="keyword match: a"),
            ContextFile(path="src/b.py", reason="keyword match: b"),
        ]
    )

    assert estimator.estimate(two_files) > estimator.estimate(one_file)
