from __future__ import annotations

from src.planning.agent_prompt_section import build_agent_prompt_section
from src.planning.plan_repair_request import PlanRepairRequest
from src.planning.repair_prompt import RepairPrompt
from src.planning.repair_request_source import RepairRequestSource

_OPENING_LINE = {
    RepairRequestSource.VALIDATION: (
        "Your generated plan failed validation."
    ),
    RepairRequestSource.EXECUTION_FAILURE: (
        "Your generated plan encountered an execution failure."
    ),
}


class RepairPromptBuilder:
    """Turns a PlanRepairRequest into a RepairPrompt Claude can act on.

    Ends with the same JSON-only output contract PlannerPromptBuilder
    implies (5E-2), since a repaired plan flows through the exact same
    PlannerResponseParser - repair prompts and normal planning prompts
    have to agree on output shape, or the parser breaks for one of them.
    The agent scope section (Phase 1-F) reuses the exact same renderer
    PlannerPromptBuilder uses - a repair attempt must see the identical
    "ONLY these agents" boundary the original planning attempt saw, not
    a differently-worded (or differently-scoped) approximation of it.

    The opening line varies with request.source (5E-5C-7A) - a plan
    that passed validation and only failed at runtime never "failed
    validation," so claiming it did would misdescribe the problem to
    Claude.
    """

    def build(self, request: PlanRepairRequest) -> RepairPrompt:
        lines = [_OPENING_LINE[request.source]]

        lines.append("")
        lines.append("Validation errors:")

        for error in request.errors:
            lines.append(f"- {error.code}: {error.message}")

        if request.context is not None:
            lines.append(
                build_agent_prompt_section(
                    request.context.available_agents
                ).rstrip("\n")
            )

            if request.context.constraints:
                lines.append("")
                lines.append("Constraints:")

                for constraint in request.context.constraints:
                    lines.append(f"- {constraint}")

        lines.append("")
        lines.append(request.instructions)

        lines.append("")
        lines.append("Return only JSON matching:")
        lines.append("{")
        lines.append('  "steps": [')
        lines.append("    {")
        lines.append('      "step_id": "",')
        lines.append('      "agent_id": "",')
        lines.append('      "description": "",')
        lines.append('      "depends_on": []')
        lines.append("    }")
        lines.append("  ]")
        lines.append("}")

        return RepairPrompt(content="\n".join(lines))
