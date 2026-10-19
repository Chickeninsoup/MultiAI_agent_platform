from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.approval_request import RiskLevel
from src.approval_rule import ApprovalRule


class ApprovalPolicyConfigError(ValueError):
    """Raised when an approval-policy configuration file is invalid
    (5E-5D-6D) - matching ToolPolicyError's own precedent
    (src/services/tools/tool_policy.py): a config file this malformed
    must fail loudly, before any Run executes, rather than silently
    becoming an empty (ungated) policy. An empty policy is only ever
    produced by an explicitly empty "rules": [] list - never by a
    parse/validation failure elsewhere in the same file."""

    error_code = "INVALID_APPROVAL_POLICY"


def load_approval_rules(
    policy_path: Path,
    *,
    known_tool_names: frozenset[str],
) -> list[ApprovalRule]:
    if not policy_path.exists():
        raise ApprovalPolicyConfigError(
            f"Approval policy file does not exist: {policy_path}"
        )

    try:
        raw_text = policy_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ApprovalPolicyConfigError(
            f"Could not read approval policy file: {policy_path}"
        ) from error

    try:
        raw_policy = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise ApprovalPolicyConfigError(
            f"Approval policy file is not valid JSON: {policy_path}"
        ) from error

    return parse_approval_rules(
        raw_policy, known_tool_names=known_tool_names
    )


def parse_approval_rules(
    raw_policy: Any,
    *,
    known_tool_names: frozenset[str],
) -> list[ApprovalRule]:
    """Parses and fully validates one approval-policy document before
    returning anything (5E-5D-6D) - every rule in the file is checked
    before any rule is accepted, so a single bad entry fails the whole
    load rather than silently producing a partial (or empty) policy
    the caller cannot distinguish from "no rules configured".

    Expected shape:
        {"rules": [{"tool_name": "write_file",
                    "risk_level": "medium",
                    "reason": "writes files inside the repository"}]}

    known_tool_names is the exact set of tool names this platform's
    ToolExecutor actually registers (passed in by the caller, which
    already builds that handler list - not hardcoded here, so this
    validation can never silently drift out of sync with the real
    handler registry). A rule naming any other tool_name is rejected -
    "unknown tool names must not silently become an empty policy"
    (5E-5D-6D) - rather than accepted now and only discovered to be
    dead configuration once ToolApprovalGate.check() is called for a
    tool_call that can never carry that name.
    """

    if not isinstance(raw_policy, dict):
        raise ApprovalPolicyConfigError(
            "Approval policy root must be an object"
        )

    allowed_root_keys = {"rules"}
    unexpected_root_keys = set(raw_policy) - allowed_root_keys

    if unexpected_root_keys:
        unexpected = ", ".join(sorted(unexpected_root_keys))
        raise ApprovalPolicyConfigError(
            f"Unexpected approval policy fields: {unexpected}"
        )

    raw_rules = raw_policy.get("rules")

    if not isinstance(raw_rules, list):
        raise ApprovalPolicyConfigError(
            "Approval policy field 'rules' must be a list"
        )

    rules: list[ApprovalRule] = []
    seen_tool_names: set[str] = set()

    for index, raw_rule in enumerate(raw_rules):
        rule = _parse_rule(
            raw_rule, index=index, known_tool_names=known_tool_names
        )

        if rule.tool_name in seen_tool_names:
            raise ApprovalPolicyConfigError(
                "Duplicate approval policy rule for tool: "
                f"{rule.tool_name!r}"
            )

        seen_tool_names.add(rule.tool_name)
        rules.append(rule)

    return rules


def _parse_rule(
    raw_rule: Any,
    *,
    index: int,
    known_tool_names: frozenset[str],
) -> ApprovalRule:
    if not isinstance(raw_rule, dict):
        raise ApprovalPolicyConfigError(
            f"Approval policy rule at index {index} must be an object"
        )

    allowed_keys = {"tool_name", "risk_level", "reason"}
    unexpected_keys = set(raw_rule) - allowed_keys

    if unexpected_keys:
        unexpected = ", ".join(sorted(unexpected_keys))
        raise ApprovalPolicyConfigError(
            f"Unexpected fields for approval policy rule at index "
            f"{index}: {unexpected}"
        )

    tool_name = raw_rule.get("tool_name")

    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ApprovalPolicyConfigError(
            f"Approval policy rule at index {index} field "
            "'tool_name' must be a non-empty string"
        )

    if tool_name not in known_tool_names:
        raise ApprovalPolicyConfigError(
            f"Approval policy rule at index {index} names an unknown "
            f"tool: {tool_name!r} (registered tools: "
            f"{', '.join(sorted(known_tool_names))})"
        )

    risk_level_raw = raw_rule.get("risk_level")

    if not isinstance(risk_level_raw, str):
        raise ApprovalPolicyConfigError(
            f"Approval policy rule at index {index} field "
            "'risk_level' must be a string"
        )

    try:
        risk_level = RiskLevel(risk_level_raw)
    except ValueError as error:
        valid_values = ", ".join(level.value for level in RiskLevel)
        raise ApprovalPolicyConfigError(
            f"Approval policy rule at index {index} has invalid "
            f"risk_level {risk_level_raw!r} (expected one of: "
            f"{valid_values})"
        ) from error

    reason = raw_rule.get("reason")

    if not isinstance(reason, str) or not reason.strip():
        raise ApprovalPolicyConfigError(
            f"Approval policy rule at index {index} field 'reason' "
            "must be a non-empty string"
        )

    return ApprovalRule(
        tool_name=tool_name, risk_level=risk_level, reason=reason
    )


def rules_to_dicts(rules: list[ApprovalRule]) -> list[dict[str, str]]:
    return [
        {
            "tool_name": rule.tool_name,
            "risk_level": rule.risk_level.value,
            "reason": rule.reason,
        }
        for rule in rules
    ]


def rules_from_dicts(
    raw_rules: list[dict[str, str]],
) -> list[ApprovalRule]:
    """Reconstructs ApprovalRules from an already-validated snapshot
    (5E-5D-6D) - used only for RunApprovalRuleSnapshot's own round
    trip (src/run_approval_rule_snapshot.py), where the content was
    written by rules_to_dicts() from an already-validated list and
    never hand-edited. Deliberately does not re-run
    parse_approval_rules()'s full validation (unknown-tool-name
    checking requires a known_tool_names set this function has no
    reason to also require) - from_dict()-style trust in your own
    prior to_dict() output, the same convention every other
    persisted-record from_dict() in this codebase already follows.
    """

    return [
        ApprovalRule(
            tool_name=raw_rule["tool_name"],
            risk_level=RiskLevel(raw_rule["risk_level"]),
            reason=raw_rule["reason"],
        )
        for raw_rule in raw_rules
    ]
