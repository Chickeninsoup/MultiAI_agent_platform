from __future__ import annotations

import dataclasses

import pytest

from src.planning.repair_decision import RepairDecision


def test_create_decision() -> None:
    decision = RepairDecision(True, "repair")

    assert decision.should_repair
    assert decision.reason == "repair"


def test_frozen() -> None:
    decision = RepairDecision(False, "stop")

    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.reason = "x"
