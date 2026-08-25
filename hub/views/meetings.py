"""Meeting pages and actions: archive, live host, detail, and the
minutes → phase-folder bridge. CPU/LLM actions (diarize, reprocess,
summarize, enroll) run synchronously — localhost single-user, and htmx
shows a busy indicator while the request is in flight.
"""

from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .. import ingest, workspace
from ..events import bus
from ..meetings.audio import resolve_audio_path
from ..meetings.minutes import build_minutes_markdown, minutes_filename
from ..models import (
    AppSettings,
    Meeting,
    MeetingSeries,
    Phase,
    Speaker,
    Utterance,
)


def meetings(request):
    return render(request, "hub/meetings.html", _meetings_context())


def _meetings_context():
    meetings = list(Meeting.objects.select_related("series", "filed_document__phase__project"))
    by_series: dict[str, list] = {}
    standalone: list[Meeting] = []
    for m in meetings:
        if m.series_id:
            by_series.setdefault(m.series.title, []).append(m)
        else:
            standalone.append(m)
    return {
        "standalone": standalone,
        "series_groups": sorted(by_series.items()),
        "total": len(meetings),
    }


def meeting_live(request):
    return render(request, "hub/meeting_live.html", {
        "all_series": MeetingSeries.objects.all(),
    })


def meeting_detail(request, meeting_id):
    meeting = get_object_or_404(
        Meeting.objects.select_related("series", "filed_document__phase__project"),
        pk=meeting_id,
    )
    return render(request, "hub/meeting_detail.html", _detail_context(meeting))


def _detail_context(meeting):
    utterances = list(meeting.utterances.order_by("seq"))
    return {
        "meeting": meeting,
        "utterances": utterances,
        "speakers": list(Speaker.objects.all()),
        "speaker_labels": sorted({u.speaker_label for u in utterances}),
        "all_series": list(MeetingSeries.objects.all()),
        "all_phases": list(
            Phase.objects.select_related("project").order_by("project__name", "order")
        ),
    }


def meeting_audio(request, meeting_id):
    meeting = get_object_or_404(Meeting, pk=meeting_id)
    if not meeting.audio_path:
        return HttpResponse(status=404)
    path = resolve_audio_path(meeting.audio_path)
    if not path.exists():
        return HttpResponse(status=404)
    return FileResponse(open(path, "rb"), content_type="audio/wav", filename=path.name)


@require_POST
def meeting_edit(request, meeting_id):
    meeting = get_object_or_404(Meeting, pk=meeting_id)
    title = request.POST.get("title", "").strip()
    if title:
        meeting.title = title
    series_id = request.POST.get("series_id", "")
    meeting.series = (
        MeetingSeries.objects.filter(pk=series_id).first() if series_id else None
    )
    meeting.save()
    bus.publish("meetings")
    return render(request, "hub/meeting_detail.html", _detail_context(meeting))


@require_POST
def meeting_delete(request, meeting_id):
    meeting = get_object_or_404(Meeting, pk=meeting_id)
    if meeting.audio_path:
        path = resolve_audio_path(meeting.audio_path)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    meeting.delete()
    bus.publish("meetings")
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = "/meetings/"
    return resp


@require_POST
def utterance_edit(request, utterance_id):
    utt = get_object_or_404(Utterance.objects.select_related("meeting"), pk=utterance_id)
    utt.text = request.POST.get("text", utt.text)
    utt.translation = request.POST.get("translation", "")
    speaker = request.POST.get("speaker_label", "").strip()
    if speaker:
        utt.speaker_label = speaker
    utt.save()
    return render(request, "hub/_utterance_row.html", {"utt": utt})


@require_POST
def meeting_rename_speaker(request, meeting_id):
    meeting = get_object_or_404(Meeting, pk=meeting_id)
    old_label = request.POST.get("old_label", "").strip()
    new_label = request.POST.get("new_label", "").strip()
    if old_label and new_label:
        Utterance.objects.filter(
            meeting=meeting, speaker_label=old_label
        ).update(speaker_label=new_label)
    return render(request, "hub/_meeting_transcript.html", _detail_context(meeting))


@require_POST
def meeting_diarize(request, meeting_id):
    meeting = get_object_or_404(Meeting, pk=meeting_id)
    error = ""
    if not meeting.audio_path:
        error = "No audio saved for this meeting."
    else:
        try:
            from hub.meetings.diarizer import diarize_meeting

            diarize_meeting(meeting.id, str(resolve_audio_path(meeting.audio_path)))
        except Exception as e:
            error = str(e)
    ctx = _detail_context(meeting)
    ctx["action_error"] = error
    return render(request, "hub/meeting_detail.html", ctx)


@require_POST
def meeting_reprocess(request, meeting_id):
    meeting = get_object_or_404(Meeting, pk=meeting_id)
    error = ""
    try:
        from hub.meetings.reprocess import reprocess_meeting

        reprocess_meeting(meeting.id, do_diarize=True)
    except Exception as e:
        error = str(e)
    ctx = _detail_context(meeting)
    ctx["action_error"] = error
    return render(request, "hub/meeting_detail.html", ctx)


def meeting_summarize_stream(request, meeting_id):
    """SSE stream of summary deltas; final text persisted on completion."""
    meeting = get_object_or_404(Meeting, pk=meeting_id)

    def transcript():
        return "\n".join(
            u.text for u in meeting.utterances.order_by("seq") if u.text.strip()
        )

    def event_stream():
        from hub.meetings.summarize import summarize_stream

        collected: list[str] = []
        try:
            for delta in summarize_stream(AppSettings.load(), transcript()):
                collected.append(delta)
                yield f"data: {delta}\n\n".encode()
        finally:
            if collected:
                Meeting.objects.filter(pk=meeting.pk).update(
                    summary="".join(collected)
                )
                bus.publish("meetings")
        yield b"data: [DONE]\n\n"

    resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


@require_POST
def meeting_enroll(request, meeting_id):
    """Register a diarized speaker's voice from this meeting's own audio."""
    meeting = get_object_or_404(Meeting, pk=meeting_id)
    error = ""
    try:
        from hub.meetings.enroll import enroll_from_meeting

        enroll_from_meeting(
            meeting.id,
            request.POST.get("speaker_label", ""),
            speaker_name=request.POST.get("speaker_name", "") or None,
        )
    except Exception as e:
        error = str(e)
    ctx = _detail_context(meeting)
    ctx["action_error"] = error
    return render(request, "hub/meeting_detail.html", ctx)


@require_POST
def meeting_send_to_phase(request, meeting_id):
    """Write minutes markdown into a phase folder; the extraction pipeline
    takes over exactly like a capture-inbox filing."""
    meeting = get_object_or_404(Meeting, pk=meeting_id)
    phase = get_object_or_404(Phase, pk=request.POST.get("phase_id"))
    settings = AppSettings.load()

    name = minutes_filename(meeting)
    pdir = workspace.phase_dir(settings, phase.project, phase)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / name).write_text(
        build_minutes_markdown(meeting, meeting.utterances.order_by("seq")),
        encoding="utf-8",
    )
    ingest.scan_project(phase.project, settings)
    # scan_project created the Document; link it back to the meeting.
    from ..models import Document

    doc = Document.objects.filter(phase=phase, filename=name).order_by("-pk").first()
    if doc is not None:
        meeting.filed_document = doc
        meeting.save(update_fields=["filed_document"])
    bus.publish("meetings")
    ctx = _detail_context(meeting)
    return render(request, "hub/meeting_detail.html", ctx)
