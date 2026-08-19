from django.shortcuts import redirect, render
from django.utils.text import slugify

from .. import workspace
from ..constants import PHASE_TEMPLATE
from ..events import bus
from ..models import AppSettings, Document, Milestone, Project, make_phase


def track_context(project):
    phases = list(project.phases.all())
    current = project.current_phase()
    latest = (
        Milestone.objects.filter(project=project)
        .exclude(status=Milestone.Status.DISMISSED)
        .order_by("-date", "-pk")[:3]
    )
    open_issues = Milestone.objects.filter(
        project=project, mtype__in=["issue", "risk", "action"]
    ).exclude(status=Milestone.Status.DISMISSED)
    pending = Milestone.objects.filter(
        project=project, status=Milestone.Status.EXTRACTED
    ).count()
    docs = Document.objects.filter(phase__project=project)
    return {
        "project": project,
        "phases": phases,
        "current": current,
        "latest": latest,
        "open_issues": open_issues.count(),
        "pending": pending,
        "doc_count": docs.count(),
    }


def home(request):
    projects = Project.objects.prefetch_related("phases").order_by("name")
    tracks = [track_context(p) for p in projects]
    return render(
        request,
        "hub/portfolio.html",
        {"tracks": tracks, "has_root": bool(AppSettings.load().expanded_workspace_root())},
    )


def project_create(request):
    name = request.POST.get("name", "").strip()
    if not name:
        if request.headers.get("HX-Request"):
            return render(
                request, "hub/_create_project.html", {"error": "Project needs a name."}
            )
        return redirect("hub:home")
    slug = slugify(name) or "project"
    unique, i = slug, 2
    while Project.objects.filter(slug=unique).exists():
        unique = f"{slug}-{i}"
        i += 1
    project = Project.objects.create(
        name=name,
        slug=unique,
        code=request.POST.get("code", "").strip(),
        description=request.POST.get("description", "").strip(),
    )
    for order, (phase_name, focus) in enumerate(PHASE_TEMPLATE, start=1):
        make_phase(project, phase_name, order, focus)
    scaffold_warning = ""
    try:
        workspace.scaffold_project(AppSettings.load(), project, project.phases.all())
    except RuntimeError as exc:
        scaffold_warning = str(exc)
    bus.publish("project", slug=project.slug)
    if request.headers.get("HX-Request"):
        return render(
            request,
            "hub/_track.html",
            {**track_context(project), "scaffold_warning": scaffold_warning, "created": True},
        )
    return redirect("hub:project", slug=project.slug)
