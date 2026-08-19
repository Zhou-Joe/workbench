from django.test import TestCase
from django.urls import reverse

from hub import ingest
from hub.models import AppSettings, Document, Milestone, Project
from hub.tests.helpers import (
    WorkspaceTestCase,
    make_docx,
    make_fake_cad,
    make_text_pdf,
)
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

    def test_create_project_scaffolds_default_subfolders(self):
        from hub.models import AppSettings

        settings = AppSettings.load()
        settings.workspace_root = "/tmp/rph_scaffold_test"
        settings.save()
        import shutil
        from pathlib import Path

        shutil.rmtree("/tmp/rph_scaffold_test", ignore_errors=True)
        self.client.post(reverse("hub:project_create"), {"name": "Scaffold Test"})
        phase_dir = (
            Path("/tmp/rph_scaffold_test") / "scaffold-test" / "01-blue-sky"
        )
        self.assertEqual(
            sorted(p.name for p in phase_dir.iterdir()),
            ["01-incoming", "02-working", "03-issued"],
        )
        shutil.rmtree("/tmp/rph_scaffold_test", ignore_errors=True)


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

    def test_upload_saves_file_and_ingests(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        project = self.seed_project()
        upload = SimpleUploadedFile(
            "minutes.docx", b"placeholder", content_type="application/octet-stream"
        )
        make_docx(self.phase_dir(project, 3) / "existing.docx", ["already here"])
        resp = self.client.post(
            reverse("hub:phase_upload", args=[project.slug, 3]),
            {"files": [upload]},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        saved = self.phase_dir(project, 3) / "minutes.docx"
        self.assertTrue(saved.exists())
        self.assertEqual(saved.read_bytes(), b"placeholder")
        # both files ingested as documents
        from hub.models import Document

        names = set(
            Document.objects.filter(phase__project=project).values_list(
                "filename", flat=True
            )
        )
        self.assertEqual(names, {"minutes.docx", "existing.docx"})

    def test_upload_with_subfolder_creates_and_ingests(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from hub.models import Document

        project = self.seed_project()
        upload = SimpleUploadedFile("report.pdf", b"%PDF-1.4 nested")
        resp = self.client.post(
            reverse("hub:phase_upload", args=[project.slug, 2]),
            {"files": [upload], "folder": "structural/reports"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        saved = self.phase_dir(project, 2) / "structural" / "reports" / "report.pdf"
        self.assertTrue(saved.exists())
        doc = Document.objects.get(filename="report.pdf")
        self.assertEqual(doc.location, "structural/reports")

    def test_upload_rejects_unsafe_folder_segments(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        project = self.seed_project()
        upload = SimpleUploadedFile("x.pdf", b"abc")
        resp = self.client.post(
            reverse("hub:phase_upload", args=[project.slug, 1]),
            {"files": [upload], "folder": "../../outside"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        # ".." segments are dropped; the file stays inside the phase folder
        saved = self.phase_dir(project, 1) / "outside" / "x.pdf"
        self.assertTrue(saved.exists())
        self.assertFalse((self.root / "outside").exists())

    def test_browse_subfolder_shows_only_its_files(self):
        project = self.seed_project()
        pdir = self.phase_dir(project, 2)
        (pdir / "structural").mkdir()
        make_docx(pdir / "structural" / "deep.docx", ["nested"])
        make_docx(pdir / "top.docx", ["top level"])
        ingest.scan_project(project)

        root_view = self.client.get(reverse("hub:phase", args=[project.slug, 2]))
        self.assertContains(root_view, "top.docx")
        self.assertContains(root_view, "structural")
        # the file table lists only root-level files; the nested one appears
        # solely in the phase-wide unassigned panel (with its location chip)
        self.assertNotContains(
            root_view, 'title="cosmic-coaster/02-phase-2/structural/deep.docx"'
        )

        deep_view = self.client.get(
            reverse("hub:phase", args=[project.slug, 2]), {"path": "structural"}
        )
        self.assertContains(deep_view, "deep.docx")
        self.assertNotContains(deep_view, "top.docx")
        self.assertContains(deep_view, "structural")

    def test_browse_rejects_path_escape(self):
        project = self.seed_project()
        resp = self.client.get(
            reverse("hub:phase", args=[project.slug, 1]),
            {"path": "../../outside"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "outside /")

    def test_folder_new_creates_folder(self):
        project = self.seed_project()
        resp = self.client.post(
            reverse("hub:phase_folder_new", args=[project.slug, 1]),
            {"name": "Vendor Reports", "path": ""},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue((self.phase_dir(project, 1) / "vendor-reports").is_dir())

    def test_folder_new_with_slashes_creates_nested(self):
        project = self.seed_project()
        resp = self.client.post(
            reverse("hub:phase_folder_new", args=[project.slug, 1]),
            {"name": "vendor-a/calc reports", "path": ""},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            (self.phase_dir(project, 1) / "vendor-a" / "calc-reports").is_dir()
        )

    def test_files_grouped_by_format_newest_first(self):
        import os
        from datetime import datetime, timezone as tz

        project = self.seed_project()
        pdir = self.phase_dir(project, 2)
        make_text_pdf(pdir / "old-report.pdf", "old")
        make_text_pdf(pdir / "new-report.pdf", "new")
        make_docx(pdir / "minutes.docx", ["m"])
        make_fake_cad(pdir / "layout.dwg")
        now = datetime.now(tz.utc).timestamp()
        os.utime(pdir / "old-report.pdf", (now - 864_000, now - 864_000))
        os.utime(pdir / "new-report.pdf", (now, now))
        ingest.scan_project(project)

        resp = self.client.get(reverse("hub:phase", args=[project.slug, 2]))
        html = resp.content.decode()
        # group order: PDF before DOCX before DWG
        self.assertLess(html.index(">PDF<"), html.index(">DOCX<"))
        self.assertLess(html.index(">DOCX<"), html.index(">DWG<"))
        # newest first inside the PDF group (file table renders before the
        # unassigned panel, so first occurrences are the table rows)
        self.assertLess(html.index("new-report.pdf"), html.index("old-report.pdf"))

    def test_browse_three_levels_deep(self):
        project = self.seed_project()
        deep = self.phase_dir(project, 1) / "a" / "b" / "c"
        deep.mkdir(parents=True)
        make_docx(deep / "bottom.docx", ["very nested"])
        ingest.scan_project(project)

        resp = self.client.get(
            reverse("hub:phase", args=[project.slug, 1]), {"path": "a/b/c"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "bottom.docx")
        self.assertContains(resp, "c")
        # file indexed with its full nested location
        from hub.models import Document

        self.assertEqual(
            Document.objects.get(filename="bottom.docx").location, "a/b/c"
        )

    def test_upload_with_path_lands_in_browsed_folder(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from hub.models import Document

        project = self.seed_project()
        upload = SimpleUploadedFile("nested.pdf", b"%PDF-1.4 nested")
        resp = self.client.post(
            reverse("hub:phase_upload", args=[project.slug, 2]),
            {"files": [upload], "path": "structural/calcs"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        saved = (
            self.phase_dir(project, 2) / "structural" / "calcs" / "nested.pdf"
        )
        self.assertTrue(saved.exists())
        self.assertEqual(
            Document.objects.get(filename="nested.pdf").location,
            "structural/calcs",
        )

    def test_upload_without_workspace_root_is_bad_request(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        project = self.seed_project()
        self.settings_obj.workspace_root = ""
        self.settings_obj.save()
        upload = SimpleUploadedFile("x.pdf", b"abc")
        resp = self.client.post(
            reverse("hub:phase_upload", args=[project.slug, 1]),
            {"files": [upload]},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("workspace root", resp.content.decode().lower())


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
