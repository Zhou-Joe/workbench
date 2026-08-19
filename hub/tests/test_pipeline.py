"""End-to-end pipeline with a mocked LLM: file → parse → milestones → digest."""

import json
from unittest.mock import patch

from hub import ingest
from hub.models import Document, ExtractionJob, Milestone, PhaseDigest
from hub.tests.helpers import WorkspaceTestCase, make_docx, make_fake_cad, make_text_pdf
from hub.worker import Worker

LLM_EXTRACTION_REPLY = json.dumps(
    {
        "document_type": "design review minutes",
        "milestones": [
            {
                "date": "2026-08-12",
                "title": "Control system design approved for construction",
                "type": "gate",
                "confidence": 0.92,
                "evidence": "The board approved the control system design.",
            },
            {
                "date": None,
                "title": "Track weld inspection outstanding",
                "type": "issue",
                "confidence": 0.7,
                "evidence": "Weld inspection pending vendor schedule.",
            },
        ],
        "digest_contribution": "Review minutes covering control system approval.",
    }
)

LLM_DIGEST_REPLY = "## Where we are\nControl system approved.\n\n## Key milestones\n- 2026-08-12 approval"


def fake_chat(settings, messages):
    """Route by system prompt: extraction vs digest vs delta."""
    system = messages[0]["content"] if messages else ""
    if "running summary" in system:
        return LLM_DIGEST_REPLY
    return LLM_EXTRACTION_REPLY


class PipelineTests(WorkspaceTestCase):
    def _drop_and_process(self, filename, builder):
        project = self.seed_project()
        pdir = self.phase_dir(project, 2)
        builder(pdir / filename)
        ingest.scan_project(project)
        with patch("hub.llm.chat", side_effect=fake_chat):
            Worker().run_pending()
        return project, project.phases.get(order=2)

    def test_docx_through_pipeline(self):
        project, phase = self._drop_and_process(
            "minutes.docx",
            lambda p: make_docx(
                p,
                [
                    "Design review minutes 2026-08-12",
                    "The board approved the control system design.",
                    "Weld inspection pending vendor schedule.",
                ],
            ),
        )
        doc = Document.objects.get(phase=phase, filename="minutes.docx")
        self.assertEqual(doc.extraction_status, "done")
        self.assertEqual(doc.extraction_tier, "native")
        self.assertEqual(doc.doc_type_label, "design review minutes")
        gate = Milestone.objects.get(mtype="gate")
        self.assertEqual(gate.title, "Control system design approved for construction")
        self.assertEqual(str(gate.date), "2026-08-12")
        self.assertEqual(gate.status, "extracted")
        issue = Milestone.objects.get(mtype="issue")
        self.assertIsNone(issue.date)
        self.assertEqual(Milestone.objects.count(), 2)

    def test_digest_generated_after_extraction(self):
        project, phase = self._drop_and_process(
            "minutes2.docx",
            lambda p: make_docx(p, ["Review 2026-08-12", "approved control system"]),
        )
        digest = PhaseDigest.objects.get(phase=phase)
        self.assertIn("Control system approved", digest.content)
        self.assertTrue(
            ExtractionJob.objects.filter(
                phase=phase, kind="digest", status="done"
            ).exists()
        )

    def test_cad_file_uses_metadata_tier_but_still_extracts(self):
        project, phase = self._drop_and_process(
            "layout.dwg", lambda p: make_fake_cad(p)
        )
        doc = Document.objects.get(phase=phase, filename="layout.dwg")
        self.assertEqual(doc.extraction_tier, "metadata")
        self.assertEqual(doc.extraction_status, "done")
        self.assertIn("layout.dwg", doc.extracted_text)
        self.assertEqual(Milestone.objects.count(), 2)

    def test_llm_down_marks_jobs_failed_and_doc_visible(self):
        project = self.seed_project()
        pdir = self.phase_dir(project, 1)
        make_text_pdf(pdir / "note.pdf", "some content")
        ingest.scan_project(project)
        with patch("hub.llm.chat", side_effect=Exception("LM Studio not reachable")):
            Worker().run_pending()
        doc = Document.objects.get(filename="note.pdf")
        self.assertEqual(doc.extraction_status, "failed")
        failed = ExtractionJob.objects.filter(status="failed")
        self.assertTrue(failed.exists())
        self.assertIn("LM Studio not reachable", failed.first().error)
        # ingestion itself was fine: the document and its text are present
        self.assertIn("some content", doc.extracted_text)

    def test_bad_json_retried_then_succeeds(self):
        project = self.seed_project()
        pdir = self.phase_dir(project, 1)
        make_text_pdf(pdir / "bad.pdf", "text present")
        ingest.scan_project(project)
        calls = {"n": 0}

        def flaky_chat(settings, messages):
            calls["n"] += 1
            if calls["n"] == 1:
                return "not json at all"
            return fake_chat(settings, messages)

        with patch("hub.llm.chat", side_effect=flaky_chat):
            Worker().run_pending()
        self.assertEqual(Milestone.objects.count(), 2)
