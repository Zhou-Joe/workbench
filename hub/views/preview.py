"""Single-click in-browser preview.

PDF / images / text: served inline — the browser renders them natively.
DOCX: converted to HTML with mammoth. XLSX: rendered as tables with
openpyxl. Everything else falls back to a notice with a download link.
"""

import mimetypes
from pathlib import Path

from django.http import FileResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_GET

from ..models import AppSettings
from .download import _safe_file

INLINE_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
    ".svg",
    ".txt",
    ".md",
    ".csv",
    ".log",
}

XLSX_ROW_LIMIT = 200
XLSX_COL_LIMIT = 40


@require_GET
def preview(request):
    try:
        settings = AppSettings.load()
        target = _safe_file(settings, request.GET.get("path", ""))
    except RuntimeError as exc:
        return HttpResponseBadRequest(str(exc))
    if target is None:
        return HttpResponseBadRequest("file not found")
    rel = request.GET.get("path", "")
    ext = target.suffix.lower()
    if ext == ".docx":
        return _preview_docx(request, target, rel)
    if ext in (".xlsx", ".xlsm"):
        return _preview_xlsx(request, target, rel)
    if ext in INLINE_EXTENSIONS:
        return _serve_inline(target)
    return render(
        request,
        "hub/preview.html",
        {
            "filename": target.name,
            "path": rel,
            "unsupported": True,
            "similar": _similar_docs(rel),
        },
    )


def _similar_docs(rel, radius=1500):
    """Top similar indexed documents in the same project, scored by filename
    stem + extracted-text-prefix similarity (Docspell-style suggestions)."""
    from ..models import Document
    from ..revisions import normalize_stem, similarity

    doc = Document.objects.filter(file_path=rel).select_related(
        "phase", "phase__project"
    ).first()
    if doc is None:
        return []
    base_stem = normalize_stem(doc.filename)
    base_text = (doc.extracted_text or "")[:radius].lower()
    scored = []
    others = (
        Document.objects.filter(
            phase__project=doc.phase.project, extension=doc.extension
        )
        .exclude(pk=doc.pk)
        .select_related("phase", "phase__project")
        .defer("digest_contribution", "delta_summary")[:60]
    )
    for other in others:
        score = similarity(base_stem, normalize_stem(other.filename)) * 2
        other_text = (other.extracted_text or "")[:radius].lower()
        if base_text and other_text:
            score += similarity(base_text, other_text)
        if score >= 0.5:
            scored.append((score, other))
    scored.sort(key=lambda pair: (-pair[0], pair[1].filename))
    return [d for _, d in scored[:4]]


def _serve_inline(target):
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    resp = FileResponse(open(target, "rb"), content_type=content_type)
    if target.suffix.lower() == ".svg":
        # SVG can carry scripts; sandbox it so it stays a picture, not code
        resp["Content-Security-Policy"] = "sandbox"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


def _preview_docx(request, target, rel):
    import mammoth

    try:
        with open(target, "rb") as f:
            result = mammoth.convert_to_html(f)
        body_html = result.value
        error = ""
    except Exception as exc:  # corrupt file, mammoth limits, etc.
        body_html = ""
        error = f"{exc.__class__.__name__}: {exc}"
    return render(
        request,
        "hub/preview.html",
        {
            "filename": target.name,
            "path": rel,
            "kind": "document",
            "body_html": body_html,
            "error": error,
            "similar": _similar_docs(rel),
        },
    )


def _preview_xlsx(request, target, rel):
    import openpyxl

    sheets = []
    error = ""
    wb = None
    try:
        wb = openpyxl.load_workbook(target, read_only=True, data_only=True)
        for ws in wb.worksheets:
            rows = []
            truncated = False
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= XLSX_ROW_LIMIT:
                    truncated = True
                    break
                rows.append(
                    ["" if c is None else str(c) for c in row[:XLSX_COL_LIMIT]]
                )
            sheets.append({"name": ws.title, "rows": rows, "truncated": truncated})
    except Exception as exc:
        error = f"{exc.__class__.__name__}: {exc}"
    finally:
        if wb is not None:
            wb.close()
    return render(
        request,
        "hub/preview.html",
        {
            "filename": target.name,
            "path": rel,
            "kind": "sheet",
            "sheets": sheets,
            "error": error,
            "similar": _similar_docs(rel),
        },
    )
