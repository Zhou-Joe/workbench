"""Browser drag-and-drop upload into a phase folder (Finder-style browsing)."""

from pathlib import Path

from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from .. import ingest, workspace
from ..models import AppSettings, Phase


@require_POST
def phase_upload(request, project_slug, order):
    phase = get_object_or_404(
        Phase, project__slug=project_slug, order=order
    )
    settings = AppSettings.load()
    files = request.FILES.getlist("files")
    if not files:
        return HttpResponseBadRequest("no files")
    try:
        # current browsed folder + optional extra sub-folder relative to it
        base = workspace.safe_subpath(
            workspace.phase_dir(settings, phase.project, phase),
            request.POST.get("path", ""),
        )
        folder = request.POST.get("folder", "").strip().strip("/")
        segments = [
            s
            for s in folder.split("/")
            if s and not s.startswith(".") and s not in ("..", workspace.ARCHIVE_DIR)
        ]
        target_dir = base.joinpath(*segments) if segments else base
        target_dir.mkdir(parents=True, exist_ok=True)
    except RuntimeError as exc:
        return HttpResponseBadRequest(str(exc))

    for uploaded in files:
        # basename only — never trust client paths
        name = Path(uploaded.name).name
        if not name or name.startswith("."):
            continue
        dest = target_dir / name
        with open(dest, "wb") as out:
            for chunk in uploaded.chunks():
                out.write(chunk)

    ingest.scan_project(phase.project, settings)
    from .docs import _phase_body

    return _phase_body(request, phase)
