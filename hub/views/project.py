from django.shortcuts import get_object_or_404, render

from .. import ingest, workspace
from ..events import bus
from ..models import AppSettings, Document, Milestone, Phase, Project, make_phase


def _rail_context(project):
    from django.db.models import Count

    phases = list(project.phases.all())
    docs_counts = dict(
        Document.objects.filter(phase__project=project, is_latest=True)
        .exclude(file_path__contains="/_archive/")
        .values_list("phase")
        .annotate(n=Count("pk"))
    )
    unassigned_counts = dict(
        Document.objects.filter(phase__project=project, series__isnull=True)
        .exclude(file_path__contains="/_archive/")
        .values_list("phase")
        .annotate(n=Count("pk"))
    )
    pending_counts = dict(
        Milestone.objects.filter(
            phase__project=project, status=Milestone.Status.EXTRACTED
        )
        .values_list("phase")
        .annotate(n=Count("pk"))
    )
    return {
        "project": project,
        "phases": phases,
        "docs_by_phase": docs_counts,
        "unassigned_by_phase": unassigned_counts,
        "pending_by_phase": pending_counts,
    }


def _ledger_context(request, project, notice=""):
    ctx = _rail_context(project)
    phase_filter = request.GET.get("phase", "")
    type_filter = request.GET.get("type", "")
    status_filter = request.GET.get("status", "")

    milestones = Milestone.objects.filter(project=project).select_related(
        "phase", "document"
    )
    if phase_filter:
        milestones = milestones.filter(phase__slug=phase_filter)
    if type_filter:
        milestones = milestones.filter(mtype=type_filter)
    if status_filter:
        milestones = milestones.filter(status=status_filter)
    else:
        milestones = milestones.exclude(status=Milestone.Status.DISMISSED)
    ctx.update(
        {
            "milestones": milestones.order_by("-date", "-pk"),
            "phase_filter": phase_filter,
            "type_filter": type_filter,
            "status_filter": status_filter,
            "type_choices": Milestone.MType.choices,
            "status_choices": Milestone.Status.choices,
            "notice": notice,
        }
    )
    return ctx


def project_detail(request, slug):
    project = get_object_or_404(Project, slug=slug)
    context = _ledger_context(request, project)
    from .tasks import tasks_context

    context.update(tasks_context(project))
    if request.headers.get("HX-Request"):
        return render(request, "hub/_ledger.html", context)
    return render(request, "hub/project.html", context)


def _renumber(project):
    """Reassign sequential orders and rename folders to match."""
    for i, phase in enumerate(project.phases.all(), start=1):
        if phase.order != i:
            phase.order = i
            phase.save(update_fields=["order"])
    workspace.sync_phase_dirs(AppSettings.load(), project)


def _hx_rail(request, project):
    if request.headers.get("HX-Request"):
        return render(request, "hub/_phase_rail.html", _rail_context(project))
    return None


def phase_add(request, slug):
    project = get_object_or_404(Project, slug=slug)
    name = request.POST.get("name", "").strip()
    if not name:
        return _hx_rail(request, project) or render(
            request, "hub/project.html", _ledger_context(request, project)
        )
    focus = request.POST.get("extraction_focus", "").strip()
    position = request.POST.get("position", "end")
    existing = set(project.phases.values_list("slug", flat=True))
    phases = list(project.phases.all())
    if position.startswith("after:"):
        try:
            after = int(position.split(":", 1)[1])
        except ValueError:
            after = len(phases)
        order = after + 1
        # shift from the highest order down — forward iteration would
        # transiently collide with the unique (project, order) constraint
        for ph in reversed(phases):
            if ph.order >= order:
                ph.order += 1
                ph.save(update_fields=["order"])
    else:
        order = len(phases) + 1
    from ..models import Phase

    phase = Phase.objects.create(
        project=project,
        name=name,
        slug=workspace.slugify_folder(name, existing),
        order=order,
        extraction_focus=focus,
    )
    _renumber(project)
    bus.publish("phase", project_id=project.pk)
    return _hx_rail(request, project) or _redirect_project(project)


def _redirect_project(project):
    from django.shortcuts import redirect

    return redirect("hub:project", slug=project.slug)


def phase_rename(request, slug, phase_id):
    project = get_object_or_404(Project, slug=slug)
    phase = get_object_or_404(Phase, pk=phase_id, project=project)
    name = request.POST.get("name", "").strip()
    if name and name != phase.name:
        old_folder = phase.folder_name
        phase.name = name
        others = set(
            project.phases.exclude(pk=phase.pk).values_list("slug", flat=True)
        )
        phase.slug = workspace.slugify_folder(name, others)
        phase.save(update_fields=["name", "slug"])
        root = workspace.project_root(AppSettings.load(), project)
        old_dir = root / old_folder
        new_dir = root / phase.folder_name
        if old_dir.exists() and old_dir != new_dir and not new_dir.exists():
            old_dir.rename(new_dir)
            workspace._rewrite_document_prefix(
                project,
                f"{project.slug}/{old_folder}/",
                f"{project.slug}/{new_dir.name}/",
            )
    focus = request.POST.get("extraction_focus", "").strip()
    if focus != phase.extraction_focus:
        phase.extraction_focus = focus
        phase.save(update_fields=["extraction_focus"])
    from .phase import phase_detail

    return phase_detail(request, project.slug, phase.order)


def phase_move(request, slug, phase_id):
    project = get_object_or_404(Project, slug=slug)
    phase = get_object_or_404(Phase, pk=phase_id, project=project)
    direction = request.POST.get("direction", "up")
    phases = list(project.phases.all())
    idx = phases.index(phase)
    swap_with = idx - 1 if direction == "up" else idx + 1
    if 0 <= swap_with < len(phases):
        other = phases[swap_with]
        # swap via a temp order slot — a direct swap would transiently
        # violate the unique (project, order) constraint
        from django.db.models import Max

        temp = (project.phases.aggregate(m=Max("order"))["m"] or 0) + 1
        old_phase, old_other = phase.order, other.order
        phase.order = temp
        phase.save(update_fields=["order"])  # frees old_phase
        other.order = old_phase
        other.save(update_fields=["order"])  # frees old_other
        phase.order = old_other
        phase.save(update_fields=["order"])
        _renumber(project)
    bus.publish("phase", project_id=project.pk)
    return _hx_rail(request, project) or _redirect_project(project)


def project_rescan(request, slug):
    project = get_object_or_404(Project, slug=slug)
    notice = ""
    try:
        new, replaced = ingest.rescan(project)
        notice = (
            f"Scan complete: {len(new)} new file(s), {len(replaced)} replacement(s)."
        )
    except (RuntimeError, OSError) as exc:
        notice = str(exc)
    if request.headers.get("HX-Request"):
        return render(
            request, "hub/_ledger.html", _ledger_context(request, project, notice)
        )
    from django.contrib import messages

    messages.success(request, notice)
    return _redirect_project(project)


def project_decisions(request, slug):
    """Decision register: every confirmed/extracted decision, newest first."""
    project = get_object_or_404(Project, slug=slug)
    decisions = (
        Milestone.objects.filter(project=project, mtype=Milestone.MType.DECISION)
        .exclude(status=Milestone.Status.DISMISSED)
        .select_related("phase", "document")
        .order_by("-date", "-pk")
    )
    return render(
        request,
        "hub/decisions.html",
        {"project": project, "decisions": decisions},
    )


def project_report(request, slug):
    """Weekly report: latest generated report + generate button."""
    from django.shortcuts import redirect

    from ..models import ExtractionJob

    project = get_object_or_404(Project, slug=slug)
    if request.method == "POST":
        ExtractionJob.objects.get_or_create(
            project=project,
            kind=ExtractionJob.Kind.REPORT,
            status=ExtractionJob.Status.QUEUED,
        )
        return redirect("hub:project_report", slug=slug)
    latest = project.reports.first()
    generating = ExtractionJob.objects.filter(
        project=project,
        kind=ExtractionJob.Kind.REPORT,
        status__in=[ExtractionJob.Status.QUEUED, ExtractionJob.Status.RUNNING],
    ).exists()
    failed = (
        ExtractionJob.objects.filter(
            project=project,
            kind=ExtractionJob.Kind.REPORT,
            status=ExtractionJob.Status.FAILED,
        )
        .order_by("-pk")
        .first()
    )
    return render(
        request,
        "hub/report.html",
        {
            "project": project,
            "report": latest,
            "generating": generating,
            "failed_error": failed.error if failed else "",
        },
    )
