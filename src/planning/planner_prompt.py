from __future__ import annotations

from src.planning.agent_prompt_section import build_agent_prompt_section
from src.planning.task_planning_context import TaskPlanningContext


class PlannerPromptBuilder:
    """Turns a request (+ optional TaskPlanningContext) into a Claude prompt.

    Plain string concatenation, no template engine - the prompt shape
    is simple enough that a templating dependency would be overkill.
    context is optional because ManagerAgent.plan() always forwards
    it even when the caller never supplied one (5E-1B).

    The agent section (Phase 1-D, extracted to agent_prompt_section in
    Phase 1-F so RepairPromptBuilder renders the identical boundary)
    treats available_agents as a hard boundary, not a suggestion. This
    is prompt-level defense only - it doesn't and can't guarantee
    compliance; PlanValidator remains the deterministic enforcement
    layer downstream.
    """

    def build(
        self, request: str, context: TaskPlanningContext | None
    ) -> str:
        prompt = f"""
You are a planning agent.

User request:
{request}
"""

        if context is not None:
            prompt += build_agent_prompt_section(
                context.available_agents
            )

            if context.constraints:
                prompt += "\nConstraints:\n"
                for constraint in context.constraints:
                    prompt += f"- {constraint}\n"

        return prompt
