"""Sequential background job processing: parse → LLM extract → digest/delta."""

import logging
import threading

from django.db import close_old_connections
from django.utils import timezone

from . import extract, llm, prompts
from .events import bus, publish_doc_event
from .models import AppSettings, Document, ExtractionJob, Milestone, PhaseDigest

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


class Worker:
    """Runs in a daemon thread; also usable synchronously in tests via run_pending()."""

    def __init__(self):
        self.stop_event = threading.Event()

    def run_forever(self, poll_seconds=1.5):
        while not self.stop_event.is_set():
            try:
                self.run_pending()
            except Exception:
                logger.exception("worker loop error")
            self.stop_event.wait(poll_seconds)

    def run_pending(self):
        while True:
            job = (
                ExtractionJob.objects.filter(status=ExtractionJob.Status.QUEUED)
                .order_by("pk")
                .first()
            )
            if job is None:
                return
            self.process(job)

    def process(self, job):
        close_old_connections()
        job.attempts += 1
        job.status = ExtractionJob.Status.RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=["attempts", "status", "started_at"])
        handler = {
            ExtractionJob.Kind.PARSE: self.process_parse,
            ExtractionJob.Kind.LLM: self.process_llm,
            ExtractionJob.Kind.DIGEST: self.process_digest,
            ExtractionJob.Kind.DELTA: self.process_delta,
            ExtractionJob.Kind.REPORT: self.process_report,
        }[job.kind]
        try:
            handler(job)
            job.status = ExtractionJob.Status.DONE
            job.error = ""
        except Exception as exc:
            logger.exception("job %s failed", job)
            job.error = f"{exc.__class__.__name__}: {exc}"
            retryable = job.attempts < MAX_ATTEMPTS
            job.status = (
                ExtractionJob.Status.QUEUED if retryable else ExtractionJob.Status.FAILED
            )
            if job.document_id and not retryable:
                doc = Document.objects.filter(pk=job.document_id).first()
                if doc:
                    doc.extraction_status = Document.Status.FAILED
                    doc.save(update_fields=["extraction_status"])
                    publish_doc_event(doc, "failed")
        finally:
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error", "finished_at"])

    # -- handlers ---------------------------------------------------------

    def process_parse(self, job):
        settings = AppSettings.load()
        doc = job.document
        doc.extraction_status = Document.Status.PROCESSING
        doc.save(update_fields=["extraction_status"])
        publish_doc_event(doc, "processing")
        from . import workspace as ws

        root = settings.expanded_workspace_root()
        abs_path = f"{root}/{doc.file_path}"
        text, tier, note = extract.extract(
            abs_path,
            mineru_path=settings.mineru_path,
            mineru_timeout=settings.mineru_timeout,
        )
        doc.extracted_text = text
        doc.extraction_tier = tier
        doc.quality_note = note
        doc.extraction_status = Document.Status.DONE
        doc.extracted_at = timezone.now()
        doc.save()
        publish_doc_event(doc, "extracted")
        ExtractionJob.objects.create(document=doc, kind=ExtractionJob.Kind.LLM)

    def process_llm(self, job):
        settings = AppSettings.load()
        doc = job.document
        phase = doc.phase
        user_prompt = prompts.build_extraction_prompt(phase, doc)
        content = llm.chat(
            settings,
            [
                {"role": "system", "content": prompts.SYSTEM_EXTRACTION},
                {"role": "user", "content": user_prompt},
            ],
        )
        data = llm.extract_json(content)
        doc.doc_type_label = str(data.get("document_type", ""))[:200]
        doc.digest_contribution = str(data.get("digest_contribution", ""))[:2000]
        doc.save(update_fields=["doc_type_label", "digest_contribution"])
        for item in data.get("milestones", []):
            if not isinstance(item, dict) or not item.get("title"):
                continue
            try:
                confidence = float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            raw_date = str(item.get("date") or "").strip() or None
            date = parse_date(raw_date)
            Milestone.objects.create(
                project=phase.project,
                phase=phase,
                document=doc,
                date=date,
                title=str(item.get("title", ""))[:400],
                mtype=_valid_type(item.get("type")),
                confidence=max(0.0, min(1.0, confidence)),
                evidence=str(item.get("evidence", ""))[:2000],
            )
        publish_doc_event(doc, "milestones")
        ExtractionJob.objects.create(phase=phase, kind=ExtractionJob.Kind.DIGEST)

    def process_digest(self, job):
        settings = AppSettings.load()
        phase = job.phase
        docs = phase.documents.exclude(digest_contribution="").order_by("ingested_at")
        contributions = [(d.filename, d.digest_contribution) for d in docs]
        milestones = [
            (m.date, m.title, m.mtype, m.status)
            for m in phase.milestones.exclude(status="dismissed")
        ]
        if not contributions and not milestones:
            return
        content = llm.chat(
            settings,
            [
                {"role": "system", "content": prompts.SYSTEM_DIGEST},
                {"role": "user", "content": prompts.build_digest_prompt(phase, contributions, milestones)},
            ],
        )
        digest, _ = PhaseDigest.objects.get_or_create(phase=phase)
        digest.content = content
        digest.model_used = settings.lm_model
        digest.save()
        bus.publish("digest", project_id=phase.project_id, phase_id=phase.pk)

    def process_report(self, job):
        from datetime import timedelta

        from .models import WeeklyReport

        settings = AppSettings.load()
        project = job.project
        cutoff = timezone.now().date() - timedelta(days=14)
        today = timezone.now().date()

        def age_days(m):
            base = m.date or m.created_at.date()
            return max(0, (today - base).days)

        recent = [
            (m.date, m.title, m.mtype)
            for m in Milestone.objects.filter(
                project=project,
                status__in=["confirmed", "edited"],
                date__gte=cutoff,
            ).order_by("-date")
        ]
        open_items = [
            (m.date or m.created_at.date(), m.title, m.mtype, age_days(m))
            for m in Milestone.objects.filter(
                project=project,
                mtype__in=["issue", "risk", "action"],
                status__in=["extracted", "confirmed", "edited"],
            ).order_by("date")
        ]
        current = project.current_phase()
        digest_text = ""
        if current and hasattr(current, "digest") and current.digest.content:
            digest_text = current.digest.content
        content = llm.chat(
            settings,
            [
                {"role": "system", "content": prompts.SYSTEM_REPORT},
                {
                    "role": "user",
                    "content": prompts.build_report_prompt(
                        project, recent, open_items, digest_text, today
                    ),
                },
            ],
        )
        WeeklyReport.objects.create(
            project=project, content=content, model_used=settings.lm_model
        )
        bus.publish("report", project_id=project.pk)

    def process_delta(self, job):
        settings = AppSettings.load()
        series = job.series
        stack = list(series.revisions.order_by("revision_number", "ingested_at"))
        if len(stack) < 2:
            return
        for older, newer in zip(stack, stack[1:]):
            if newer.delta_summary:
                continue
            content = llm.chat(
                settings,
                [
                    {"role": "system", "content": prompts.SYSTEM_DELTA},
                    {"role": "user", "content": prompts.build_delta_prompt(series.title, older, newer)},
                ],
            )
            data = llm.extract_json(content)
            newer.delta_summary = str(data.get("delta", ""))[:1000]
            newer.save(update_fields=["delta_summary"])
        bus.publish("revision", project_id=series.phase.project_id, phase_id=series.phase_id)


def parse_date(raw):
    if not raw or raw.lower() in ("null", "none"):
        return None
    from datetime import datetime

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _valid_type(value):
    values = {c.value for c in Milestone.MType}
    v = str(value or "").lower().strip()
    return v if v in values else Milestone.MType.GATE
