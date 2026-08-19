from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils.timezone import localtime
from django.views.decorators.http import require_POST

from .. import extract, revisions, workspace
from ..models import AppSettings, Document, Milestone, Phase

# group order: PDF, office docs, email, CAD, images, everything else last
_KIND_CATEGORY = {
    "pdf": 0,
    "office": 1,
    "email": 2,
    "cad": 3,
    "image": 4,
    "other": 9,
}


def _format_key(extension):
    ext = (extension or "").lstrip(".").lower()
    kind = extract.kind_for_extension("." + ext) if ext else "other"
    return (_KIND_CATEGORY.get(kind, 9), ext or "file")


def _display_date(dt):
    if dt is None:
        return "—"
    return localtime(dt).strftime("%Y-%m-%d")


def group_by_format(items, ext_of, time_of):
    """Group items by file format; groups ordered PDF → office → email →
    CAD → image → other (alphabetical inside a category), newest first
    within each group."""
    buckets = {}
    for item in items:
        key = _format_key(ext_of(item))
        buckets.setdefault(key, []).append(item)
    groups = []
    for key in sorted(buckets):
        items_in = sorted(buckets[key], key=time_of, reverse=True)
        label = key[1].upper()
        groups.append({"label": label, "items": items_in})
    return groups


def _browse_path(request, phase, settings):
    """Validated current sub-folder from ?path= (or POST body)."""
    raw = request.GET.get("path", "") or request.POST.get("path", "")
    # resolve() on both sides — macOS temp dirs sit behind /var → /private/var
    base = workspace.phase_dir(settings, phase.project, phase).resolve()
    target = workspace.safe_subpath(base, raw)
    try:
        rel = target.relative_to(base)
        current = rel.as_posix() if str(rel) != "." else ""
    except ValueError:
        current = ""
    return current, base / current if current else base


def _listing(phase, settings, current, cur_dir):
    """Finder-style listing: folders first, then files, with DB metadata."""
    ws_root = Path(settings.expanded_workspace_root()).resolve()
    docs_by_path = {
        d.file_path: d
        for d in Document.objects.filter(phase=phase).select_related("series")
    }
    folders, files = [], []
    if cur_dir.exists():
        for child in sorted(cur_dir.iterdir(), key=lambda p: p.name.lower()):
            name = child.name
            if name.startswith(".") or name == workspace.ARCHIVE_DIR:
                continue
            if child.is_dir():
                folders.append(
                    {
                        "name": name,
                        "count": workspace.folder_item_count(child),
                        "path": f"{current}/{name}" if current else name,
                    }
                )
            elif child.is_file():
                rel = child.relative_to(ws_root).as_posix()
                try:
                    stat = child.stat()
                except OSError:
                    stat = None
                files.append(
                    {
                        "name": name,
                        "rel": rel,
                        "size": stat.st_size if stat else 0,
                        "mtime": stat.st_mtime if stat else 0,
                        "modified": _display_date(
                            datetime.fromtimestamp(stat.st_mtime, tz=dt_timezone.utc)
                        )
                        if stat
                        else "—",
                        "doc": docs_by_path.get(rel),
                    }
                )
    return folders, files


def _phase_url(project, phase, path=""):
    from django.urls import reverse

    url = reverse("hub:phase", args=[project.slug, phase.order])
    return f"{url}?path={path}" if path else url


def phase_detail(request, project_slug, order):
    phase = get_object_or_404(
        Phase, project__slug=project_slug, order=order
    )
    project = phase.project
    settings = AppSettings.load()
    phases = list(project.phases.all())

    try:
        current, cur_dir = _browse_path(request, phase, settings)
        phase_dir_path = str(workspace.phase_dir(settings, project, phase))
    except RuntimeError:
        current, cur_dir, phase_dir_path = "", None, None

    folders = files = []
    file_groups = []
    if cur_dir is not None:
        folders, files = _listing(phase, settings, current, cur_dir)
        file_groups = group_by_format(
            files,
            ext_of=lambda f: Path(f["name"]).suffix,
            time_of=lambda f: f["mtime"],
        )

    # root-only panels: phase-wide concerns
    unassigned = pending_milestones = archived = archived_groups = None
    suggestions = {}
    digest = getattr(phase, "digest", None)
    if not current:
        unassigned = list(
            Document.objects.filter(phase=phase, series__isnull=True)
            .exclude(file_path__contains="/_archive/")
            .order_by("-ingested_at")
        )
        suggestions = {d.pk: revisions.suggest_predecessors(d) for d in unassigned}
        pending_milestones = Milestone.objects.filter(
            phase=phase, status=Milestone.Status.EXTRACTED
        ).select_related("document")
        archived = list(
            Document.objects.filter(phase=phase, file_path__contains="/_archive/")
            .select_related("series")
            .order_by("-ingested_at")
        )
        archived_groups = group_by_format(
            archived,
            ext_of=lambda d: d.extension,
            time_of=lambda d: d.ingested_at,
        )

    # breadcrumb segments with cumulative paths
    crumbs = []
    acc = ""
    if current:
        for seg in current.split("/"):
            acc = f"{acc}/{seg}" if acc else seg
            crumbs.append({"name": seg, "path": acc})

    context = {
        "project": project,
        "phase": phase,
        "phases": phases,
        "current": current,
        "crumbs": crumbs,
        "folders": folders,
        "files": files,
        "file_groups": file_groups,
        "archived_groups": archived_groups,
        "phase_dir_path": phase_dir_path,
        "phase_url": _phase_url(project, phase, current),
        "unassigned": unassigned,
        "suggestions": suggestions,
        "pending_milestones": pending_milestones,
        "archived": archived,
        "digest": digest,
    }
    if request.headers.get("HX-Request"):
        return render(request, "hub/_phase_body.html", context)
    return render(request, "hub/phase.html", context)


@require_POST
def phase_folder_new(request, project_slug, order):
    phase = get_object_or_404(Phase, project__slug=project_slug, order=order)
    name = request.POST.get("name", "").strip()
    if not name:
        return HttpResponseBadRequest("folder needs a name")
    try:
        settings = AppSettings.load()
        workspace.create_subfolder(
            settings,
            phase.project,
            phase,
            request.POST.get("path", ""),
            name,
        )
    except RuntimeError as exc:
        return HttpResponseBadRequest(str(exc))
    return phase_detail(request, project_slug, order)
