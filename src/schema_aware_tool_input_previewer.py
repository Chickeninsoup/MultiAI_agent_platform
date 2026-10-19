from __future__ import annotations

from src.domain.tools.tool_call import ToolCall
from src.tool_input_previewer import ToolInputPreviewer

_MAX_FIELD_CHARS = 200

# Per-tool, per-field allow-list of what is safe to echo back to a
# human reviewer (5E-5D-6D) - built by hand from each registered
# handler's own ToolDefinition.input_schema
# (src/services/tools/handlers/*.py), not derived automatically from
# the schema itself: a JSON Schema's "properties" says what a field
# *is*, not whether showing its value is safe. write_file/patch_file's
# actual payload fields (content/old_text/new_text) are deliberately
# excluded here - only path-shaped and enum/boolean-shaped fields ever
# appear. Adding a new tool to ToolExecutor's handler registry without
# adding it here means that tool's calls get the explicit
# metadata-only fallback below, never raw input by accident - the
# allow-list fails closed.
_SAFE_FIELDS_BY_TOOL: dict[str, tuple[str, ...]] = {
    "list_files": ("path", "recursive"),
    "read_file": ("path", "start_line", "end_line"),
    "git_status": (),
    "git_diff": ("staged",),
    "write_file": ("path", "mode"),
    "patch_file": ("path",),
    "run_test": ("test_name",),
}


class SchemaAwareToolInputPreviewer:
    """Production ToolInputPreviewer (5E-5D-6D) - the first real
    implementation of the Protocol src/tool_input_previewer.py
    documents but deliberately leaves unbuilt at 5E-5D-4A.

    For a registered tool (a key in _SAFE_FIELDS_BY_TOOL), the preview
    is "<tool_name>: field=value, ..." built only from that tool's own
    reviewed-safe fields, present-or-not - never the full tool_call.input
    dict, never repr()/str()/json.dumps() of it. write_file's `content`,
    patch_file's `old_text`/`new_text`, and any field of a tool this
    previewer does not recognize are never reachable through this
    class, structurally: there is no branch here that falls back to
    emitting an arbitrary field's value.

    For a tool name with no entry in _SAFE_FIELDS_BY_TOOL at all
    (unsupported input shape - a future tool added to ToolExecutor's
    registry without a matching update here, or a tool_call this
    previewer has simply never been taught about), the preview states
    plainly that input is omitted - an honest metadata-only preview,
    not a crash and not a silent full-input dump.

    Each included field's value is converted with str() (safe for the
    str/int/bool-shaped fields this allow-list actually selects) and
    truncated to _MAX_FIELD_CHARS - defense in depth against an
    unexpectedly long value in an otherwise-safe field (e.g. an
    unusually long path), not a response to any field this class
    treats as sensitive (those are never reachable here at all).
    """

    def preview(self, tool_call: ToolCall) -> str:
        safe_fields = _SAFE_FIELDS_BY_TOOL.get(tool_call.name)

        if safe_fields is None:
            return (
                f"{tool_call.name}: input omitted (no reviewed safe "
                "field list is configured for this tool)"
            )

        if not safe_fields:
            return f"{tool_call.name}: (no input fields)"

        parts: list[str] = []

        for field_name in safe_fields:
            if field_name not in tool_call.input:
                continue

            value_text = str(tool_call.input[field_name])

            if len(value_text) > _MAX_FIELD_CHARS:
                value_text = (
                    value_text[:_MAX_FIELD_CHARS] + "...[truncated]"
                )

            parts.append(f"{field_name}={value_text}")

        if not parts:
            return f"{tool_call.name}: (no reviewed fields present)"

        return f"{tool_call.name}: " + ", ".join(parts)
