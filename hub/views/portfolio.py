from datetime import date

from django.shortcuts import redirect, render
from django.utils.text import slugify

from .. import workspace
from ..constants import PHASE_TEMPLATE
from ..events import bus
from ..models import AppSettings, Document, Milestone, Project, make_phase

AGING_WARN_DAYS = 14


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


def attention_context():
    """Cross-project Now/Next data: pending reviews, aging open items,
    files awaiting series assignment."""
    today = date.today()
    pending_review = list(
        Milestone.objects.filter(status=Milestone.Status.EXTRACTED)
        .select_related("phase", "phase__project", "document")
        .order_by("-date", "-pk")[:15]
    )
    open_items = []
    for m in (
        Milestone.objects.filter(mtype__in=["issue", "risk", "action"])
        .exclude(status=Milestone.Status.DISMISSED)
        .select_related("phase", "phase__project")
        .order_by("date", "pk")
    ):
        base = m.date or m.created_at.date()
        age = max(0, (today - base).days)
        level = ""
        if m.date and m.date < today:
            level = "over"
        elif age >= AGING_WARN_DAYS:
            level = "warn"
        open_items.append({"m": m, "date": base, "age": age, "level": level})
    open_items.sort(key=lambda item: -item["age"])
    unassigned = list(
        Document.objects.filter(series__isnull=True)
        .exclude(file_path__contains="/_archive/")
        .select_related("phase", "phase__project")
        .order_by("-ingested_at")[:10]
    )
    from .search import match_count
    from ..models import SavedSearch

    search_alerts = []
    for saved in SavedSearch.objects.all():
        current = match_count(saved.query)
        if current > saved.last_count:
            search_alerts.append(
                {
                    "saved": saved,
                    "new": current - saved.last_count,
                    "total": current,
                }
            )
    return {
        "pending_review": pending_review,
        "open_items": open_items[:15],
        "unassigned": unassigned,
        "search_alerts": search_alerts,
    }


def home(request):
    projects = Project.objects.prefetch_related("phases").order_by("name")
    tracks = [track_context(p) for p in projects]
    from ..models import Protocol

    return render(
        request,
        "hub/portfolio.html",
        {
            "tracks": tracks,
            "has_root": bool(AppSettings.load().expanded_workspace_root()),
            "protocols": Protocol.objects.prefetch_related("phases"),
            **attention_context(),
        },
    )


def _protocol_phases(request):
    """Resolve the chosen protocol's phases, falling back to the built-in
    six-phase ride template when none exist yet."""
    from ..models import Protocol

    proto = None
    protocol_id = request.POST.get("protocol", "")
    if protocol_id:
        proto = Protocol.objects.filter(pk=protocol_id).first()
    if proto is None:
        proto = Protocol.objects.filter(is_default=True).first()
    if proto and proto.phases.exists():
        return proto, [(p.name, p.extraction_focus) for p in proto.phases.all()]
    return proto, list(PHASE_TEMPLATE)


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
    proto, phases = _protocol_phases(request)
    project = Project.objects.create(
        name=name,
        slug=unique,
        code=request.POST.get("code", "").strip(),
        description=request.POST.get("description", "").strip(),
        protocol=proto,
    )
    for order, (phase_name, focus) in enumerate(phases, start=1):
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
