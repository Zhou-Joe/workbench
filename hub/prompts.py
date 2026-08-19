"""Prompt construction for milestone extraction, digests and revision deltas."""

import json

MAX_TEXT_CHARS = 24_000

SYSTEM_CAPTURE = """\
You route a quick note from a ride development engineer into their project \
workspace. Given the note and the list of projects with their phases (each \
phase has an extraction focus describing its purpose), decide where it \
belongs. Return ONLY a JSON object:
{"project_slug": "slug or null if nothing matches",
 "phase_order": 3,
 "confidence": 0.0,
 "tags": ["up to 3 short tags"],
 "rationale": "one short sentence"}
Rules: only use slugs and phase orders from the list. If the note clearly \
does not belong to any project, return null for project_slug."""


def build_capture_prompt(text, projects_info):
    parts = ["NOTE:", text, "", "AVAILABLE DESTINATIONS:"]
    for slug, name, order, phase_name, focus in projects_info:
        parts.append(f"- {slug} / phase {order:02d} {phase_name}" + (f" — {focus}" if focus else ""))
    return "\n".join(parts)


ASK_EXCERPT_CHARS = 4_000
ASK_MAX_SOURCES = 6

SYSTEM_ASK = """\
You answer a ride development engineer's questions using ONLY the numbered \
document excerpts provided. Cite sources inline like [1] or [2][5] after \
every claim. If the excerpts do not contain the answer, say so plainly and \
suggest which document kind would likely hold it. Never invent facts, dates \
or decisions. Answer in the language of the question. Be concise and \
concrete: names, dates, numbers."""


def build_ask_prompt(question, excerpts):
    """excerpts: list of (filename, text) — numbered [1]..[n]."""
    parts = [f"Question: {question}", ""]
    for i, (filename, text) in enumerate(excerpts, start=1):
        if len(text) > ASK_EXCERPT_CHARS:
            text = text[:ASK_EXCERPT_CHARS] + "\n[…truncated…]"
        parts.append(f"[{i}] {filename}")
        parts.append(text)
        parts.append("")
    return "\n".join(parts)

SYSTEM_EXTRACTION = """\
You extract engineering project milestones from amusement ride development \
documents. You work for a ride development engineer coordinating multiple \
ride projects through phased design lifecycles.

Return ONLY a JSON object, no prose before or after, with this exact shape:
{
  "document_type": "short label, e.g. 'design review minutes'",
  "milestones": [
    {
      "date": "YYYY-MM-DD or null",
      "title": "one clear sentence",
      "type": "gate | decision | deliverable | issue | risk | action",
      "confidence": 0.0,
      "evidence": "short quote from the document supporting the milestone"
    }
  ],
  "tags": ["structural", "controls"],
  "digest_contribution": "2-3 sentence summary of this document"
}

Rules:
- Extract only what the document actually states. Never invent dates or events.
- Use dates found in the document; null if none.
- If the document contains no milestones, return an empty milestones list.
- Keep titles factual and self-contained (a colleague should understand them \
without opening the document).
- Confidence between 0.0 and 1.0: how sure you are this is a real milestone.
- tags: 0-5 discipline tags. Prefer this vocabulary: structural, ride-system, \
controls, electrical, show, scenic, audio-video, geotechnical, safety, \
procurement, contracts, permits, schedule, budget, testing, commissioning, \
vendor-correspondence, meeting-minutes, calculations, drawings, reports. \
Add a different short tag only when none of these fit.
"""


def build_extraction_prompt(phase, document):
    focus = phase.extraction_focus.strip()
    meta = {
        "project": phase.project.name,
        "phase": f"{phase.order:02d} {phase.name}",
        "filename": document.filename,
        "file_type": document.doc_kind,
    }
    text = document.extracted_text or ""
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n\n[…truncated…]"
    lines = [
        f"Project: {meta['project']}",
        f"Phase: {meta['phase']}",
        f"Filename: {meta['filename']}",
        f"File type: {meta['file_type']}",
    ]
    if focus:
        lines.append(
            f"In this phase, pay special attention to: {focus}"
        )
    lines.append("")
    lines.append("DOCUMENT CONTENT:")
    lines.append(text if text.strip() else "[no machine-readable content]")
    return "\n".join(lines)


SYSTEM_DIGEST = """\
You write a running summary of one design phase of an amusement ride \
project, for the engineer who owns it. Use the contributed document \
summaries and the confirmed milestones below. Output Markdown only: \
a '## Where we are' paragraph, a '## Key milestones' bullet list \
(newest first), and an '## Open items' bullet list of unresolved \
issues/risks/actions. Be concrete: names, dates, numbers. Never invent \
facts. Max ~250 words."""


def build_digest_prompt(phase, contributions, milestones):
    parts = [f"Project: {phase.project.name}", f"Phase: {phase.order:02d} {phase.name}", ""]
    if contributions:
        parts.append("DOCUMENT SUMMARIES:")
        for filename, contribution in contributions:
            parts.append(f"- {filename}: {contribution}")
        parts.append("")
    if milestones:
        parts.append("MILESTONES:")
        for date, title, mtype, status in milestones:
            date_s = date.isoformat() if date else "no date"
            parts.append(f"- {date_s} [{mtype}] ({status}) {title}")
        parts.append("")
    if len(contributions) > 60:
        parts = parts[:10] + ["[…older entries truncated…]"] + parts[-60:]
    return "\n".join(parts)


SYSTEM_REPORT = """\
You write a concise weekly status report for one amusement ride project, \
for the engineer who owns it and for their management. Use only the \
provided milestones, open items, and phase digest — never invent facts. \
Output Markdown only, in English, with exactly these sections:
## Progress (last 14 days)
bullet list of confirmed milestones with dates
## Current phase
one short paragraph from the phase digest
## Risks and open items
bullet list of open issues/risks/actions, each tagged with its age in days
## Watch next week
2-4 bullets of the most pressing items to move forward, derived only from \
the open items and upcoming work visible in the data
Max ~250 words. Concrete: names, dates, numbers."""


def build_report_prompt(project, recent_milestones, open_items, digest_text, today):
    parts = [f"Project: {project.name}", f"Today: {today.isoformat()}", ""]
    parts.append("CONFIRMED MILESTONES (last 14 days):")
    if recent_milestones:
        for date, title, mtype in recent_milestones:
            parts.append(f"- {date} [{mtype}] {title}")
    else:
        parts.append("- none recorded")
    parts.append("")
    parts.append("OPEN ITEMS (issues/risks/actions not dismissed):")
    if open_items:
        for date, title, mtype, age_days in open_items:
            parts.append(f"- {date} [{mtype}] {title} (open {age_days} days)")
    else:
        parts.append("- none")
    parts.append("")
    parts.append("CURRENT PHASE DIGEST:")
    parts.append(digest_text or "(no digest yet)")
    return "\n".join(parts)


SYSTEM_DELTA = """\
You compare two revisions of an engineering document and state what \
changed. Return ONLY a JSON object: {"delta": "one or two sentences"}. \
Focus on substance: scope, status, approvals, dates, numbers. If the \
texts are near-identical, say so plainly. Never invent changes."""


def build_delta_prompt(series_title, old_doc, new_doc):
    def clip(doc):
        text = doc.extracted_text or "[no extracted text — metadata only]"
        if len(text) > 12_000:
            text = text[:12_000] + "\n\n[…truncated…]"
        return text

    return json.dumps(
        {
            "series": series_title,
            "older_revision": {
                "filename": old_doc.filename,
                "date": str(old_doc.file_mtime or ""),
                "content": clip(old_doc),
            },
            "newer_revision": {
                "filename": new_doc.filename,
                "date": str(new_doc.file_mtime or ""),
                "content": clip(new_doc),
            },
        },
        indent=1,
    )
