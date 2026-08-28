from __future__ import annotations

from src.agents.task_agent_info import TaskAgentInfo


def build_agent_prompt_section(agents: list[TaskAgentInfo]) -> str:
    """Renders the "hard boundary" agent scope block shared by planning
    and repair prompts (Phase 1-D / 1-F).

    A single shared renderer so the guardrail wording - and any future
    changes to it - can't drift between "here's who can plan" and
    "here's who can repair"; the two situations enforce the exact same
    boundary (TaskPlanningContext.available_agents), so they render it
    identically.
    """

    lines = ["", "AVAILABLE AGENTS FOR THIS TASK", ""]

    if not agents:
        lines.append(
            "No agents are currently assigned to this task."
        )
        lines.append("Do NOT create or invent agents.")
    else:
        lines.append(
            "The following agents are the ONLY agents "
            "available for this task."
        )
        lines.append(
            "You MUST assign every step to one of these agent "
            "IDs."
        )
        lines.append("Do NOT create new agents.")
        lines.append("Do NOT invent agent IDs.")
        lines.append(
            "Do NOT reference agents that are not listed below."
        )

        for agent in agents:
            lines.append("")
            lines.extend(_format_agent(agent))

    return "\n".join(lines) + "\n"


def _format_agent(agent: TaskAgentInfo) -> list[str]:
    lines = [
        f"Agent ID: {agent.agent_id}",
        f"Role: {agent.role}",
    ]

    if agent.description:
        lines.append(f"Description: {agent.description}")

    if agent.capabilities:
        lines.append("Capabilities:")
        for capability in agent.capabilities:
            lines.append(f"- {capability}")

    return lines
