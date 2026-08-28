from __future__ import annotations

from src.agents.agent_template import AgentTemplate
from src.agents.agent_template_repository import (
    AgentTemplateRepository,
)


def test_save_and_get_template() -> None:
    repository = AgentTemplateRepository()
    template = AgentTemplate(
        template_id="backend-dev",
        name="Backend Developer",
        description="Builds backend services",
        capabilities=["python", "api"],
    )

    repository.save(template)

    assert repository.get("backend-dev") == template


def test_get_returns_none_when_not_found() -> None:
    repository = AgentTemplateRepository()

    assert repository.get("missing") is None


def test_save_overwrites_existing_template_with_the_same_id() -> None:
    repository = AgentTemplateRepository()
    repository.save(AgentTemplate(template_id="backend-dev", name="v1"))
    repository.save(AgentTemplate(template_id="backend-dev", name="v2"))

    assert repository.get("backend-dev").name == "v2"


def test_list_all_templates() -> None:
    repository = AgentTemplateRepository()
    backend = AgentTemplate(template_id="backend-dev", name="Backend")
    reviewer = AgentTemplate(template_id="reviewer", name="Reviewer")

    repository.save(backend)
    repository.save(reviewer)

    assert repository.list_all() == [backend, reviewer]


def test_list_all_is_empty_when_no_templates_saved() -> None:
    repository = AgentTemplateRepository()

    assert repository.list_all() == []
