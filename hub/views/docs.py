from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .. import revisions
from ..events import bus
from ..models import ArchiveMove, Document, DocumentSeries, ExtractionJob


def _phase_body(request, phase):
    from .phase import phase_detail

    return phase_detail(request, phase.project.slug, phase.order)


@require_POST
def assign_new_series(request, doc_id):
    doc = get_object_or_404(Document, pk=doc_id)
    title = request.POST.get("title", "").strip() or doc.filename
    revisions.assign_new_series(doc, title)
    return _phase_body(request, doc.phase)


@require_POST
def assign_predecessor(request, doc_id):
    doc = get_object_or_404(Document, pk=doc_id)
    predecessor = get_object_or_404(
        Document, pk=request.POST.get("predecessor_id"), phase=doc.phase
    )
    if predecessor.pk == doc.pk:
        return _phase_body(request, doc.phase)
    revisions.supersede(doc, predecessor)
    return _phase_body(request, doc.phase)


@require_POST
def undo_archive(request, move_id):
    move = get_object_or_404(ArchiveMove, pk=move_id, undone=False)
    revisions.undo_archive(move)
    return _phase_body(request, move.document.phase)


def series_stack(request, series_id):
    series = get_object_or_404(DocumentSeries, pk=series_id)
    stack = revisions.series_stack(series)
    moves = {
        m.document_id: m
        for m in ArchiveMove.objects.filter(
            document__in=stack, undone=False
        ).select_related("document")
    }
    delta_queued = ExtractionJob.objects.filter(
        series=series, kind=ExtractionJob.Kind.DELTA
    ).exclude(status=ExtractionJob.Status.FAILED).exists()
    return render(
        request,
        "hub/_series_stack.html",
        {
            "series": series,
            "stack": stack,
            "moves": moves,
            "delta_queued": delta_queued,
        },
    )


@require_POST
def series_delta(request, series_id):
    series = get_object_or_404(DocumentSeries, pk=series_id)
    if series.revisions.count() >= 2:
        ExtractionJob.objects.get_or_create(
            series=series,
            kind=ExtractionJob.Kind.DELTA,
            status=ExtractionJob.Status.QUEUED,
        )
    bus.publish("revision", project_id=series.phase.project_id, phase_id=series.phase_id)
    return series_stack(request, series_id)
