"""Full-text search across every extracted document + saved searches."""

import re

from django.shortcuts import render
from django.utils.html import escape, mark_safe
from django.views.decorators.http import require_GET, require_POST

from ..events import bus
from ..models import Document, SavedSearch

RESULT_LIMIT = 50
SNIPPET_RADIUS = 110


def match_count(query):
    return (
        Document.objects.filter(extracted_text__icontains=query)
        | Document.objects.filter(filename__icontains=query)
    ).count()


@require_GET
def search(request):
    q = request.GET.get("q", "").strip()
    results = []
    if len(q) >= 2:
        docs = (
            Document.objects.filter(extracted_text__icontains=q)
            | Document.objects.filter(filename__icontains=q)
        ).select_related("phase", "phase__project").order_by("-ingested_at")
        for doc in docs[:RESULT_LIMIT]:
            results.append(
                {
                    "doc": doc,
                    "snippet": _snippet(doc.extracted_text, q),
                }
            )
    # visiting via a saved-search link marks its matches as seen
    seen_id = request.GET.get("seen", "")
    if seen_id:
        saved = SavedSearch.objects.filter(pk=seen_id).first()
        if saved:
            saved.last_count = match_count(saved.query)
            saved.save(update_fields=["last_count"])
    return render(
        request,
        "hub/search.html",
        {
            "q": q,
            "performed": len(q) >= 2,
            "results": results,
            "total_shown": len(results),
            "saved_searches": SavedSearch.objects.all(),
        },
    )


@require_POST
def search_save(request):
    q = request.POST.get("q", "").strip()
    if len(q) >= 2:
        name = request.POST.get("name", "").strip() or q[:60]
        SavedSearch.objects.create(
            name=name[:200], query=q[:300], last_count=match_count(q)
        )
        bus.publish("search")
    return search(request)


@require_POST
def search_delete(request, saved_id):
    SavedSearch.objects.filter(pk=saved_id).delete()
    return search(request)


def _snippet(text, q, radius=SNIPPET_RADIUS):
    if not text:
        return ""
    idx = text.lower().find(q.lower())
    if idx < 0:
        window = text[: radius * 2]
    else:
        start = max(0, idx - radius)
        end = min(len(text), idx + len(q) + radius)
        window = text[start:end]
        if start > 0:
            window = "…" + window
        if end < len(text):
            window = window + "…"
    escaped = escape(window)
    q_escaped = re.escape(escape(q))
    highlighted = re.sub(
        q_escaped, lambda m: f"<mark>{m.group(0)}</mark>", escaped, flags=re.IGNORECASE
    )
    return mark_safe(highlighted)
