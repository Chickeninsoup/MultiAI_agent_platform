from __future__ import annotations

from pathlib import Path

from src.approval_request import RiskLevel
from src.approval_rule import ApprovalRule
from src.run_approval_rule_snapshot import load, save


def test_load_returns_none_when_no_snapshot_exists(
    tmp_path: Path,
) -> None:
    assert load(tmp_path) is None


def test_save_then_load_round_trips_rules(tmp_path: Path) -> None:
    rules = [
        ApprovalRule(
            tool_name="write_file",
            risk_level=RiskLevel.MEDIUM,
            reason="writes files",
        )
    ]

    save(tmp_path, rules)
    loaded = load(tmp_path)

    assert loaded == rules


def test_save_empty_list_is_distinguishable_from_missing(
    tmp_path: Path,
) -> None:
    save(tmp_path, [])

    loaded = load(tmp_path)

    assert loaded == []
    assert loaded is not None
