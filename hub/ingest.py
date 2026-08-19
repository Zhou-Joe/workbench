"""Scan the workspace and index files as Documents + ExtractionJobs."""

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import extract, workspace
from .events import publish_doc_event
from .models import AppSettings, Document, ExtractionJob, Phase, Project

logger = logging.getLogger(__name__)


def checksum_of(path, chunk_size=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def scan_project(project, settings=None):
    """Reconcile disk state with the database for one project.
    Returns (new_docs, replaced_docs)."""
    settings = settings or AppSettings.load()
    new_docs, replaced_docs = [], []
    root = workspace.project_root(settings, project)
    if not root.exists():
        return new_docs, replaced_docs

    ws_root = Path(settings.expanded_workspace_root())
    for phase in project.phases.all():
        pdir = root / phase.folder_name
        if not pdir.exists():
            continue
        for file_path in sorted(pdir.rglob("*")):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(ws_root).as_posix()
            if f"/{workspace.ARCHIVE_DIR}/" in f"/{rel}":
                _ensure_archived_indexed(phase, file_path, rel, root, settings)
                continue
            if file_path.parent != pdir:
                continue  # only phase-root files are "current deliverables"
            doc = _ingest_file(phase, file_path, rel, root, settings)
            if doc is None:
                continue
            if doc.filename and _is_replacement(doc):
                replaced_docs.append(doc)
            else:
                new_docs.append(doc)
    return new_docs, replaced_docs


def scan_all(settings=None):
    settings = settings or AppSettings.load()
    total_new, total_replaced = [], []
    for project in Project.objects.all():
        try:
            new, replaced = scan_project(project, settings)
            total_new.extend(new)
            total_replaced.extend(replaced)
        except RuntimeError:
            raise
        except Exception:
            logger.exception("scan failed for project %s", project.slug)
    return total_new, total_replaced


def _is_replacement(doc):
    """A doc whose (phase, file_path) previously existed with another checksum."""
    return (
        Document.objects.filter(phase=doc.phase, file_path=doc.file_path)
        .exclude(pk=doc.pk)
        .exists()
    )


def _ingest_file(phase, file_path, rel, root, settings):
    """Create a Document + parse job for a file if not yet indexed."""
    try:
        stat = file_path.stat()
    except OSError:
        return None
    checksum = checksum_of(file_path)
    existing = Document.objects.filter(
        phase=phase, file_path=rel, checksum=checksum
    ).first()
    if existing:
        return None
    ext = file_path.suffix.lower()
    doc = Document.objects.create(
        phase=phase,
        file_path=rel,
        filename=file_path.name,
        extension=ext,
        size_bytes=stat.st_size,
        file_mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        checksum=checksum,
        doc_kind=extract.kind_for_extension(ext),
    )
    ExtractionJob.objects.create(document=doc, kind=ExtractionJob.Kind.PARSE)
    publish_doc_event(doc, "detected")
    return doc


def _ensure_archived_indexed(phase, file_path, rel, root, settings):
    """Files under _archive/ are indexed as superseded revisions (no jobs)."""
    checksum = checksum_of(file_path)
    if Document.objects.filter(phase=phase, file_path=rel, checksum=checksum).exists():
        return
    try:
        stat = file_path.stat()
    except OSError:
        return
    ext = file_path.suffix.lower()
    Document.objects.create(
        phase=phase,
        file_path=rel,
        filename=file_path.name,
        extension=ext,
        size_bytes=stat.st_size,
        file_mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        checksum=checksum,
        doc_kind=extract.kind_for_extension(ext),
        is_latest=False,
        extraction_status=Document.Status.DONE,
        quality_note="indexed from _archive on scan; not re-extracted",
    )


def rescan(project):
    """Public entry used by the UI button; also refreshes folder scaffolding."""
    settings = AppSettings.load()
    workspace.sync_phase_dirs(settings, project)
    return scan_project(project, settings)


def watch_targets(settings):
    root = settings.expanded_workspace_root()
    if not root:
        return {}
    folders = {}
    for project in Project.objects.all():
        proot = Path(root) / project.slug
        if not proot.exists():
            continue
        for phase in project.phases.all():
            folders[phase.folder_name] = phase
    return folders
