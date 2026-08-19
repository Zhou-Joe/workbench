"""Ask-with-citations, jobs dashboard, auto tags + similar documents."""

import json
from unittest.mock import patch

from django.urls import reverse

from hub.models import Document, ExtractionJob, Question, Tag
from hub.tests.helpers import WorkspaceTestCase, make_docx
from hub.worker import Worker

ASK_REPLY = (
    "The weld inspection was postponed to September per Vendor X's email [1]. "
    "The control system IFC package was approved on 2026-08-12 [2]."
)


def ask_chat(settings, messages):
    return ASK_REPLY


class AskTests(WorkspaceTestCase):
    """Legacy single-shot retrieval path (agent disabled/failing)."""

    def _seed_doc(self, project, filename, text):
        phase = project.phases.get(order=1)
        return Document.objects.create(
            phase=phase,
            file_path=f"{project.slug}/01-phase-1/{filename}",
            filename=filename,
            extension=".txt",
            doc_kind="other",
            extraction_status="done",
            extracted_text=text,
        )

    def test_ask_flow_with_citations(self):
        project = self.seed_project()
        self._seed_doc(
            project, "vendor-email.txt", "weld inspection postponed to September by vendor"
        )
        self._seed_doc(
            project, "minutes.txt", "control system IFC package approved 2026-08-12"
        )
        self.client.post(reverse("hub:ask"), {"q": "What about the weld inspection?"})
        question = Question.objects.first()
        self.assertEqual(question.status, "queued")
        self.assertTrue(
            ExtractionJob.objects.filter(
                question=question, kind="ask", status="queued"
            ).exists()
        )
        with (
            patch("hub.agent.run_agent_question", side_effect=Exception("agent down")),
            patch("hub.llm.chat", side_effect=ask_chat),
        ):
            Worker().run_pending()
        question.refresh_from_db()
        self.assertEqual(question.status, "done")
        self.assertIn("weld inspection", question.answer)
        self.assertTrue(question.citations)
        self.assertIn("vendor-email.txt", json.dumps(question.citations))
        # view renders answer + citation link
        resp = self.client.get(reverse("hub:ask"))
        html = resp.content.decode()
        self.assertIn("weld inspection was postponed", html)
        self.assertIn("vendor-email.txt", html)

    def test_ask_no_matching_documents_answers_plainly(self):
        self.seed_project()
        self.client.post(reverse("hub:ask"), {"q": "anything about giraffes"})
        with patch("hub.agent.run_agent_question", side_effect=Exception("agent down")):
            Worker().run_pending()
        question = Question.objects.first()
        self.assertEqual(question.status, "done")
        self.assertIn("No extracted documents matched", question.answer)


class AgentAskTests(WorkspaceTestCase):
    def test_agent_path_with_tool_collected_citations(self):
        project = self.seed_project()
        phase = project.phases.get(order=1)
        doc = Document.objects.create(
            phase=phase,
            file_path=f"{project.slug}/01-phase-1/vendor-email.txt",
            filename="vendor-email.txt",
            extension=".txt",
            doc_kind="other",
            extraction_status="done",
            extracted_text="weld inspection postponed to September by vendor",
        )
        self.client.post(reverse("hub:ask"), {"q": "What about the weld inspection?"})
        question = Question.objects.first()

        def fake_agent(text, project=None):
            assert "weld inspection" in text
            return (
                "The inspection moves to September [vendor-email.txt].",
                [doc],
            )

        with patch("hub.agent.run_agent_question", side_effect=fake_agent):
            Worker().run_pending()
        question.refresh_from_db()
        self.assertEqual(question.status, "done")
        self.assertIn("September", question.answer)
        self.assertEqual(len(question.citations), 1)
        self.assertEqual(question.citations[0]["filename"], "vendor-email.txt")


class JobsDashboardTests(WorkspaceTestCase):
    def test_jobs_list_and_retry(self):
        project = self.seed_project()
        make_docx(self.phase_dir(project, 1) / "a.docx", ["x"])
        from hub import ingest

        ingest.scan_project(project)
        job = ExtractionJob.objects.first()
        job.status = "failed"
        job.error = "LM Studio not reachable"
        job.save()

        resp = self.client.get(reverse("hub:jobs"))
        self.assertContains(resp, "LM Studio not reachable")
        self.assertContains(resp, "Retry")

        resp = self.client.post(reverse("hub:job_retry", args=[job.pk]))
        self.assertEqual(resp.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.error, "")

    def test_jobs_status_filter(self):
        resp = self.client.get(reverse("hub:jobs"), {"status": "failed"})
        self.assertEqual(resp.status_code, 200)


class AutoTagTests(WorkspaceTestCase):
    def test_extraction_assigns_tags(self):
        reply = json.dumps(
            {
                "document_type": "calculation report",
                "milestones": [
                    {
                        "date": "2026-08-12",
                        "title": "Frame analysis complete",
                        "type": "deliverable",
                        "confidence": 0.9,
                        "evidence": "Analysis approved.",
                    }
                ],
                "tags": ["structural", "calculations"],
                "digest_contribution": "Structural calcs.",
            }
        )

        def chat(settings, messages):
            system = messages[0]["content"] if messages else ""
            if "running summary" in system:
                return "## Where we are\ncalcs done"
            return reply

        project = self.seed_project()
        make_docx(
            self.phase_dir(project, 2) / "calcs.docx",
            ["Frame analysis complete, approved"],
        )
        from hub import ingest

        ingest.scan_project(project)
        with patch("hub.llm.chat", side_effect=chat):
            Worker().run_pending()
        doc = Document.objects.get(filename="calcs.docx")
        self.assertEqual(
            set(doc.tags.values_list("name", flat=True)),
            {"structural", "calculations"},
        )
        self.assertEqual(Tag.objects.count(), 2)


class SimilarDocsTests(WorkspaceTestCase):
    def test_preview_shows_similar_documents(self):
        project = self.seed_project()
        phase = project.phases.get(order=1)
        # real file on disk so the docx preview branch renders
        make_docx(
            self.phase_dir(project, 1) / "calc-v1.docx",
            ["track weld inspection procedure and acceptance criteria"],
        )
        Document.objects.create(
            phase=phase, file_path=f"{project.slug}/01-phase-1/calc-v1.docx",
            filename="calc-v1.docx", extension=".docx", doc_kind="office",
            extraction_status="done",
            extracted_text="track weld inspection procedure and acceptance criteria",
        )
        Document.objects.create(
            phase=phase, file_path=f"{project.slug}/01-phase-1/calc-v2.docx",
            filename="calc-v2.docx", extension=".docx", doc_kind="office",
            extraction_status="done",
            extracted_text="track weld inspection procedure and acceptance criteria revision",
        )
        resp = self.client.get(
            reverse("hub:preview"),
            {"path": f"{project.slug}/01-phase-1/calc-v1.docx"},
        )
        html = resp.content.decode()
        self.assertIn("Similar documents", html)
        self.assertIn("calc-v2.docx", html)
