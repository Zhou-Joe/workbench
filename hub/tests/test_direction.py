"""Tests for Now/Next dashboard, search, decision log, weekly report."""

from datetime import date, timedelta
from unittest.mock import patch

from django.urls import reverse

from hub.models import Document, ExtractionJob, Milestone, Project, WeeklyReport
from hub.tests.helpers import WorkspaceTestCase, make_docx
from hub.tests.test_pipeline import fake_chat
from hub.worker import Worker

REPORT_REPLY = (
    "## Progress (last 14 days)\n- 2026-08-12 [gate] Control system approved\n\n"
    "## Current phase\nDetail design ongoing.\n\n"
    "## Risks and open items\n- Weld inspection open 21 days\n\n"
    "## Watch next week\n- Close weld inspection"
)


def report_chat(settings, messages):
    system = messages[0]["content"] if messages else ""
    if "weekly status report" in system:
        return REPORT_REPLY
    return fake_chat(settings, messages)


class AttentionDashboardTests(WorkspaceTestCase):
    def test_dashboard_shows_pending_aging_and_unassigned(self):
        project = self.seed_project()
        phase = project.phases.get(order=1)
        old = date.today() - timedelta(days=30)
        Milestone.objects.create(
            project=project, phase=phase, date=old, title="Weld inspection outstanding",
            mtype="issue", status="confirmed",
        )
        Milestone.objects.create(
            project=project, phase=phase, date=date.today(), title="New gate hit",
            mtype="gate", status="extracted", confidence=0.9,
        )
        make_docx(self.phase_dir(project, 1) / "loose.docx", ["x"])  # unassigned
        from hub import ingest

        ingest.scan_project(project)

        resp = self.client.get(reverse("hub:home"))
        html = resp.content.decode()
        self.assertIn("Now / Next", html)
        self.assertIn("To review", html)
        self.assertIn("New gate hit", html)
        self.assertIn("Open issues", html)
        self.assertIn("Weld inspection outstanding", html)
        self.assertIn("badge-over", html)  # 30 days old, date in the past
        self.assertIn("Files awaiting assignment", html)
        self.assertIn("loose.docx", html)

    def test_dashboard_quiet_when_nothing_pending(self):
        self.seed_project()
        resp = self.client.get(reverse("hub:home"))
        self.assertContains(resp, "Nothing needs your attention")


class SearchTests(WorkspaceTestCase):
    def _doc_with_text(self, project, filename, text):
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

    def test_search_finds_text_with_highlight(self):
        project = self.seed_project()
        self._doc_with_text(
            project, "weld-notes.txt", "The track weld inspection is scheduled for August."
        )
        resp = self.client.get(reverse("hub:search"), {"q": "weld inspection"})
        html = resp.content.decode()
        self.assertIn("weld-notes.txt", html)
        self.assertIn("<mark>", html)
        self.assertIn(project.name, html)

    def test_search_requires_min_length(self):
        resp = self.client.get(reverse("hub:search"), {"q": "w"})
        self.assertContains(resp, "Type a keyword")

    def test_search_no_results_message(self):
        self.seed_project()
        resp = self.client.get(reverse("hub:search"), {"q": "xyzzy"})
        self.assertContains(resp, "No documents match")


class DecisionLogTests(WorkspaceTestCase):
    def test_decisions_view_lists_only_decisions(self):
        project = self.seed_project()
        phase = project.phases.get(order=2)
        Milestone.objects.create(
            project=project, phase=phase, date=date(2026, 3, 14),
            title="Mountain village theme locked", mtype="decision", status="confirmed",
            evidence="Board selected direction B.",
        )
        Milestone.objects.create(
            project=project, phase=phase, date=date(2026, 3, 20),
            title="Some gate", mtype="gate", status="confirmed",
        )
        resp = self.client.get(reverse("hub:project_decisions", args=[project.slug]))
        html = resp.content.decode()
        self.assertIn("Mountain village theme locked", html)
        self.assertIn("Board selected direction B.", html)
        self.assertNotIn("Some gate", html)


class WeeklyReportTests(WorkspaceTestCase):
    def test_report_generation_flow(self):
        project = self.seed_project()
        phase = project.phases.get(order=2)
        Milestone.objects.create(
            project=project, phase=phase, date=date.today() - timedelta(days=2),
            title="Control system approved for construction", mtype="gate",
            status="confirmed",
        )
        # POST queues the job
        resp = self.client.post(reverse("hub:project_report", args=[project.slug]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            ExtractionJob.objects.filter(
                project=project, kind="report", status="queued"
            ).exists()
        )
        # worker processes it with a mocked LLM
        with patch("hub.llm.chat", side_effect=report_chat):
            Worker().run_pending()
        report = WeeklyReport.objects.filter(project=project).first()
        self.assertIsNotNone(report)
        self.assertIn("Control system approved", report.content)
        # view shows the report
        resp = self.client.get(reverse("hub:project_report", args=[project.slug]))
        self.assertContains(resp, "Control system approved")

    def test_report_failure_is_visible(self):
        project = self.seed_project()
        self.client.post(reverse("hub:project_report", args=[project.slug]))
        with patch("hub.llm.chat", side_effect=Exception("LM Studio not reachable")):
            Worker().run_pending()
        resp = self.client.get(reverse("hub:project_report", args=[project.slug]))
        self.assertContains(resp, "LM Studio not reachable")
