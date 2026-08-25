"""JSON payload for the ⌘K command palette."""

from django.http import JsonResponse
from django.urls import reverse

from ..models import Meeting, Phase, Project


def palette(request):
    items = [
        {"label": "Portfolio (Now / Next)", "url": reverse("hub:home")},
        {"label": "Capture Inbox", "url": reverse("hub:inbox")},
        {"label": "New live meeting", "url": reverse("hub:meeting_live")},
        {"label": "Meetings archive", "url": reverse("hub:meetings")},
        {"label": "Meeting speakers", "url": reverse("hub:speakers")},
        {"label": "Meeting series", "url": reverse("hub:series_list")},
        {"label": "Ask the agent", "url": reverse("hub:ask")},
        {"label": "Pipeline jobs", "url": reverse("hub:jobs")},
        {"label": "Search documents", "url": reverse("hub:search")},
        {"label": "Settings", "url": reverse("hub:settings")},
        {"label": "Protocols (phase templates)", "url": reverse("hub:protocols")},
    ]
    for m in Meeting.objects.order_by("-started_at")[:12]:
        items.append({"label": f"meeting: {m.title}", "url": reverse("hub:meeting_detail", args=[m.pk])})
    for p in Project.objects.prefetch_related("phases").order_by("name"):
        items.append({"label": p.name, "url": reverse("hub:project", args=[p.slug])})
        items.append(
            {"label": f"{p.name} — timeline", "url": reverse("hub:project_timeline", args=[p.slug])}
        )
        items.append(
            {"label": f"{p.name} — decisions", "url": reverse("hub:project_decisions", args=[p.slug])}
        )
        for ph in p.phases.all():
            items.append(
                {
                    "label": f"{p.name} / {ph.order:02d} {ph.name}",
                    "url": reverse("hub:phase", args=[p.slug, ph.order]),
                }
            )
    return JsonResponse({"items": items[:400]})
