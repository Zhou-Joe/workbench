"""Pipeline queue visibility: list jobs, surface failures, one-click retry."""

from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from ..events import bus
from ..models import ExtractionJob


def jobs(request):
    status_filter = request.GET.get("status", "")
    qs = ExtractionJob.objects.select_related(
        "document", "phase", "phase__project", "project", "question", "series"
    ).order_by("-pk")
    if status_filter:
        qs = qs.filter(status=status_filter)
    counts = {
        s: ExtractionJob.objects.filter(status=s).count()
        for s in ("queued", "running", "done", "failed")
    }
    return render(
        request,
        "hub/jobs.html",
        {
            "jobs": qs[:100],
            "counts": counts,
            "status_filter": status_filter,
        },
    )


@require_POST
def job_retry(request, job_id):
    job = get_object_or_404(ExtractionJob, pk=job_id)
    if job.status == ExtractionJob.Status.FAILED:
        job.status = ExtractionJob.Status.QUEUED
        job.error = ""
        job.save(update_fields=["status", "error"])
        bus.publish("jobs")
    return jobs(request)
