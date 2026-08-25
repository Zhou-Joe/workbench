"""Recurring meeting series: list, detail, cross-meeting progress summaries."""

from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from ..events import bus
from ..models import AppSettings, MeetingSeries


def series_list(request):
    return render(request, "hub/series_list.html", {
        "all_series": list(
            MeetingSeries.objects.prefetch_related("meetings")
        ),
    })


def series_detail(request, series_id):
    series = get_object_or_404(MeetingSeries, pk=series_id)
    return render(request, "hub/series_detail.html", _series_context(series))


def _series_context(series):
    return {
        "series": series,
        "meetings": list(series.meetings.order_by("-started_at")[:20]),
    }


@require_POST
def series_create(request):
    title = request.POST.get("title", "").strip()
    if title:
        MeetingSeries.objects.create(
            title=title[:200],
            description=request.POST.get("description", "").strip(),
            frequency=request.POST.get("frequency", MeetingSeries.Frequency.WEEKLY),
        )
    return render(request, "hub/series_list.html", {
        "all_series": list(MeetingSeries.objects.prefetch_related("meetings")),
    })


@require_POST
def series_edit(request, series_id):
    series = get_object_or_404(MeetingSeries, pk=series_id)
    title = request.POST.get("title", "").strip()
    if title:
        series.title = title
    series.description = request.POST.get("description", "").strip()
    series.frequency = request.POST.get("frequency", series.frequency)
    series.save()
    return render(request, "hub/series_detail.html", _series_context(series))


@require_POST
def series_delete(request, series_id):
    MeetingSeries.objects.filter(pk=series_id).delete()
    resp = render(
        request,
        "hub/series_list.html",
        {"all_series": list(MeetingSeries.objects.prefetch_related("meetings"))},
    )
    resp["HX-Redirect"] = "/meetings/series/"
    return resp


def _meetings_data(series):
    from django.utils import timezone

    out = []
    for m in series.meetings.order_by("started_at"):
        if m.summary.strip():
            content = m.summary
        else:
            content = "\n".join(u.text for u in m.utterances.order_by("seq") if u.text.strip())
        if not content.strip():
            continue
        out.append(
            {
                "title": m.title,
                "date": timezone.localtime(m.started_at).strftime("%Y-%m-%d"),
                "summary_or_transcript": content,
            }
        )
    return out


def series_summarize_stream(request, series_id):
    """SSE stream of the cross-meeting progress overview."""
    series = get_object_or_404(MeetingSeries, pk=series_id)

    def event_stream():
        from hub.meetings.summarize import summarize_series_stream

        collected: list[str] = []
        try:
            for delta in summarize_series_stream(AppSettings.load(), _meetings_data(series)):
                collected.append(delta)
                yield f"data: {delta}\n\n".encode()
        finally:
            if collected:
                MeetingSeries.objects.filter(pk=series.pk).update(
                    summary="".join(collected)
                )
                bus.publish("meetings")
        yield b"data: [DONE]\n\n"

    resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp
