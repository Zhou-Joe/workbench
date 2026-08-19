# Ride Program Hub

A personal, local-only work platform for coordinating the design life of
multiple amusement ride projects. Drop files into phase-structured project
folders; the platform extracts milestones with a local LLM and keeps a
per-project timeline and portfolio overview current — no manual status
maintenance, no data leaving your machine.

Design spec: `docs/superpowers/specs/2026-08-19-ride-program-hub-design.md`

## Quick start

```bash
# 1. Environment (Python 3.14 via uv, packages via the Aliyun mirror)
brew install uv                       # or: pip install --user -i https://mirrors.aliyun.com/pypi/simple/ uv
uv venv --python 3.14 .venv
UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/ uv pip install \
    --python .venv/bin/python -r requirements.txt

# 2. Database + admin account
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser

# 3. Run
.venv/bin/python manage.py runserver
# open http://127.0.0.1:8000/  (admin at /admin/)
```

## First-run setup (in the app)

1. **Settings → Workspace root** — point it at your projects folder
   (e.g. `~/RideProjects`). The app only reads your files and moves them
   solely for revision archival (logged, undoable; can be disabled).
2. **Settings → LLM** — start LM Studio, load a model, start its local
   server (Developer tab), then set the base URL (`http://localhost:1234/v1`)
   and the model name here.
3. **Create a project** on the Portfolio page — it scaffolds the six
   design-phase folders (Blue Sky → Testing & Commissioning). Phases are
   fully editable: rename, insert between, reorder.
4. **Drop files** into a phase folder. The watcher ingests them, the
   pipeline extracts milestones (you'll see live status in the header),
   and they appear in the ledger for you to confirm, edit, or dismiss.

## Extraction tiers

| Files | Engine | Notes |
|---|---|---|
| PDF (text or scanned), images | **MinerU** 3.x | `uv pip install mineru` + run `mineru-models-download` once; without it, text PDFs fall back to fast text-layer extraction and scans stay unextracted |
| DOCX / PPTX / XLSX | python-docx / python-pptx / openpyxl | lossless and instant |
| EML / MSG email | stdlib / extract-msg | |
| CAD (.dwg, .rvt, .step, …) | metadata only | filename/date context, flagged low-confidence |

## Architecture notes

- Django 6.1 + SQLite, single-user localhost app. Background worker thread
  processes parse → LLM → digest jobs; also available as
  `manage.py process_queue [--watch]`.
- Realtime UX: htmx fragment swaps (no page reloads) + a Server-Sent Events
  stream at `/events/` driving live region refreshes and the activity strip.
- LLM access is a thin client over LM Studio's OpenAI-compatible API —
  swapping models or pointing at a different endpoint is a settings change.
- Revision management: files are confirmed against a document series;
  superseded revisions move to the phase's `_archive/` folder (or
  database-only mode), every move logged and one-click undoable.

## Tests

```bash
RIDEHUB_DISABLE_WORKER=1 .venv/bin/python manage.py test hub
```

Extractor unit tests run against generated fixture files; the LLM is mocked;
revision/supersede/archive flows and the full pipeline are covered
end-to-end.

## Development environment

- Python 3.14.3 (uv-managed), Django 6.1, all dependencies latest at
  build time (see `requirements.txt`), installed via the Aliyun PyPI mirror.
- htmx 2.0.10 is vendored at `hub/static/hub/js/htmx.min.js`.
