from __future__ import annotations

from src.agents.agent_template import AgentTemplate


class AgentTemplateRepository:
    """Looks up what a template_id actually means: name, capabilities, description.

    User-owned data, kept deliberately separate from TaskAgentRegistry
    (which only knows "this instance's template_id is X", never what
    X means) - see task_agent.py's docstring on why Registry doesn't
    reach into templates itself. save/get/list_all rather than
    register/assign - a Template is a user asset the caller owns and
    updates, not something assigned into a scope the way a TaskAgent
    is assigned to a Task. In-memory only; nothing here persists to
    disk yet.
    """

    def __init__(self) -> None:
        self._templates: dict[str, AgentTemplate] = {}

    def save(self, template: AgentTemplate) -> None:
        self._templates[template.template_id] = template

    def get(self, template_id: str) -> AgentTemplate | None:
        return self._templates.get(template_id)

    def list_all(self) -> list[AgentTemplate]:
        return list(self._templates.values())
