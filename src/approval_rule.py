from __future__ import annotations

from dataclasses import dataclass

from src.approval_request import RiskLevel


@dataclass(frozen=True)
class ApprovalRule:
    """A caller-configured statement that calling a given tool always
    requires human approval, and why (5E-5D-3).

    Deliberately narrower than ToolPolicyEntry
    (src/services/tools/tool_policy.py): that one answers "is this
    tool enabled for this Agent at all, and what are its output/write
    limits" - authorization and resource limits. This answers a
    completely separate question - "does calling this tool, once
    already authorized, need a human's blessing first, and how risky
    is it" - so it carries risk_level/reason instead of enabled/
    max_output_chars/max_write_bytes, and is evaluated by a different
    policy (ToolApprovalPolicy) than ToolPolicy.is_enabled().

    Deliberately excludes any ToolCall input: a rule describes a tool
    *by name*, once, at configuration time - not a specific call. V1
    has no input-dependent heuristics (see RuleBasedToolApprovalPolicy);
    keeping input off this model entirely (rather than, say, an
    optional/unused field) makes that a structural guarantee, not just
    a convention nothing currently violates.
    """

    tool_name: str
    risk_level: RiskLevel
    reason: str

    def __post_init__(self) -> None:
        if not self.tool_name or not self.tool_name.strip():
            raise ValueError(
                "ApprovalRule field 'tool_name' must be a non-empty "
                "string"
            )

        if not self.reason or not self.reason.strip():
            raise ValueError(
                "ApprovalRule field 'reason' must be a non-empty "
                "string"
            )

        if not isinstance(self.risk_level, RiskLevel):
            raise ValueError(
                "ApprovalRule field 'risk_level' must be a RiskLevel"
            )
