from __future__ import annotations

import dataclasses

import pytest

from src.planning.repair_prompt import RepairPrompt


def test_create_prompt() -> None:
    prompt = RepairPrompt(content="fix plan")

    assert prompt.content == "fix plan"


def test_prompt_frozen() -> None:
    prompt = RepairPrompt(content="fix")

    with pytest.raises(dataclasses.FrozenInstanceError):
        prompt.content = "new"
