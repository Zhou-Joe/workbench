from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from ..models import ExtractionJob, Milestone
from ..worker import parse_date


def _queue_digest(milestone):
    ExtractionJob.objects.get_or_create(
        phase=milestone.phase,
        kind=ExtractionJob.Kind.DIGEST,
        status=ExtractionJob.Status.QUEUED,
    )


def _row(request, milestone):
    """Row actions swap nothing (bare <tr> fragments don't parse reliably in
    htmx); the HX-Trigger header makes the enclosing region refresh instead."""
    response = render(
        request,
        "hub/_milestone_row.html",
        {
            "m": milestone,
            "dep_candidates": milestone.project.milestones.exclude(
                pk=milestone.pk
            ).exclude(status="dismissed").order_by("-date", "-pk")[:30],
        },
    )
    response["HX-Trigger"] = "rph:tick"
    return response


@require_POST
def milestone_action(request, ms_id):
    action = request.POST.get("action", "")
    milestone = get_object_or_404(Milestone, pk=ms_id)
    if action == "confirm":
        if milestone.status == Milestone.Status.EXTRACTED:
            milestone.status = Milestone.Status.CONFIRMED
    elif action == "dismiss":
        milestone.status = Milestone.Status.DISMISSED
    elif action == "restore":
        milestone.status = Milestone.Status.EXTRACTED
    milestone.save(update_fields=["status", "updated_at"])
    _queue_digest(milestone)
    return _row(request, milestone)


@require_POST
def milestone_edit(request, ms_id):
    milestone = get_object_or_404(Milestone, pk=ms_id)
    milestone.title = request.POST.get("title", milestone.title).strip()[:400]
    milestone.date = parse_date(request.POST.get("date", "")) or milestone.date
    mtype = request.POST.get("mtype", "")
    if mtype in {c.value for c in Milestone.MType}:
        milestone.mtype = mtype
    milestone.notes = request.POST.get("notes", "").strip()
    milestone.status = Milestone.Status.EDITED
    milestone.save()
    if "depends_on" in request.POST:
        pks = [
            int(v)
            for v in request.POST.getlist("depends_on")
            if v.isdigit()
        ]
        allowed = milestone.project.milestones.filter(pk__in=pks).exclude(
            pk=milestone.pk
        )
        milestone.depends_on.set(allowed)
    _queue_digest(milestone)
    return _row(request, milestone)
