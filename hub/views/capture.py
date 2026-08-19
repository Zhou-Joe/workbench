"""Quick capture: dump a note from anywhere; the LLM suggests where it goes;
one click files it as a real markdown document through the full pipeline."""

from datetime import datetime

from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .. import ingest, workspace
from ..events import bus
from ..models import AppSettings, Capture, ExtractionJob, Phase, Project


def inbox(request):
    return render(request, "hub/inbox.html", _inbox_context())


def capture(request):
    if request.method == "POST":
        text = request.POST.get("q", "").strip()
        if text:
            capture_obj = Capture.objects.create(text=text[:4000])
            ExtractionJob.objects.create(
                capture=capture_obj, kind=ExtractionJob.Kind.CAPTURE
            )
            bus.publish("capture", capture_id=capture_obj.pk)
        return _inbox_area(request)
    return inbox(request)


@require_POST
def capture_file(request, capture_id):
    capture_obj = get_object_or_404(Capture, pk=capture_id)
    phase = get_object_or_404(
        Phase,
        pk=request.POST.get("phase_id"),
    )
    capture_obj = _file_capture(capture_obj, phase)
    return _inbox_area(request)


@require_POST
def capture_skip(request, capture_id):
    capture_obj = get_object_or_404(Capture, pk=capture_id)
    capture_obj.status = Capture.Status.SKIPPED
    capture_obj.save(update_fields=["status"])
    return _inbox_area(request)


def _file_capture(capture_obj, phase):
    settings = AppSettings.load()
    pdir = workspace.phase_dir(settings, phase.project, phase)
    pdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"capture-{stamp}.md"
    (pdir / name).write_text(
        f"# Quick note — {datetime.now():%Y-%m-%d %H:%M}\n\n{capture_obj.text}\n",
        encoding="utf-8",
    )
    capture_obj.status = Capture.Status.FILED
    capture_obj.suggested_phase = phase
    capture_obj.suggested_project = phase.project
    root = settings.expanded_workspace_root()
    capture_obj.filed_path = f"{phase.project.slug}/{phase.folder_name}/{name}"
    capture_obj.save()
    ingest.scan_project(phase.project, settings)
    bus.publish("capture", capture_id=capture_obj.pk)
    return capture_obj


def _inbox_context():
    inbox = list(
        Capture.objects.filter(status=Capture.Status.INBOX)
        .select_related("suggested_project", "suggested_phase")
        .prefetch_related("tags")
    )
    filed = Capture.objects.filter(status=Capture.Status.FILED).select_related(
        "suggested_project", "suggested_phase"
    )[:10]
    phases = list(Phase.objects.select_related("project").order_by("project__name", "order"))
    return {
        "inbox": inbox,
        "filed": filed,
        "all_phases": phases,
        "inbox_count": len(inbox),
    }


def _inbox_area(request):
    return render(request, "hub/_inbox_area.html", _inbox_context())
