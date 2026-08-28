from __future__ import annotations

from src.planning.plan_repair_request import PlanRepairRequest
from src.planning.planner_output import PlannerOutput
from src.planning.planner_parser import PlannerResponseParser
from src.planning.planner_provider import PlannerProvider
from src.planning.repair_prompt_builder import RepairPromptBuilder


class RepairPlanner:
    """Asks Claude to fix a failed plan: request -> prompt -> PlannerOutput.

    A separate class from ClaudePlanner rather than a new method on it -
    "create a plan from a request" and "repair a plan that already
    failed validation" are different operations with different inputs
    (str vs PlanRepairRequest), even though both end up going through
    the same PlannerProvider and PlannerResponseParser. Returns
    PlannerOutput, not TaskPlan: converting PlannedStep -> TaskStep and
    deciding what task_id a repaired plan gets belongs to whatever
    calls this (5E-3D's repair loop), not to prompt/parse plumbing.
    """

    def __init__(
        self,
        provider: PlannerProvider,
        prompt_builder: RepairPromptBuilder | None = None,
        parser: PlannerResponseParser | None = None,
    ) -> None:
        self.provider = provider
        self.prompt_builder = (
            prompt_builder
            if prompt_builder is not None
            else RepairPromptBuilder()
        )
        self.parser = (
            parser if parser is not None else PlannerResponseParser()
        )

    def repair(self, repair_request: PlanRepairRequest) -> PlannerOutput:
        prompt = self.prompt_builder.build(repair_request)
        raw = self.provider.complete(prompt.content)

        return self.parser.parse(raw)
