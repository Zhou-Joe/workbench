"""Dependency-aware Gantt timeline (server-rendered SVG) + .ics calendar.

Tasks (user work items) render as bars, milestones (extracted events) as
dots with dependency arrows; both share one date scale. A dashed line marks
today when it falls inside the range."""

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
    tasks = list(project.tasks.order_by("start_date", "pk"))

    dated = [m.date for m in milestones if m.date]
    dated += [t.start_date for t in tasks if t.start_date]
    dated += [t.end_date for t in tasks if t.end_date]
    today = date.today()

    task_rows = []
    milestone_rows = []
    arrows = []
    axis = []
    today_x = None
    y = TOP_PAD

    if dated:
        d_min, d_max = min(dated), max(dated)
        span = max((d_max - d_min).days, 1)

        def x_of(d):
            if d is None:
                return None
            return LABEL_WIDTH + ((d - d_min).days / span) * (CHART_WIDTH - 24) + 12

        for t in tasks:
            x1, x2 = x_of(t.start_date), x_of(t.end_date)
            if x1 is None and x2 is None:
                continue  # undated tasks stay on the board only
            if x1 is None:
                x1 = x2
            if x2 is None:
                x2 = x1
            bar_x1, bar_x2 = x1, max(x2, x1 + 6)
            task_rows.append(
                {
                    "t": t,
                    "y": y + ROW_HEIGHT // 2,
                    "x1": bar_x1,
                    "x2": bar_x2,
                    "w": bar_x2 - bar_x1,
                }
            )
            y += ROW_HEIGHT

        separator_y = y + 4 if task_rows else None
        y = y + (12 if task_rows else 0)

        index_by_pk = {}
        for m in milestones:
            index_by_pk[m.pk] = len(milestone_rows)
            milestone_rows.append(
                {
                    "m": m,
                    "y": y + ROW_HEIGHT // 2,
                    "x": x_of(m.date),
                    "blocked": m.is_blocked,
                    "deps": list(m.depends_on.all()),
                }
            )
            y += ROW_HEIGHT

        for row in milestone_rows:
            for dep in row["deps"]:
                j = index_by_pk.get(dep.pk)
                if j is None:
                    continue
                dep_row = milestone_rows[j]
                arrows.append(
                    {
                        "x1": dep_row["x"] if dep_row["x"] is not None else LABEL_WIDTH + 12,
                        "y1": dep_row["y"],
                        "x2": row["x"] if row["x"] is not None else LABEL_WIDTH + 12,
                        "y2": row["y"],
                    }
                )
        if d_min <= today <= d_max:
            today_x = x_of(today)
        axis = [
            {"x": x_of(d_min), "label": d_min.strftime("%Y-%m-%d")},
            {"x": x_of(d_max), "label": d_max.strftime("%Y-%m-%d")},
        ]

    chart_height = max(y + BOTTOM_PAD, TOP_PAD + BOTTOM_PAD)
    return render(
        request,
        "hub/timeline.html",
        {
            "project": project,
            "task_rows": task_rows,
            "rows": milestone_rows,
            "arrows": arrows,
            "axis": axis,
            "today_x": today_x,
            "chart_height": chart_height,
            "chart_width": LABEL_WIDTH + CHART_WIDTH,
            "blocked_count": sum(1 for r in milestone_rows if r["blocked"]),
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
