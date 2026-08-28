from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepairPrompt:
    """The text sent to Claude asking it to fix a failed plan.

    A dedicated wrapper instead of a bare str for the same reason
    PlanRepairRequest wraps its fields - logging, token estimation,
    and testing all want to reach for `.content` on something typed,
    not carry raw strings around.
    """

    content: str
