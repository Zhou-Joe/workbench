from django.test import TestCase
from django.urls import reverse

from hub import ingest
from hub.models import AppSettings, Document, Milestone, Project
from hub.tests.helpers import WorkspaceTestCase, make_docx
from hub.worker import Worker


class PortfolioViewTests(TestCase):
    def test_home_empty(self):
        resp = self.client.get(reverse("hub:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No projects yet")

    def test_create_project_via_htmx(self):
        resp = self.client.post(
            reverse("hub:project_create"),
            {"name": "Cosmic Coaster", "code": "CC"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cosmic Coaster")
        project = Project.objects.get(slug="cosmic-coaster")
        self.assertEqual(project.phases.count(), 6)
        self.assertEqual(project.phases.first().name, "Blue Sky")


class ProjectViewTests(WorkspaceTestCase):
    def test_project_page_shows_ledger(self):
        project = self.seed_project()
        resp = self.client.get(reverse("hub:project", args=[project.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Milestone ledger")

    def test_phase_add_between(self):
        project = self.seed_project()
        resp = self.client.post(
            reverse("hub:phase_add", args=[project.slug]),
            {"name": "Permitting", "position": "after:2"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        names = list(project.phases.values_list("name", flat=True))
        self.assertEqual(names, ["Phase 1", "Phase 2", "Permitting", "Phase 3"])
        orders = list(project.phases.values_list("order", flat=True))
        self.assertEqual(orders, [1, 2, 3, 4])
        folders = sorted(
            p.name for p in (self.root / project.slug).iterdir() if p.is_dir()
        )
        self.assertEqual(folders, ["01-phase-1", "02-phase-2", "03-permitting", "04-phase-3"])

    def test_rescan_reports_new_files(self):
        project = self.seed_project()
        make_docx(self.phase_dir(project, 1) / "note.docx", ["hello"])
        resp = self.client.post(
            reverse("hub:project_rescan", args=[project.slug]),
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "1 new file")
        self.assertEqual(Document.objects.count(), 1)


class PhaseViewTests(WorkspaceTestCase):
    def test_phase_page_and_unassigned_card(self):
        project = self.seed_project()
        make_docx(self.phase_dir(project, 2) / "pkg.docx", ["x"])
        ingest.scan_project(project)
        resp = self.client.get(
            reverse("hub:phase", args=[project.slug, 2])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "pkg.docx")
        self.assertContains(resp, "Start a new series")


class MilestoneActionTests(WorkspaceTestCase):
    def test_confirm_returns_row_and_queues_digest(self):
        from unittest.mock import patch

        project = self.seed_project()
        phase = project.phases.get(order=1)
        from hub.tests.test_pipeline import fake_chat

        make_docx(self.phase_dir(project, 1) / "m.docx", ["approved"])
        ingest.scan_project(project)
        with patch("hub.llm.chat", side_effect=fake_chat):
            Worker().run_pending()
        ms = Milestone.objects.first()
        self.assertIsNotNone(ms)

        resp = self.client.post(
            reverse("hub:milestone_action", args=[ms.pk]),
            {"action": "confirm"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        ms.refresh_from_db()
        self.assertEqual(ms.status, "confirmed")
        from hub.models import ExtractionJob

        self.assertTrue(
            ExtractionJob.objects.filter(phase=phase, kind="digest", status="queued").exists()
        )


class SettingsViewTests(TestCase):
    def test_settings_save(self):
        resp = self.client.post(
            reverse("hub:settings"),
            {
                "workspace_root": "~/RideProjects",
                "lm_base_url": "http://localhost:1234/v1",
                "lm_model": "qwen3-8b",
                "lm_temperature": "0.2",
                "lm_max_tokens": "2048",
                "mineru_path": "mineru",
                "mineru_timeout": "900",
                "archive_mode": "move",
                "watch_enabled": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        settings = AppSettings.load()
        self.assertEqual(settings.lm_model, "qwen3-8b")
        self.assertTrue(settings.watch_enabled)


class SseTests(TestCase):
    def test_sse_content_type(self):
        resp = self.client.get(reverse("hub:sse"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/event-stream")
        self.assertEqual(resp["Cache-Control"], "no-cache")
