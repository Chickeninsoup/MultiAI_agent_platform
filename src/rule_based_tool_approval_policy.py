from __future__ import annotations

from src.approval_rule import ApprovalRule
from src.domain.tools.tool_call import ToolCall
from src.tool_approval_policy_result import ToolApprovalPolicyResult
from src.tool_approval_requirement import ToolApprovalRequirement


class RuleBasedToolApprovalPolicy:
    """Default ToolApprovalPolicy: a fixed table of ApprovalRules,
    keyed by exact tool name (5E-5D-3).

    V1 is deliberately name-only, with no input-dependent heuristics -
    a ToolCall's tool_call.name either has a configured ApprovalRule
    or it doesn't; evaluate() never inspects tool_call.input. Matching
    exact tool-name lookup, this codebase does not case-fold tool
    names anywhere it matters (ToolExecutor keys its handlers dict by
    the exact string handler.definition.name, and looks callers up by
    tool_call.name with a plain dict .get() - no .lower()/.upper()
    normalization); ApprovalRule.tool_name is matched the same way.

    Unconfigured tools default to DOES_NOT_REQUIRE_APPROVAL, not the
    reverse - this is a deliberately explicit allow-list model (a tool
    needs an ApprovalRule to require approval), not a deny-list one (a
    tool needs a rule to be allowed to skip approval). No built-in
    global list of risky tools exists anywhere in this codebase to
    default to instead (ToolRetentionPolicy's PROTECTED set answers a
    different question entirely - see its own module docstring - and
    was deliberately not copied here); rules must be supplied by
    whatever constructs this policy.

    Rules are consumed once, at construction, into an internal dict -
    this class never retains the caller's original list, so mutating
    that list afterward has no effect on an already-constructed
    policy's behavior. Duplicate rules for the same tool_name raise at
    construction, matching ToolExecutor's exact precedent for
    duplicate tool registration (src/services/tools/tool_executor.py).
    """

    def __init__(self, rules: list[ApprovalRule]) -> None:
        self._rules_by_tool_name: dict[str, ApprovalRule] = {}

        for rule in rules:
            if rule.tool_name in self._rules_by_tool_name:
                raise ValueError(
                    "Duplicate approval rule for tool: "
                    f"{rule.tool_name}"
                )

            self._rules_by_tool_name[rule.tool_name] = rule

    def evaluate(self, tool_call: ToolCall) -> ToolApprovalPolicyResult:
        rule = self._rules_by_tool_name.get(tool_call.name)

        if rule is None:
            return ToolApprovalPolicyResult(
                requirement=(
                    ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL
                ),
            )

        return ToolApprovalPolicyResult(
            requirement=ToolApprovalRequirement.REQUIRES_APPROVAL,
            risk_level=rule.risk_level,
            reason=rule.reason,
        )
