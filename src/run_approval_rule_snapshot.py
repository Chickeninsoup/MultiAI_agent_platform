from __future__ import annotations

import json
from pathlib import Path

from src.approval_policy_config import rules_from_dicts, rules_to_dicts
from src.approval_rule import ApprovalRule

SNAPSHOT_FILE_NAME = "approval_rules.json"


def get_snapshot_file(run_directory: Path) -> Path:
    return run_directory / SNAPSHOT_FILE_NAME


def save(run_directory: Path, rules: list[ApprovalRule]) -> None:
    """Persists the exact ApprovalRules in effect when this Run
    started (5E-5D-6D) - written once, at Run-start composition time,
    *even when rules is empty* (an explicit "no gating configured for
    this Run" fact, not merely the absence of a record), so a later
    continuation call reads this Run's own durable record rather than
    whatever the live APPROVAL_POLICY_PATH config file happens to
    contain *now* - which may have changed, or been deleted entirely,
    between the original `run` command and a later
    `resume-after-approval` in a different process. "Do not resume
    with empty rules merely because ... a configuration file vanished"
    (5E-5D-6D) holds because continuation never re-reads that config
    file at all - only this snapshot.
    """

    snapshot_file = get_snapshot_file(run_directory)
    snapshot_file.parent.mkdir(parents=True, exist_ok=True)
    snapshot_file.write_text(
        json.dumps(rules_to_dicts(rules)), encoding="utf-8"
    )


def load(run_directory: Path) -> list[ApprovalRule] | None:
    """Returns the persisted snapshot, or None if this Run has none at
    all - which only happens for a Run that started before this
    feature existed (no approval_rules.json was ever written for it).
    None is deliberately distinct from an empty list: an empty
    snapshot means "this Run explicitly started with no approval
    rules configured" (a fact), a missing snapshot means "nothing was
    ever recorded" (an absence) - a caller falling back to "no rules"
    for either case may do so, but only by choosing to, not because
    the two were silently conflated here.
    """

    snapshot_file = get_snapshot_file(run_directory)

    if not snapshot_file.exists():
        return None

    raw_rules = json.loads(snapshot_file.read_text(encoding="utf-8"))

    return rules_from_dicts(raw_rules)
