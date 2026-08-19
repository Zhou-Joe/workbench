# Ride Program Hub — Design Spec

**Date:** 2026-08-19
**Status:** Approved design, pending implementation planning
**Owner:** Ride development engineer (single user, local deployment)

## 1. Purpose

A personal, local-only work platform for coordinating the full design life of
multiple amusement ride projects. The user drops partner/team files into
phase-structured project folders; the platform extracts and summarizes
milestones with an LLM and presents a per-project timeline and a portfolio
overview, answering "what's done now and what's next" without manual status
maintenance.

Core value: the milestone timeline **derives itself from the documents**.
Data entry is nothing more than saving files into folders.

## 2. Context and constraints

- **Single user, local-only.** Runs on the user's Mac; no multi-user auth, no
  cloud services. Ride design documents are confidential IP and never leave
  the machine.
- **Hardware reality:** the development machine has 8 GB RAM. LLM model
  choice (4B-class default) is the user's decision inside LM Studio, not the
  app's.
- **Scale:** 2–5 active projects, a handful of documents per project per
  week. SQLite and in-process background processing are sufficient; a task
  queue (Celery etc.) is explicitly out of scope.
- **Stack:** Django (user is familiar with it) + SQLite + server-rendered
  templates. Django admin is part of the product (review/correction UI).

## 3. Workspace

The user picks a workspace root folder (e.g. `~/RideProjects`). On-disk
layout:

```
<workspace_root>/
  <project-slug>/                  # e.g. tron-lightcycle-expansion/
    <NN>-<phase-slug>/             # e.g. 04-detail-design-review/
      <current files>
      _archive/                    # superseded revisions moved here
```

### 3.1 Phases

Phases are a **per-project ordered list**, not a constant. New projects are
seeded from a six-phase template:

1. `01-Blue-Sky`
2. `02-Concept-Design`
3. `03-Feasibility-Analysis`
4. `04-Detail-Design-and-Review`
5. `05-Installation`
6. `06-Testing-and-Commissioning`

The user can rename any phase, add a new phase at any position (between two
phases or at the end), and reorder phases. The sort order drives both folder
naming (`NN-` prefixes, renumbered on reorder) and timeline display.
Renaming a phase renames its folder; file contents are never touched.

Each phase carries an optional, user-editable **extraction focus** text that
is injected into the LLM prompt (what to look for in this phase's
documents). The template seeds defaults, e.g.:

- Blue Sky: creative directions explored, show concepts, approvals to advance
- Concept Design: concept lock decisions, ride system selections, capacity targets
- Feasibility: site constraints, budget/schedule findings, go/no-go recommendations
- Detail Design & Review: review submissions, comment resolutions, approvals/rejections, IFC dates
- Installation: deliveries, site milestones, installation completion
- Testing & Commissioning: test campaigns, punch lists, certification and sign-offs, readiness reviews

### 3.2 File ingestion

- A folder watcher (watchdog, FSEvents on macOS, debounced) detects new or
  changed files in project folders.
- A **Rescan** button on every project screen catches anything the watcher
  missed (laptop sleep, files copied while the app was off).
- A startup scan reconciles the database with disk state.
- In-place file replacement (same path, new content) is detected via
  checksum change and treated as a new revision candidate (§6).

### 3.3 File safety guarantees

The app **never modifies or deletes file contents**. It may **move** files
only for archival of superseded revisions (§6), only after user
confirmation, always logged and undoable. A settings toggle (`archive_mode`)
can restrict archival to database-only, leaving all files physically in
place. If the app is deleted, the folders remain fully usable plain folders.

## 4. Data model

All models live in one Django app. SQLite backend.

- **Project** — name, slug, code, description, timestamps.
- **Phase** — FK Project, name, slug, `order` (unique per project),
  `extraction_focus` (text, optional), timestamps.
- **DocumentSeries** — FK Phase, title, timestamps. The logical deliverable
  (e.g. "Ride Control System IFC Package"). Series are phase-scoped in v1.
- **Document** — FK Phase, nullable FK DocumentSeries, `revision_number`
  (within series), `file_path` (relative to workspace root), filename,
  extension, size, mtime, checksum, `doc_kind` (pdf / office / email /
  cad / image / other), `extraction_tier` (mineru / native / email /
  metadata), `extraction_status` (pending / processing / done / failed),
  `is_latest` (bool; exactly one per series), `extracted_text` (nullable
  text), extraction/model timestamps.
- **Milestone** — FK Project, FK Phase, FK Document (source), date, title,
  `mtype` (gate / decision / deliverable / issue / risk / action), `status`
  (extracted / confirmed / edited / dismissed), confidence, evidence quote,
  notes, timestamps.
- **PhaseDigest** — one per Phase: markdown content, model used, updated_at.
  Regenerated as documents accumulate.
- **ExtractionJob** — FK Document, kind (parse / llm), status, attempts,
  error text, started/finished timestamps. Every failure is visible and
  retryable; nothing fails silently.
- **ArchiveMove** — undo log: FK Document, from_path, to_path, moved_at,
  `undone` flag.
- **AppSettings** — singleton row: workspace root, LM Studio base URL
  (default `http://localhost:1234/v1`), model name, generation parameters
  (temperature, max tokens), MinerU executable path and options,
  `archive_mode` (move / db_only), watch enabled.

## 5. Extraction pipeline

New/changed file → Document row → background job. Three extraction tiers:

| Tier | Inputs | Engine |
|---|---|---|
| mineru | PDFs (text or scanned), images, DOCX/PPTX/XLSX | MinerU 3.x (`pip install mineru`), invoked via CLI, Markdown output |
| native / email | same Office formats when MinerU unavailable or failed; `.eml`; `.msg` via extract-msg | python-docx / python-pptx / openpyxl / stdlib email / extract-msg |
| metadata | native CAD (.dwg, .rvt, .step, …) and anything else unreadable | filename, date, size only; flagged low-confidence |

Fallback rule: if MinerU is not installed or errors on a file, the pipeline
falls back to the native tier and flags the Document so the lower extraction
quality is visible. A missing tool never blocks ingestion.

### 5.1 LLM layer

- **Provider: LM Studio** local server (OpenAI-compatible API). The app
  never assumes a specific model; base URL and model name come from
  AppSettings. A connection-status indicator warns when the server is down.
- The client is a thin interface (`summarize(prompt) -> dict`) so a future
  provider swap (bigger local machine, company-approved endpoint) is a
  settings change.
- **Extraction prompt:** phase-aware. The phase's `extraction_focus` text is
  injected, plus the document's extracted Markdown. Output is strict JSON:

```json
{
  "document_type": "design review minutes",
  "milestones": [
    {
      "date": "2026-08-12",
      "title": "Control system IFC package approved",
      "type": "gate",
      "confidence": 0.9,
      "evidence": "…quoted source text…"
    }
  ],
  "digest_contribution": "2–3 sentence summary of this document"
}
```

Malformed JSON → one repair retry → job fails visibly with the raw output
stored for debugging; the document stays browsable at its tier.
- Milestones land with status `extracted` and appear in the review
  workflow. A phase digest regenerates whenever a document in that phase
  completes LLM extraction or a milestone in it is confirmed, edited, or
  dismissed.

### 5.2 Background processing

A single in-process worker thread polls `ExtractionJob` for pending rows and
processes them sequentially (light flow makes this ample). Same logic
exposed as a management command (`process_queue`) for manual runs.

## 6. Revision management

Design-phase deliverables rev constantly; the latest revision must be
obvious and prior revisions preserved.

- Every document belongs to a **series**; each file is a **revision** within
  it. Exactly one revision per series is `is_latest`.
- **Supersede flow:** when a new file arrives with no series, the app
  computes candidates in the same phase — current-latest documents ranked by
  normalized filename similarity (revision markers like `v2`, `revC`,
  `_final`, dates stripped before comparison; similarity via
  `difflib.SequenceMatcher` on the normalized stems, top 5 kept) — and
  presents a confirmation card: "supersedes X" (top suggestions listed) or
  "new series" (asks for a title). In-place replacements (checksum change)
  auto-suggest the original as predecessor.
- On confirmation: the new file joins the series with
  `revision_number = max + 1`; the previous revision is marked superseded
  and, in `move` archive mode, physically moved to the phase's `_archive/`
  folder. Every move writes an ArchiveMove row and is one-click undoable.
- **Revision history view:** for any series, the full chronological stack —
  revision numbers, dates, file, extraction status, and an optional LLM
  one-line delta summary between consecutive revisions (regenerated on
  demand, not automatically).

## 7. UI

Server-rendered Django templates, minimal JavaScript for timeline
rendering. Four screens plus admin:

1. **Portfolio** (home) — every project as a track: current phase, phase
   progression bar, latest confirmed milestones, open-issue count.
2. **Project timeline** — milestone ledger chronological across phases,
   filterable by phase / type / status; pending-review milestones
   highlighted; confirm / edit / dismiss actions (form posts).
3. **Phase detail** — documents in the phase (latest revisions prominent,
   archived collapsed), phase digest, pending milestones, supersede
   confirmation cards for unassigned new files.
4. **Settings** — LM Studio base URL / model / parameters, MinerU path and
   options, workspace root, archive mode, watcher toggle; LM Studio
   connection status.
5. **Django admin** — full CRUD on all models for corrections and cleanup.

Future screens (cross-project search, weekly report) are cheap additions on
the same models; deliberately out of scope for v1.

## 8. Error handling summary

| Failure | Behavior |
|---|---|
| MinerU missing/crashes | Fallback to native tier; Document flagged |
| Unreadable file | Metadata-tier Document with visible flag |
| LM Studio down / bad JSON | Job retries, then fails visibly with raw output stored; ingestion unaffected |
| Watcher misses events | Rescan button + startup reconciliation |
| Wrong supersede confirmation | Undo via ArchiveMove log |
| App deleted | Folders remain plain, usable folders |

## 9. Testing

- Fixture files drive extractor unit tests: a small text PDF, a scanned PDF,
  DOCX, PPTX, EML, a fake CAD file (renamed binary).
- LLM client is mocked in tests (deterministic fixtures); a `--live` flag
  runs a real smoke test against LM Studio on demand.
- Integration test: temp workspace, drop fixture file via the watcher API,
  assert Document + Milestone rows appear.
- Revision flow tests: supersede, archive move + undo, db_only mode.

## 10. Build stages (each shippable on its own)

1. **Workspace** — Django skeleton, settings, project/phase management with
   editable ordering, folder scaffolding, watcher + ingestion (metadata
   tier), portfolio and phase screens.
2. **Intelligence** — MinerU + native extraction tiers, LM Studio client,
   milestone extraction, phase digests, review workflow, timeline screen.
3. **Revisions** — series, supersede flow, `_archive/` moves with undo,
   revision history view.

## 11. Non-goals (v1)

Multi-user access, cloud sync or hosting, mobile UI, CAD geometry parsing,
email threading reconstruction, automated gate scheduling, notifications,
cross-project search UI.
