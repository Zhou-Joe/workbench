"""Revision management: series assignment, suggestions, supersede, undo."""

import difflib
import re

from django.utils import timezone

from . import workspace
from .events import bus
from .models import ArchiveMove, Document, DocumentSeries

REVISION_MARKERS = [
    re.compile(r"(?<![a-z0-9])rev(?:ision)?[.\s_-]*\d+[a-z]?\b", re.I),
    re.compile(r"(?<![a-z0-9])rev[.\s_-]*[a-z]\b", re.I),
    re.compile(r"(?<![a-z0-9])ver(?:sion)?[.\s_-]*\d+[a-z]?\b", re.I),
    re.compile(r"(?<![a-z0-9])v[.\s_-]*\d+\b", re.I),
    re.compile(r"(?<![a-z0-9])r[.\s_-]*\d+\b", re.I),
    re.compile(r"[_\s-]final\b", re.I),
    re.compile(r"[_\s-]issued\b", re.I),
    re.compile(r"\d{4}[-_.]?\d{2}[-_.]?\d{2}"),
    re.compile(r"[_\s-]copy(?:\s*\d+)?$", re.I),
]


def normalize_stem(filename):
    """Lowercase the stem with revision markers stripped, for similarity."""
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    stem = stem.lower()
    for marker in REVISION_MARKERS:
        stem = marker.sub(" ", stem)
    return re.sub(r"[^a-z0-9]+", " ", stem).strip()


def similarity(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def _phase_relative(doc):
    prefix = f"{doc.phase.project.slug}/{doc.phase.folder_name}/"
    return doc.file_path[len(prefix):] if doc.file_path.startswith(prefix) else doc.filename


def _norm_key(doc):
    """Location + filename, both normalized, so candidates in the same
    sub-folder outrank same-named files elsewhere in the phase."""
    rel = _phase_relative(doc)
    dirpart, _, filename = rel.rpartition("/")
    dir_n = re.sub(r"[^a-z0-9]+", " ", dirpart.lower()).strip()
    stem_n = normalize_stem(filename)
    return (dir_n + " " + stem_n).strip()


def suggest_predecessors(doc, limit=5, floor=0.5, candidates=None):
    """Candidate docs this file might supersede: same phase, latest or
    unassigned, ranked by location-aware filename similarity. Pass
    pre-fetched deferred-field candidates to avoid per-doc queries."""
    norm = _norm_key(doc)
    if candidates is None:
        candidates = Document.objects.filter(phase=doc.phase).exclude(pk=doc.pk)
    scored = []
    for cand in candidates:
        if cand.pk == doc.pk:
            continue
        if cand.is_archived:
            continue
        if cand.series_id and not cand.is_latest:
            continue
        # a replacement of the same path is always the strongest signal
        same_path = cand.file_path == doc.file_path
        score = 1.0 if same_path else similarity(norm, _norm_key(cand))
        if same_path or score >= floor:
            scored.append((score, cand))
    scored.sort(key=lambda pair: (-pair[0], pair[1].filename))
    return [cand for _, cand in scored[:limit]]


def assign_new_series(doc, title):
    series = DocumentSeries.objects.create(phase=doc.phase, title=title)
    _apply_assignment(doc, series, predecessor=None)
    return series


def supersede(doc, predecessor):
    """doc replaces predecessor within its series."""
    if predecessor.series_id:
        series = predecessor.series
    else:
        series = DocumentSeries.objects.create(
            phase=predecessor.phase, title=predecessor.filename
        )
        _apply_assignment(predecessor, series, predecessor=None)
    _apply_assignment(doc, series, predecessor=predecessor)
    return series


def _apply_assignment(doc, series, predecessor):
    doc.series = series
    doc.revision_number = _max_revision(series) + 1
    doc.is_latest = True
    doc.save(update_fields=["series", "revision_number", "is_latest"])
    if predecessor is not None:
        predecessor.is_latest = False
        predecessor.save(update_fields=["is_latest"])
        _archive(predecessor)


def _max_revision(series):
    latest_num = 0
    for rev in series.revisions.values_list("revision_number", flat=True):
        if rev and rev > latest_num:
            latest_num = rev
    return latest_num


def _archive(doc):
    from .models import AppSettings

    settings = AppSettings.load()
    if settings.archive_mode != AppSettings.ArchiveMode.MOVE:
        return
    result = workspace.archive_file(settings, doc)
    if result is None:
        return
    from_rel, to_rel = result
    ArchiveMove.objects.create(document=doc, from_path=from_rel, to_path=to_rel)
    doc.file_path = to_rel
    doc.save(update_fields=["file_path"])
    bus.publish("revision", project_id=doc.phase.project_id, phase_id=doc.phase_id)


def undo_archive(move):
    """Reverse an archive move; the restored doc becomes latest again."""
    from .models import AppSettings

    settings = AppSettings.load()
    if settings.archive_mode == AppSettings.ArchiveMode.MOVE:
        if not workspace.restore_file(settings, move.from_path, move.to_path):
            return False
    doc = move.document
    series = doc.series
    doc.file_path = move.from_path
    doc.is_latest = True
    doc.save(update_fields=["file_path", "is_latest"])
    if series:
        for rev in series.revisions.exclude(pk=doc.pk):
            if rev.revision_number and rev.revision_number > (doc.revision_number or 0):
                rev.is_latest = False
                rev.save(update_fields=["is_latest"])
    move.undone = True
    move.undone_at = timezone.now()
    move.save(update_fields=["undone", "undone_at"])
    bus.publish("revision", project_id=doc.phase.project_id, phase_id=doc.phase_id)
    return True


def series_stack(series):
    return list(series.revisions.order_by("revision_number", "ingested_at"))
