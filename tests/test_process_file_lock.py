from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src import process_file_lock as lock_module
from src.process_file_lock import (
    ProcessFileLockBusyError,
    ProcessFileLockUnsupportedError,
    process_file_lock,
)


def test_acquire_and_release_allows_sequential_reacquisition(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "run.lock"

    with process_file_lock(lock_path):
        pass

    # Released on normal exit - a second, later acquisition succeeds.
    with process_file_lock(lock_path):
        pass

    assert lock_path.exists()


def test_released_on_exception(tmp_path: Path) -> None:
    lock_path = tmp_path / "run.lock"

    with pytest.raises(RuntimeError):
        with process_file_lock(lock_path):
            raise RuntimeError("boom")

    # Released even though the body raised - a later acquisition still
    # succeeds rather than hanging/raising busy.
    with process_file_lock(lock_path):
        pass


def test_does_not_unlink_or_recreate_the_lock_file(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "run.lock"

    with process_file_lock(lock_path):
        pass

    first_inode = lock_path.stat().st_ino

    with process_file_lock(lock_path):
        pass

    assert lock_path.stat().st_ino == first_inode


def test_second_thread_is_busy_while_first_holds_lock(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "run.lock"
    holder_ready = threading.Event()
    release = threading.Event()
    contender_result: list[Exception | None] = []

    def holder() -> None:
        with process_file_lock(lock_path):
            holder_ready.set()
            release.wait(timeout=5)

    def contender() -> None:
        holder_ready.wait(timeout=5)
        try:
            with process_file_lock(lock_path):
                contender_result.append(None)
        except ProcessFileLockBusyError as exc:
            contender_result.append(exc)

    holder_thread = threading.Thread(target=holder)
    contender_thread = threading.Thread(target=contender)
    holder_thread.start()
    contender_thread.start()
    contender_thread.join(timeout=5)
    release.set()
    holder_thread.join(timeout=5)

    assert len(contender_result) == 1
    assert isinstance(contender_result[0], ProcessFileLockBusyError)


def test_nonblocking_acquisition_never_waits(tmp_path: Path) -> None:
    lock_path = tmp_path / "run.lock"
    holder_ready = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with process_file_lock(lock_path):
            holder_ready.set()
            release.wait(timeout=5)

    holder_thread = threading.Thread(target=holder)
    holder_thread.start()
    holder_ready.wait(timeout=5)

    import time

    started = time.monotonic()
    with pytest.raises(ProcessFileLockBusyError):
        with process_file_lock(lock_path):
            pass
    elapsed = time.monotonic() - started

    release.set()
    holder_thread.join(timeout=5)

    assert elapsed < 1.0


def test_unsupported_platform_fails_explicitly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lock_module, "fcntl", None)

    with pytest.raises(ProcessFileLockUnsupportedError):
        with process_file_lock(tmp_path / "run.lock"):
            pass  # pragma: no cover - never reached

    # Nothing was created - the unsupported-platform failure happens
    # before any filesystem interaction, not a partial attempt.
    assert not (tmp_path / "run.lock").exists()
