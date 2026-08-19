from django.shortcuts import get_object_or_404, render

from .. import revisions, workspace
from ..models import AppSettings, Document, Milestone, Phase


def phase_detail(request, project_slug, order):
    phase = get_object_or_404(
        Phase, project__slug=project_slug, order=order
    )
    project = phase.project
    phases = list(project.phases.all())

    current_docs = (
        Document.objects.filter(phase=phase, is_latest=True)
        .exclude(file_path__contains="/_archive/")
        .select_related("series")
        .order_by("-ingested_at")
    )
    archived = (
        Document.objects.filter(phase=phase, file_path__contains="/_archive/")
        .select_related("series")
        .order_by("-ingested_at")
    )
    unassigned = [
        d for d in Document.objects.filter(phase=phase, series__isnull=True)
        .exclude(file_path__contains="/_archive/")
        .order_by("-ingested_at")
    ]
    suggestions = {d.pk: revisions.suggest_predecessors(d) for d in unassigned}
    pending_milestones = Milestone.objects.filter(
        phase=phase, status=Milestone.Status.EXTRACTED
    ).select_related("document")
    digest = getattr(phase, "digest", None)

    try:
        phase_dir_path = str(
            workspace.phase_dir(AppSettings.load(), project, phase)
        )
    except RuntimeError:
        phase_dir_path = None

    context = {
        "project": project,
        "phase": phase,
        "phases": phases,
        "current_docs": current_docs,
        "archived": archived,
        "unassigned": unassigned,
        "suggestions": suggestions,
        "pending_milestones": pending_milestones,
        "digest": digest,
        "phase_dir_path": phase_dir_path,
    }
    if request.headers.get("HX-Request"):
        return render(request, "hub/_phase_body.html", context)
    return render(request, "hub/phase.html", context)
