from typing import Protocol

from src.domain.tools.tool_call import ToolCall


class ToolInputPreviewer(Protocol):
    """Something that can build a human-safe preview of one ToolCall's
    input (5E-5D-4A).

    Structural, matching this codebase's ToolApprovalPolicy/
    ContextSelector convention - a fixed formatter today, could be
    schema-aware or LLM-summarized later without ToolApprovalGate
    changing.

    Deliberately the *only* source ToolApprovalGate is allowed to use
    for ApprovalRequest.input_preview - the gate has no fallback
    (repr(tool_call), str(tool_call.input), json.dumps(tool_call.input)
    or the raw input itself) if a previewer isn't supplied or returns
    nothing useful. ApprovalRequest.input_preview (src/approval_request.py)
    already documents that it "has no way to know which fields of an
    arbitrary tool's input are sensitive for a given tool" and pushes
    that responsibility to whatever constructs the request; this
    Protocol is where that responsibility actually lives - a real
    implementation (not built in this stage) would know, per tool
    name, which fields are safe to summarize and which must be
    redacted. preview() must not mutate tool_call and must return a
    non-empty string; ToolApprovalGate enforces the latter rather than
    trusting every implementation to.
    """

    def preview(self, tool_call: ToolCall) -> str:
        ...
