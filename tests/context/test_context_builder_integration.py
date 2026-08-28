from __future__ import annotations

from pathlib import Path

from src.context.context_budget import ContextBudget
from src.context.context_file import ContextFile
from src.context.context_snapshot import ContextSnapshot
from src.context_builder import (
    DEFAULT_CONTEXT_FILES,
    RunContextBuilder,
)
from src.models import (
    AgentDefinition,
    AgentLimits,
    RunDefinition,
    TaskDefinition,
)


class FakeTaskRepository:
    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    def get_background_file(self, task_id: str) -> Path:
        return self._project_root / "no-such-background.md"


class FakeRunRepository:
    def read_input(self, task_id: str, run_id: str) -> str:
        return "run input"


class FakeAgentRepository:
    def read_system_prompt(self, agent_id: str) -> str:
        return "system prompt"

    def load_tool_policy(self, agent_id: str) -> dict[str, object]:
        return {}


class FakeSelector:
    def __init__(self, snapshot: ContextSnapshot | Exception) -> None:
        self._snapshot = snapshot
        self.called = False

    def select(
        self, task_description: str, repository_root: Path
    ) -> ContextSnapshot:
        self.called = True

        if isinstance(self._snapshot, Exception):
            raise self._snapshot

        return self._snapshot


class FixedEstimator:
    def __init__(self, value: int) -> None:
        self._value = value

    def estimate(self, snapshot: ContextSnapshot) -> int:
        return self._value


class FakeTrimmer:
    def __init__(self, snapshot: ContextSnapshot) -> None:
        self._snapshot = snapshot
        self.called = False

    def trim(
        self, snapshot: ContextSnapshot, budget: ContextBudget
    ) -> ContextSnapshot:
        self.called = True
        return self._snapshot


def _task(**overrides: object) -> TaskDefinition:
    fields: dict[str, object] = dict(
        id="task-1",
        title="fix the login bug",
        description="fix the login bug",
        workspace_id="workspace-1",
        status="in_progress",
        priority="normal",
        created_by="user-1",
        assigned_agents=["agent-coder"],
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        started_at="2026-01-01T00:00:00Z",
        completed_at=None,
        abandoned_at=None,
        current_run_id="run-1",
        run_count=1,
        completion_criteria=[],
        tags=[],
    )
    fields.update(overrides)
    return TaskDefinition(**fields)


def _run(**overrides: object) -> RunDefinition:
    fields: dict[str, object] = dict(
        id="run-1",
        task_id="task-1",
        agent_id="agent-coder",
        status="running",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        started_at="2026-01-01T00:00:00Z",
        completed_at=None,
    )
    fields.update(overrides)
    return RunDefinition(**fields)


def _agent() -> AgentDefinition:
    return AgentDefinition(
        id="agent-coder",
        name="Coder",
        description="Writes code.",
        owner="owner-1",
        status="active",
        role="engineer",
        template_id="engineer",
        default_model="claude-model-placeholder",
        credential_id="cred-1",
        system_prompt_path="system-prompt.md",
        tool_policy_path="tool-policy.json",
        default_workspace_id="workspace-1",
        capabilities=[],
        limits=AgentLimits(
            memory_mb=512,
            cpus=1,
            timeout_seconds=60,
            max_input_tokens=50_000,
            max_output_tokens=4096,
        ),
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


def _builder(
    tmp_path: Path, *, selector=None, estimator=None, trimmer=None
) -> RunContextBuilder:
    return RunContextBuilder(
        project_root=tmp_path,
        task_repository=FakeTaskRepository(tmp_path),
        run_repository=FakeRunRepository(),
        agent_repository=FakeAgentRepository(),
        selector=selector,
        estimator=estimator,
        trimmer=trimmer,
    )


def test_selector_is_called_and_its_files_are_rendered(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "login.py").write_text(
        "def login(): ...\n", encoding="utf-8"
    )

    selector = FakeSelector(
        ContextSnapshot(
            files=[
                ContextFile(
                    path="src/login.py", reason="keyword match: login"
                )
            ]
        )
    )
    builder = _builder(tmp_path, selector=selector)

    context = builder.build(_task(), _run(), _agent())

    assert selector.called is True
    assert "src/login.py" in context.project_snapshot
    assert "def login(): ..." in context.project_snapshot
    for legacy_path in DEFAULT_CONTEXT_FILES:
        assert legacy_path not in context.project_snapshot


def test_trimmer_is_called_when_estimate_exceeds_budget(
    tmp_path: Path,
) -> None:
    (tmp_path / "kept.py").write_text("kept\n", encoding="utf-8")
    (tmp_path / "dropped.py").write_text("dropped\n", encoding="utf-8")

    selector = FakeSelector(
        ContextSnapshot(
            files=[
                ContextFile(path="dropped.py", reason="keyword match"),
                ContextFile(path="kept.py", reason="keyword match"),
            ]
        )
    )
    trimmer = FakeTrimmer(
        ContextSnapshot(
            files=[ContextFile(path="kept.py", reason="keyword match")]
        )
    )
    builder = _builder(
        tmp_path,
        selector=selector,
        estimator=FixedEstimator(999_999),
        trimmer=trimmer,
    )

    context = builder.build(_task(), _run(), _agent())

    # The project tree lists every file under project_root regardless
    # of selection, so check the per-file content section instead of
    # the bare filename to confirm dropped.py's *content* was never
    # rendered.
    assert trimmer.called is True
    assert "## File: `kept.py`" in context.project_snapshot
    assert "## File: `dropped.py`" not in context.project_snapshot


def test_trimmer_is_not_called_when_under_budget(
    tmp_path: Path,
) -> None:
    (tmp_path / "small.py").write_text("x\n", encoding="utf-8")

    selector = FakeSelector(
        ContextSnapshot(
            files=[ContextFile(path="small.py", reason="keyword match")]
        )
    )
    trimmer = FakeTrimmer(ContextSnapshot())
    builder = _builder(
        tmp_path,
        selector=selector,
        estimator=FixedEstimator(1),
        trimmer=trimmer,
    )

    builder.build(_task(), _run(), _agent())

    assert trimmer.called is False


def test_selector_exception_falls_back_to_legacy_files(
    tmp_path: Path,
) -> None:
    selector = FakeSelector(RuntimeError("selector exploded"))
    builder = _builder(tmp_path, selector=selector)

    context = builder.build(_task(), _run(), _agent())

    assert selector.called is True
    for legacy_path in DEFAULT_CONTEXT_FILES:
        assert legacy_path in context.project_snapshot


def test_empty_selection_falls_back_to_legacy_files(
    tmp_path: Path,
) -> None:
    selector = FakeSelector(ContextSnapshot(files=[]))
    builder = _builder(tmp_path, selector=selector)

    context = builder.build(_task(), _run(), _agent())

    for legacy_path in DEFAULT_CONTEXT_FILES:
        assert legacy_path in context.project_snapshot


def test_explicit_run_metadata_override_still_wins_over_selector(
    tmp_path: Path,
) -> None:
    (tmp_path / "manual.py").write_text("manual\n", encoding="utf-8")

    selector = FakeSelector(
        ContextSnapshot(
            files=[ContextFile(path="never.py", reason="keyword match")]
        )
    )
    builder = _builder(tmp_path, selector=selector)
    run = _run(metadata={"context_files": ["manual.py"]})

    context = builder.build(_task(), run, _agent())

    assert selector.called is False
    assert "manual.py" in context.project_snapshot
    assert "never.py" not in context.project_snapshot


def test_real_selector_prefers_task_relevant_file_over_hardcoded_defaults(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text(
        "def authenticate(): ...\n", encoding="utf-8"
    )
    (tmp_path / "src" / "unrelated.py").write_text(
        "def unrelated(): ...\n", encoding="utf-8"
    )

    builder = _builder(tmp_path)
    task = _task(description="fix the authentication bug")

    context = builder.build(task, _run(), _agent())

    # unrelated.py still exists on disk and shows up in the project
    # tree listing regardless of selection, so check its content
    # section specifically to confirm it wasn't selected.
    assert "## File: `src/auth.py`" in context.project_snapshot
    assert (
        "## File: `src/unrelated.py`" not in context.project_snapshot
    )
    for legacy_path in DEFAULT_CONTEXT_FILES:
        assert f"## File: `{legacy_path}`" not in context.project_snapshot
