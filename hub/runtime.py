"""Thread bootstrap shared by runserver and the process_queue command."""

import logging
import threading

logger = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()


def start_background():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    from .models import AppSettings
    from .watcher import watchers
    from .worker import Worker

    settings = AppSettings.load()
    worker = Worker()
    t = threading.Thread(target=worker.run_forever, daemon=True, name="rph-worker")
    t.start()
    logger.info("background worker thread started")
    if settings.watch_enabled and settings.expanded_workspace_root():
        watchers.start()
