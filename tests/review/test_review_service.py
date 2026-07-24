from src.review.change_snapshot import ChangeSnapshot
from src.review.review_service import ReviewService


def test_build_report_from_snapshot_pending_decision() -> None:
    snapshot = ChangeSnapshot(
        run_id="run-001",
        changed_files=["src/main.py"],
        mutation_count=1,
        test_results={"run_test": {"exit_code": 0}},
        diff_path=None,
    )

    report = ReviewService().build_report(
        snapshot=snapshot,
        approved=None,
    )

    assert report.run_id == "run-001"
    assert report.changed_files == ["src/main.py"]
    assert report.summary is None
    assert report.risks == []
    assert report.approved is None


def test_build_report_reflects_approved_decision() -> None:
    snapshot = ChangeSnapshot(
        run_id="run-002",
        changed_files=[],
        mutation_count=0,
        test_results={},
        diff_path=None,
    )

    report = ReviewService().build_report(
        snapshot=snapshot,
        approved=True,
    )

    assert report.approved is True


def test_build_report_reflects_rejected_decision() -> None:
    snapshot = ChangeSnapshot(
        run_id="run-003",
        changed_files=["src/main.py"],
        mutation_count=1,
        test_results={},
        diff_path=None,
    )

    report = ReviewService().build_report(
        snapshot=snapshot,
        approved=False,
    )

    assert report.approved is False
