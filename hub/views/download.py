"""Downloads: single files, folders, and multi-file selections as ZIP.

Every path is validated against the workspace root — nothing outside the
user's folders can ever be requested. Dotfiles and _archive/ folders are
excluded from ZIP contents, matching what the browser shows.
"""

import os
import tempfile
import zipfile
from pathlib import Path

from django.http import FileResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET

from .. import workspace
from ..models import AppSettings, Phase

DL_SVG = (
    '<svg class="dl-icon" width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">'
    '<path d="M8 1v8M4.5 6.5 8 10l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.6"/>'
    '<path d="M2 12v2h12v-2" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>'
)


def _resolved_root(settings):
    root = settings.expanded_workspace_root()
    if not root:
        raise RuntimeError("Workspace root is not configured")
    return Path(root).resolve()


def _safe_file(settings, rel):
    root = _resolved_root(settings)
    candidate = (root / (rel or "")).resolve()
    if candidate == root or not str(candidate).startswith(str(root) + os.sep):
        return None
    if not candidate.is_file():
        return None
    return candidate


def _safe_dir(settings, project_slug, phase_order, rel_path):
    root = _resolved_root(settings)
    try:
        phase = Phase.objects.select_related("project").get(
            project__slug=project_slug, order=phase_order
        )
    except Phase.DoesNotExist:
        return None
    base = workspace.phase_dir(settings, phase.project, phase).resolve()
    target = workspace.safe_subpath(base, rel_path)
    if not target.is_dir():
        return None
    return target


def _zip_response(entries, zip_name):
    """entries: list of (abs_path, arcname). Streams a ZIP via a spooled
    temp file so large folders don't sit in memory."""
    entries = list(entries)
    if not entries:
        return HttpResponseBadRequest("nothing to download")
    buf = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
    seen = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for abs_path, arcname in entries:
            name = arcname
            i = 2
            while name in seen:
                stem, dot, ext = arcname.rpartition(".")
                name = f"{stem or arcname}-{i}.{ext}" if dot else f"{arcname}-{i}"
                i += 1
            seen.add(name)
            zf.write(abs_path, name)
    buf.seek(0)
    resp = FileResponse(
        buf,
        as_attachment=True,
        filename=zip_name,
        content_type="application/zip",
    )
    return resp


def _dir_entries(dir_path):
    entries = []
    for child in sorted(dir_path.rglob("*")):
        if child.is_symlink():
            continue  # never follow links out of the workspace
        rel = child.relative_to(dir_path)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if workspace.ARCHIVE_DIR in rel.parts:
            continue
        if child.is_file():
            entries.append((child, rel.as_posix()))
    return entries


@require_GET
def download_file(request):
    try:
        settings = AppSettings.load()
        target = _safe_file(settings, request.GET.get("path", ""))
    except RuntimeError as exc:
        return HttpResponseBadRequest(str(exc))
    if target is None:
        return HttpResponseBadRequest("file not found")
    return FileResponse(
        open(target, "rb"), as_attachment=True, filename=target.name
    )


@require_GET
def download_folder(request):
    try:
        settings = AppSettings.load()
        target = _safe_dir(
            settings,
            request.GET.get("project", ""),
            request.GET.get("phase", ""),
            request.GET.get("path", ""),
        )
    except (RuntimeError, ValueError) as exc:
        return HttpResponseBadRequest(str(exc))
    if target is None:
        return HttpResponseBadRequest("folder not found")
    return _zip_response(_dir_entries(target), f"{target.name}.zip")


@require_GET
def download_zip(request):
    paths = request.GET.getlist("p")
    if not paths:
        return HttpResponseBadRequest("no files selected")
    try:
        settings = AppSettings.load()
        root = _resolved_root(settings)
        entries = []
        for rel in paths:
            target = _safe_file(settings, rel)
            if target is not None:
                # sanitized arcname — never trust the raw client path
                entries.append(
                    (target, target.relative_to(root).as_posix())
                )
    except RuntimeError as exc:
        return HttpResponseBadRequest(str(exc))
    return _zip_response(entries, "ridehub-selection.zip")
