from __future__ import annotations

from dataclasses import dataclass

from src.domain.events.event_repository import EventRepository
from src.domain.events.timeline import RunTimeline
from src.domain.events.timeline_builder import TimelineBuilder
from src.models import RunDefinition, TaskDefinition
from src.repositories import RunRepository, TaskRepository
from src.review.change_snapshot import ChangeSnapshot
from src.review.snapshot_repository import (
    SnapshotNotFoundError,
    SnapshotRepository,
)


@dataclass(frozen=True)
class RunInspection:
    run: RunDefinition
    task_id: str
    timeline: RunTimeline
    snapshot: ChangeSnapshot | None


class RunQueryService:
    """Read-only counterpart to RunService.

    RunService executes Runs and changes their state; this only reads
    what's already on disk (run.json / events.jsonl / change_snapshot.json)
    to answer "what happened" - it never mutates anything. Deliberately
    does not share RunService's private task-lookup helper: the query
    side shouldn't depend on the command side, and the lookup itself is
    a few lines, not worth coupling the two over.
    """

    def __init__(
        self,
        *,
        task_repository: TaskRepository,
        run_repository: RunRepository,
        event_repository: EventRepository,
        snapshot_repository: SnapshotRepository,
        timeline_builder: TimelineBuilder,
    ) -> None:
        self._task_repository = task_repository
        self._run_repository = run_repository
        self._event_repository = event_repository
        self._snapshot_repository = snapshot_repository
        self._timeline_builder = timeline_builder

    def list_runs(self) -> list[RunDefinition]:
        runs: list[RunDefinition] = []

        for task in self._task_repository.list_all():
            for run_id in self._run_repository.list_run_ids(task.id):
                runs.append(
                    self._run_repository.load(task.id, run_id)
                )

        return runs

    def inspect_run(self, run_id: str) -> RunInspection:
        task = self._find_task_for_run(run_id)

        if task is None:
            raise ValueError(f"No task owns run {run_id}")

        run = self._run_repository.load(task.id, run_id)

        events_path = self._run_repository.get_events_file(
            task.id,
            run_id,
        )
        events = self._event_repository.load_events(
            events_path,
            run_id,
        )
        timeline = self._timeline_builder.build(
            run_id=run_id,
            events=events,
        )

        run_directory = self._run_repository.get_run_dir(
            task.id,
            run_id,
        )

        try:
            snapshot = self._snapshot_repository.load(run_directory)
        except SnapshotNotFoundError:
            snapshot = None

        return RunInspection(
            run=run,
            task_id=task.id,
            timeline=timeline,
            snapshot=snapshot,
        )

    def _find_task_for_run(
        self,
        run_id: str,
    ) -> TaskDefinition | None:
        for task in self._task_repository.list_all():
            if run_id in self._run_repository.list_run_ids(task.id):
                return task

        return None
