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
    ext = target.suffix.lower()
    if ext == ".docx":
        return _preview_docx(request, target)
    if ext in (".xlsx", ".xlsm"):
        return _preview_xlsx(request, target)
    if ext in INLINE_EXTENSIONS:
        return _serve_inline(target)
    return render(
        request,
        "hub/preview.html",
        {
            "filename": target.name,
            "path": request.GET.get("path", ""),
            "unsupported": True,
        },
    )


def _serve_inline(target):
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(open(target, "rb"), content_type=content_type)


def _preview_docx(request, target):
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
            "path": request.GET.get("path", ""),
            "kind": "document",
            "body_html": body_html,
            "error": error,
        },
    )


def _preview_xlsx(request, target):
    import openpyxl

    sheets = []
    error = ""
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
        wb.close()
    except Exception as exc:
        error = f"{exc.__class__.__name__}: {exc}"
    return render(
        request,
        "hub/preview.html",
        {
            "filename": target.name,
            "path": request.GET.get("path", ""),
            "kind": "sheet",
            "sheets": sheets,
            "error": error,
        },
    )
