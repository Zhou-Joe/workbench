"""Watchdog-based folder watcher with debounce; feeds ingestion + SSE."""

import logging
import threading

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from . import ingest
from .models import AppSettings, Phase

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 2.0


class _Handler(FileSystemEventHandler):
    def __init__(self, manager):
        self.manager = manager

    def on_created(self, event):
        if not event.is_directory:
            self.manager.note(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.manager.note(event.dest_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.manager.note(event.src_path)


class WatcherManager:
    def __init__(self):
        self.observer = None
        self._pending = {}
        self._lock = threading.Lock()
        self._timer = None

    def note(self, path):
        with self._lock:
            self._pending[path] = True
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(DEBOUNCE_SECONDS, self._drain)
            self._timer.daemon = True
            self._timer.start()

    def _drain(self):
        with self._lock:
            paths = list(self._pending.keys())
            self._pending.clear()
            self._timer = None
        if not paths:
            return
        try:
            settings = AppSettings.load()
            if not settings.expanded_workspace_root():
                return
            # Route each path to its project/phase by folder segments.
            from .models import Project

            projects = {p.slug: p for p in Project.objects.all()}
            for path in paths:
                parts = path.strip("/").split("/")
                # expect <root>/<project-slug>/<NN-phase-slug>/...
                for i, part in enumerate(parts[:-1]):
                    project = projects.get(part)
                    if project is None:
                        continue
                    folder = parts[i + 1] if i + 1 < len(parts) else ""
                    phase = Phase.objects.filter(
                        project=project, slug=folder.split("-", 1)[-1]
                    ).first()
                    if phase is None:
                        continue
                    ingest.scan_project(project, settings)
                    break
        except Exception:
            logger.exception("watcher drain failed")

    def start(self):
        settings = AppSettings.load()
        root = settings.expanded_workspace_root()
        if not root or not settings.watch_enabled:
            return False
        self.stop()
        self.observer = Observer(timeout=1.0)
        self.observer.schedule(_Handler(self), root, recursive=True)
        self.observer.daemon = True
        self.observer.start()
        logger.info("watcher started on %s", root)
        return True

    def stop(self):
        if self.observer is not None:
            self.observer.stop()
            self.observer = None


watchers = WatcherManager()
