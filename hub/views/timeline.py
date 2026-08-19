"""Dependency-aware Gantt timeline (server-rendered SVG) + .ics calendar."""

from datetime import date, timedelta

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateformat import format as dj_format

from ..models import Milestone, Project

ROW_HEIGHT = 30
LABEL_WIDTH = 300
CHART_WIDTH = 640
TOP_PAD = 24
BOTTOM_PAD = 16


def project_timeline(request, slug):
    project = get_object_or_404(Project, slug=slug)
    milestones = list(
        Milestone.objects.filter(project=project)
        .exclude(status="dismissed")
        .prefetch_related("depends_on")
        .order_by("date", "pk")
    )

    rows = []
    index_by_pk = {}
    dated = [m for m in milestones if m.date]
    if dated:
        d_min = min(m.date for m in dated)
        d_max = max(m.date for m in dated)
        span = max((d_max - d_min).days, 1)

        def x_of(date):
            if date is None:
                return None
            frac = (date - d_min).days / span
            return LABEL_WIDTH + frac * (CHART_WIDTH - 24) + 12

        for i, m in enumerate(milestones):
            index_by_pk[m.pk] = i
        for i, m in enumerate(milestones):
            rows.append(
                {
                    "m": m,
                    "y": TOP_PAD + i * ROW_HEIGHT + ROW_HEIGHT // 2,
                    "x": x_of(m.date),
                    "blocked": m.is_blocked,
                    "deps": list(m.depends_on.all()),
                }
            )
        arrows = []
        for row in rows:
            for dep in row["deps"]:
                j = index_by_pk.get(dep.pk)
                if j is None:
                    continue
                dep_row = rows[j]
                arrows.append(
                    {
                        "x1": dep_row["x"] if dep_row["x"] is not None else LABEL_WIDTH + 12,
                        "y1": dep_row["y"],
                        "x2": row["x"] if row["x"] is not None else LABEL_WIDTH + 12,
                        "y2": row["y"],
                    }
                )
        chart_height = TOP_PAD + len(rows) * ROW_HEIGHT + BOTTOM_PAD
        axis = [
            {"x": x_of(d_min), "label": d_min.strftime("%Y-%m-%d")},
            {"x": x_of(d_max), "label": d_max.strftime("%Y-%m-%d")},
        ]
    else:
        d_min = d_max = None
        arrows = []
        axis = []
        chart_height = TOP_PAD + BOTTOM_PAD

    return render(
        request,
        "hub/timeline.html",
        {
            "project": project,
            "rows": rows,
            "arrows": arrows,
            "axis": axis,
            "chart_height": chart_height,
            "chart_width": LABEL_WIDTH + CHART_WIDTH,
            "blocked_count": sum(1 for r in rows if r["blocked"]),
        },
    )


def project_calendar(request, slug):
    project = get_object_or_404(Project, slug=slug)
    milestones = (
        Milestone.objects.filter(project=project, date__isnull=False)
        .exclude(status="dismissed")
        .order_by("date")
    )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Ride Program Hub//EN",
        "CALSCALE:GREGORIAN",
    ]
    stamp = dj_format(timezone.now(), "YmdTHMS")
    for m in milestones:
        summary = f"[{m.mtype}] {m.title}".replace(",", "\\,")
        desc = (m.evidence or "")[:300].replace(",", "\\,").replace("\n", "\\n")
        lines += [
            "BEGIN:VEVENT",
            f"UID:rph-milestone-{m.pk}@rideprogramhub.local",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{m.date.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(m.date + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{desc}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    resp = HttpResponse("\r\n".join(lines), content_type="text/calendar")
    resp["Content-Disposition"] = f'attachment; filename="{slug}-milestones.ics"'
    return resp
