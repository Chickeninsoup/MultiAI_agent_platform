from __future__ import annotations

from src.planning.plan_schema import PlannedStep
from src.planning.planner_parser import PlannerResponseParser
from src.planning.planner_prompt import PlannerPromptBuilder
from src.planning.planner_provider import PlannerProvider
from src.planning.task_planning_context import TaskPlanningContext
from src.task_plan import TaskPlan, TaskStep


class ClaudePlanner:
    """LLM-backed Planner: prompt -> Claude -> parse -> TaskPlan.

    Wires together the pieces 5E-2A-D built, in one direction only:
    build a prompt from the request/context, hand it to the injected
    PlannerProvider (never AnthropicProvider directly - see
    PlannerProvider's own docstring for why), parse the raw text back
    into a PlannerOutput, then convert each PlannedStep into a
    trusted TaskStep. Does not validate the result - PlanValidator
    still owns "is this plan actually executable" (unknown agents,
    cycles, etc.); this only owns "did the LLM's response parse into
    the right shape."

    prompt_builder/parser default to the deterministic implementations
    (self-constructing, no external calls) so a caller only has to
    supply the one genuinely required, non-defaultable dependency:
    something that can actually talk to an LLM.

    context is typed as TaskPlanningContext (Phase 1C-3A), matching
    PlannerPromptBuilder's own migration - it renders each agent's
    agent_id, a minimal compatible rendering; a richer prompt (role,
    capabilities) is still a later design pass, not this one.
    """

    def __init__(
        self,
        provider: PlannerProvider,
        prompt_builder: PlannerPromptBuilder | None = None,
        parser: PlannerResponseParser | None = None,
    ) -> None:
        self._provider = provider
        self._prompt_builder = (
            prompt_builder
            if prompt_builder is not None
            else PlannerPromptBuilder()
        )
        self._parser = (
            parser if parser is not None else PlannerResponseParser()
        )

    def create_plan(
        self,
        request: str,
        task_id: str,
        context: TaskPlanningContext | None = None,
    ) -> TaskPlan:
        prompt = self._prompt_builder.build(request, context)
        raw = self._provider.complete(prompt)
        output = self._parser.parse(raw)

        return TaskPlan(
            task_id=task_id,
            steps=[
                self._to_task_step(step) for step in output.steps
            ],
        )

    @staticmethod
    def _to_task_step(step: PlannedStep) -> TaskStep:
        return TaskStep(
            step_id=step.step_id,
            agent_id=step.agent_id,
            description=step.description,
            depends_on=step.depends_on,
        )
