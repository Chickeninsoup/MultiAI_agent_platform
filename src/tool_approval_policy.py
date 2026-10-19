from typing import Protocol

from src.domain.tools.tool_call import ToolCall
from src.tool_approval_policy_result import ToolApprovalPolicyResult


class ToolApprovalPolicy(Protocol):
    """Something that can classify whether a ToolCall needs human
    approval before it executes (5E-5D-3).

    Structural, matching this codebase's ContextSelector/
    ToolRetentionPolicy convention - a fixed rule table today
    (RuleBasedToolApprovalPolicy), could be risk-scored or
    LLM-judged later without evaluate()'s callers changing.

    Deliberately a separate protocol from ToolPolicy
    (src/services/tools/tool_policy.py), not an extra method bolted
    onto it: ToolPolicy answers "is this Agent authorized to call this
    tool at all" (is_enabled()) and stays the single source of truth
    for that question. evaluate() answers an entirely later question -
    "given a ToolCall that's already authorized, does it also need a
    human's blessing before running" - and never touches
    authorization. A future runtime is what's responsible for calling
    ToolPolicy first and ToolApprovalPolicy only afterward; nothing
    about this protocol can turn an unauthorized ToolCall into an
    authorized one, because it never sees authorization at all.

    evaluate() is pure: no execution, no ApprovalRequest, no
    persistence, no events, no model/LLM calls. It only reads
    tool_call.name (never tool_call.input) and returns a
    ToolApprovalPolicyResult describing what it found.
    """

    def evaluate(self, tool_call: ToolCall) -> ToolApprovalPolicyResult:
        ...
