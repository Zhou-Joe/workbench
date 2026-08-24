"""One-click project export: every file plus a machine-readable data dump."""

import json
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from .. import workspace
from ..models import AppSettings, Milestone, Project


@require_GET
def project_export(request, slug):
    project = get_object_or_404(Project, slug=slug)
    settings = AppSettings.load()
    root = workspace.project_root(settings, project)

    data = _data_dump(project)
    stamp = date.today().strftime("%Y%m%d")

    buf = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("ridehub-data.json", json.dumps(data, indent=1, default=_jsonify))
        if root.is_dir():
            for child in sorted(root.rglob("*")):
                if child.is_symlink():
                    continue  # never follow links out of the workspace
                rel = child.relative_to(root)
                if any(part.startswith(".") for part in rel.parts):
                    continue
                if child.is_file():
                    zf.write(child, f"{project.slug}/{rel.as_posix()}")
    buf.seek(0)
    resp = FileResponse(
        buf,
        as_attachment=True,
        filename=f"{project.slug}-export-{stamp}.zip",
        content_type="application/zip",
    )
    return resp


def _jsonify(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _data_dump(project):
    phases = []
    for ph in project.phases.all():
        phases.append(
            {
                "order": ph.order,
                "name": ph.name,
                "extraction_focus": ph.extraction_focus,
                "closed_at": ph.closed_at,
                "digest": ph.digest.content if hasattr(ph, "digest") else "",
                "documents": [
                    {
                        "file": d.file_path,
                        "revision": d.revision_number,
                        "is_latest": d.is_latest,
                        "series": d.series.title if d.series else None,
                        "kind": d.doc_kind,
                        "status": d.extraction_status,
                        "tags": sorted(t.name for t in d.tags.all()),
                        "delta_summary": d.delta_summary,
                    }
                    for d in ph.documents.select_related("series").prefetch_related("tags")
                ],
            }
        )
    milestones = [
        {
            "date": m.date,
            "title": m.title,
            "type": m.mtype,
            "status": m.status,
            "evidence": m.evidence,
            "notes": m.notes,
            "phase": m.phase.order,
            "source": m.document.file_path if m.document else None,
            "depends_on": [d.pk for d in m.depends_on.all()],
        }
        for m in Milestone.objects.filter(project=project)
        .select_related("phase", "document")
        .prefetch_related("depends_on")
    ]
    tasks = [
        {
            "title": t.title,
            "status": t.status,
            "start": t.start_date,
            "end": t.end_date,
            "notes": t.notes,
            "completed_at": t.completed_at,
        }
        for t in project.tasks.all()
    ]
    return {
        "exported_at": datetime.now(),
        "app": "Ride Program Hub",
        "project": {
            "name": project.name,
            "slug": project.slug,
            "code": project.code,
            "description": project.description,
            "protocol": project.protocol.name if project.protocol else None,
        },
        "phases": phases,
        "milestones": milestones,
        "tasks": tasks,
    }
