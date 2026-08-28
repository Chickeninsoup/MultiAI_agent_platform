from __future__ import annotations

import dataclasses

import pytest

from src.agents.agent_template import AgentTemplate


def test_create_agent_template() -> None:
    template = AgentTemplate(
        template_id="backend", name="Backend Developer"
    )

    assert template.template_id == "backend"
    assert template.name == "Backend Developer"


def test_agent_template_defaults() -> None:
    template = AgentTemplate(
        template_id="backend", name="Backend Developer"
    )

    assert template.description == ""
    assert template.capabilities == []
    assert template.tools == []


def test_agent_template_is_frozen() -> None:
    template = AgentTemplate(template_id="coder", name="Coder")

    with pytest.raises(dataclasses.FrozenInstanceError):
        template.name = "new"
