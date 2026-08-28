from __future__ import annotations

import json

from src.planning.plan_schema import PlannedStep
from src.planning.planner_output import PlannerOutput


class PlannerResponseParser:
    """Turns a Claude JSON response into a PlannerOutput.

    Deliberately unforgiving: invalid JSON raises json.JSONDecodeError,
    a missing required field raises KeyError - both propagate straight
    out rather than being caught and papered over here. This sits on
    the same trust boundary PlanValidator sits on for TaskPlan itself:
    a malformed response should fail loudly and immediately, not
    silently become a plan with blank/guessed fields. depends_on is
    the one genuinely optional field (a step with no dependencies just
    omits it), so that one alone defaults to [] via .get().
    """

    def parse(self, raw: str) -> PlannerOutput:
        data = json.loads(raw)

        steps = [
            PlannedStep(
                step_id=item["step_id"],
                agent_id=item["agent_id"],
                description=item["description"],
                depends_on=item.get("depends_on", []),
            )
            for item in data["steps"]
        ]

        return PlannerOutput(steps=steps)
