from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - platform-dependent
    fcntl = None  # type: ignore[assignment]


class ProcessFileLockUnsupportedError(RuntimeError):
    """Raised by process_file_lock() on a platform with no fcntl-based
    advisory locking (Windows, primarily) - this codebase's supported
    local platforms are POSIX (Linux/macOS, where fcntl.flock() is
    always available). Failing loudly and immediately here is
    deliberate (5E-5D-6C-1: "unsupported locking environments must
    fail explicitly rather than silently falling back to
    scan-then-create") - the alternative, quietly skipping the OS lock
    and relying on the create_exclusive()/find_incomplete() dance
    alone, is exactly the residual same-Run race this module exists to
    close, and silently reintroducing it on an unsupported platform
    would be worse than refusing to run there at all."""

    pass


class ProcessFileLockBusyError(RuntimeError):
    """Raised by process_file_lock() when lock_path is already held -
    either by another process (the OS flock denies it) or by another
    thread in this same process (the paired threading.Lock denies it).
    Always nonblocking (5E-5D-6C-1: "prefer nonblocking acquisition
    with a clear existing-style busy/blocked error over indefinite
    waiting") - this generic primitive raises its own plain vocabulary;
    callers with a richer domain error taxonomy (e.g. RunService's
    RunContinuationBlockedError) catch this and re-raise their own."""

    pass


_thread_locks: dict[str, threading.Lock] = {}
_thread_locks_mutex = threading.Lock()


def _thread_lock_for(key: str) -> threading.Lock:
    with _thread_locks_mutex:
        lock = _thread_locks.get(key)

        if lock is None:
            lock = threading.Lock()
            _thread_locks[key] = lock

        return lock


@contextmanager
def process_file_lock(lock_path: Path) -> Iterator[None]:
    """Exclusive, nonblocking ownership of lock_path, across both
    threads and processes (5E-5D-6C-1).

    OS-backed via fcntl.flock(LOCK_EX | LOCK_NB) on a file descriptor
    open for lock_path - an advisory lock the *kernel* tracks against
    that open file description, not a record this process writes
    itself. If the owning process dies for any reason (crash, SIGKILL,
    OOM), the kernel releases the lock the instant the file descriptor
    closes, as part of process teardown - no stale OS lock can ever
    outlive the process that held it, with no cleanup code required on
    this module's part. Supported wherever fcntl exists - this
    project's supported local platforms (Linux, macOS/BSD); on a
    platform without it (fcntl is None at import time), this raises
    ProcessFileLockUnsupportedError immediately, before touching the
    filesystem at all.

    flock()'s exact behavior across two independent opens of the same
    path *within one process* (e.g. two threads, each opening their
    own file descriptor) is a subtlety this code does not lean on
    either way - a plain threading.Lock, keyed by the resolved
    lock_path string, is acquired first and is what actually
    guarantees thread-safety; flock() is what guarantees cross-process
    safety. Both must be free for this context manager to succeed;
    whichever is busy raises ProcessFileLockBusyError before the other
    is ever touched (the thread lock is checked first, so a
    thread-local contender never even opens the file).

    lock_path's parent directories are created if missing, and the
    file itself is created if missing (os.O_CREAT) but never
    truncated and never unlinked here - at acquisition or at release.
    The same underlying file must still exist, at the same path, for
    the next contender to lock (5E-5D-6C-1: "do not unlink and
    recreate it during normal release: contenders must continue
    locking the same underlying file").
    """

    if fcntl is None:
        raise ProcessFileLockUnsupportedError(
            "process_file_lock() requires fcntl-based advisory "
            "locking (Linux/macOS), unavailable on this platform"
        )

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    thread_lock = _thread_lock_for(str(lock_path))

    if not thread_lock.acquire(blocking=False):
        raise ProcessFileLockBusyError(
            f"Lock already held by another thread in this process: "
            f"{lock_path}"
        )

    try:
        file_descriptor = os.open(
            str(lock_path), os.O_CREAT | os.O_RDWR, 0o644
        )

        try:
            try:
                fcntl.flock(
                    file_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB
                )
            except OSError as exc:
                raise ProcessFileLockBusyError(
                    f"Lock already held by another process: "
                    f"{lock_path}"
                ) from exc

            try:
                yield
            finally:
                # Explicit unlock before close(), even though close()
                # alone would also release it - makes the release
                # point unambiguous rather than implicit in fd
                # teardown.
                fcntl.flock(file_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(file_descriptor)
    finally:
        thread_lock.release()
