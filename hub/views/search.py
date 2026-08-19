"""Full-text search across every extracted document."""

import re

from django.shortcuts import render
from django.utils.html import escape, mark_safe
from django.views.decorators.http import require_GET

from ..models import Document

RESULT_LIMIT = 50
SNIPPET_RADIUS = 110


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
    return render(
        request,
        "hub/search.html",
        {
            "q": q,
            "performed": len(q) >= 2,
            "results": results,
            "total_shown": len(results),
        },
    )


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
