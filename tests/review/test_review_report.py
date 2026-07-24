import pytest

from src.review.review_report import ReviewReport


def test_creates_report_with_expected_fields() -> None:
    report = ReviewReport(
        run_id="run-001",
        summary=None,
        changed_files=["src/main.py"],
        risks=[],
        approved=None,
    )

    assert report.run_id == "run-001"
    assert report.summary is None
    assert report.changed_files == ["src/main.py"]
    assert report.risks == []
    assert report.approved is None


def test_supports_populated_summary_and_risks() -> None:
    report = ReviewReport(
        run_id="run-002",
        summary="Changed authentication flow.",
        changed_files=["src/auth.py"],
        risks=["Touches database migration"],
        approved=True,
    )

    assert report.summary == "Changed authentication flow."
    assert report.risks == ["Touches database migration"]
    assert report.approved is True


def test_report_is_immutable() -> None:
    report = ReviewReport(
        run_id="run-001",
        summary=None,
        changed_files=[],
        risks=[],
        approved=None,
    )

    with pytest.raises(AttributeError):
        report.approved = True  # type: ignore[misc]
