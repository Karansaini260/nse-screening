"""
Shared helpers for background work in Tk pages.

Tkinter widgets can only be safely accessed from the main thread.
This module provides two helpers that page modules use to run
work in background threads and safely surface results on the
UI thread.

Use `run_in_background()` when you need to:
  * Run CPU/IO-heavy work off the UI thread (model.predict,
    CSV read, ML training, etc.)
  * Still need to update Tk widgets with the result

Pattern:
    def on_button_click(self):
        def worker():
            result = heavy_work()
            self._schedule_on_ui(lambda: self._update_label(result))
        run_in_background(worker, on_error=lambda e: log(f"failed: {e}"))

Why a helper instead of `threading.Thread(target=..., daemon=True).start()`?
  * Centralises the daemon flag and error logging. 4+ pages were
    doing the same `threading.Thread(target=..., daemon=True).start()`
    boilerplate.
  * Pages that need a "is anything running" flag for the test
    helper can use `WorkerTracker` (below) to track in-flight
    threads; the helper updates the tracker so tests can wait.
"""
import logging
import threading
from typing import Callable, Optional

_log = logging.getLogger(__name__)


def run_in_background(
    target: Callable[[], None],
    *,
    name: Optional[str] = None,
    tracker: Optional["WorkerTracker"] = None,
    on_error: Optional[Callable[[BaseException], None]] = None,
) -> threading.Thread:
    """Spawn a daemon thread to run `target` in the background.

    The thread is daemonised so the Python interpreter can exit
    cleanly even if the thread is still running (it will be
    killed at shutdown). Errors are logged and (optionally)
    forwarded to `on_error` instead of being silently swallowed.

    Parameters
    ----------
    target : callable
        The function to run on the background thread. No
        arguments.
    name : str, optional
        Thread name for easier debugging. Defaults to
        'Worker-N' (auto-assigned by threading).
    tracker : WorkerTracker, optional
        If provided, the thread is added to the tracker's
        active set on start and removed on completion. The
        test helper `tests/test_ml_stats_page.py::_wait_for_refresh`
        uses a similar pattern; pages that want the test helper
        to wait on their background work should pass the
        same tracker.
    on_error : callable(exception), optional
        Called if `target` raises. Defaults to logging the
        exception via the module logger.

    Returns
    -------
    threading.Thread
        The spawned thread (already started).
    """
    def wrapped():
        try:
            target()
        except BaseException as e:
            try:
                _log.exception("Background worker failed: %s", e)
            except Exception:
                pass
            if on_error is not None:
                try:
                    on_error(e)
                except Exception:
                    pass
        finally:
            if tracker is not None:
                tracker.remove_current()

    t = threading.Thread(target=wrapped, name=name, daemon=True)
    if tracker is not None:
        tracker.add(t)
    t.start()
    return t


class WorkerTracker:
    """Tracks the set of background worker threads currently
    running for a page. Used by the test helper to know when
    all background work has finished.

    The page keeps a `WorkerTracker` instance and passes it
    to every `run_in_background()` call. When the page is
    destroyed, it should call `tracker.clear()` to stop
    tracking — the threads themselves are daemonised so they
    won't block process exit.

    The page's existing `_active_worker_count()` method can
    just call `len(tracker.alive)`.
    """

    def __init__(self):
        import threading as _threading
        self._lock = _threading.Lock()
        self._threads = set()

    def add(self, thread: threading.Thread) -> None:
        with self._lock:
            self._threads.add(thread)

    def remove_current(self) -> None:
        """Remove the currently-running thread from the tracker.
        Called automatically by `run_in_background()` when the
        worker finishes. Pages should not need to call this.
        """
        with self._lock:
            current = threading.current_thread()
            self._threads.discard(current)

    def clear(self) -> None:
        """Drop all tracked threads. Called by the page's
        destroy() so late-firing callbacks don't keep the
        test helper waiting.
        """
        with self._lock:
            self._threads.clear()

    @property
    def alive(self) -> list:
        """Return the list of still-alive tracked threads.
        Used by `_active_worker_count()` and by tests."""
        with self._lock:
            threads = list(self._threads)
        return [t for t in threads if t.is_alive()]
