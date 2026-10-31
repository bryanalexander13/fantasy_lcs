"""Background deadline watcher for the shared draft room."""

import logging
import threading
import time

from draft import auto_pick_if_expired

_worker_lock = threading.Lock()
_worker_started = False


def start_draft_timer_worker() -> None:
    """Start one process-local watcher so expired turns advance without a page open."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        threading.Thread(target=_watch_deadlines, name="fantasy-draft-timer", daemon=True).start()


def _watch_deadlines() -> None:
    while True:
        try:
            auto_pick_if_expired()
        except Exception:
            logging.exception("Draft timer could not process an expired turn")
        time.sleep(1)
