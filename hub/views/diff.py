"""Side-by-side revision diff for a document series (GitHub-style)."""

import difflib

from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from ..models import DocumentSeries
from ..revisions import series_stack

CONTEXT_RADIUS = 2


@require_GET
def series_diff(request, series_id):
    series = get_object_or_404(DocumentSeries, pk=series_id)
    stack = series_stack(series)
    if len(stack) < 2:
        return render(
            request,
            "hub/diff.html",
            {"series": series, "stack": stack, "too_few": True, "rows": []},
        )
    a_pk = request.GET.get("a")
    b_pk = request.GET.get("b")
    b = next((d for d in stack if str(d.pk) == b_pk), stack[-1])
    a = next(
        (d for d in stack if str(d.pk) == a_pk and d.pk != b.pk),
        _default_old(stack, b),
    )
    rows = _diff_rows(a.extracted_text or "", b.extracted_text or "")
    return render(
        request,
        "hub/diff.html",
        {
            "series": series,
            "stack": stack,
            "doc_a": a,
            "doc_b": b,
            "rows": rows,
            "too_few": False,
        },
    )


def _default_old(stack, b):
    candidates = [d for d in stack if d.pk != b.pk]
    return candidates[-1] if candidates else b


def _diff_rows(text_a, text_b):
    """Aligned rows for a side-by-side table with change highlighting."""
    lines_a = text_a.splitlines() or [""]
    lines_b = text_b.splitlines() or [""]
    matcher = difflib.SequenceMatcher(None, lines_a, lines_b, autojunk=False)
    raw = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                raw.append(("equal", lines_a[i1 + k], lines_b[j1 + k]))
        elif tag == "delete":
            for k in range(i1, i2):
                raw.append(("removed", lines_a[k], ""))
        elif tag == "insert":
            for k in range(j1, j2):
                raw.append(("added", "", lines_b[k]))
        else:  # replace — pair up lines, pad the shorter side
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                left = lines_a[i1 + k] if i1 + k < i2 else ""
                right = lines_b[j1 + k] if j1 + k < j2 else ""
                raw.append(("changed", left, right))
    # collapse long equal runs to context windows
    keep = [False] * len(raw)
    for idx, row in enumerate(raw):
        if row[0] != "equal":
            for j in range(max(0, idx - CONTEXT_RADIUS), min(len(raw), idx + CONTEXT_RADIUS + 1)):
                keep[j] = True
    rows = []
    skip_run = 0
    for idx, row in enumerate(raw):
        if keep[idx]:
            rows.append(row)
            skip_run = 0
        else:
            skip_run += 1
            if skip_run == 1:
                rows.append(("skip", f"⋯ {skip_run} identical line", ""))
            elif skip_run > 1 and rows:
                rows[-1] = ("skip", f"⋯ {skip_run} identical lines", "")
    return rows
