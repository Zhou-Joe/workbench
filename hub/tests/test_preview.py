from django.urls import reverse

from hub import ingest
from hub.tests.helpers import (
    WorkspaceTestCase,
    make_docx,
    make_fake_cad,
    make_text_pdf,
    make_xlsx,
)


class PreviewTests(WorkspaceTestCase):
    def test_pdf_preview_served_inline(self):
        project = self.seed_project()
        make_text_pdf(self.phase_dir(project, 1) / "note.pdf", "hello")
        ingest.scan_project(project)
        resp = self.client.get(
            reverse("hub:preview"),
            {"path": f"{project.slug}/01-phase-1/note.pdf"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertNotIn("attachment", resp.get("Content-Disposition", ""))

    def test_docx_preview_converts_to_html(self):
        project = self.seed_project()
        make_docx(
            self.phase_dir(project, 2) / "minutes.docx",
            ["Design Review Minutes", "Control system approved for construction"],
        )
        resp = self.client.get(
            reverse("hub:preview"),
            {"path": f"{project.slug}/02-phase-2/minutes.docx"},
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Control system approved for construction", html)

    def test_xlsx_preview_renders_tables(self):
        project = self.seed_project()
        make_xlsx(
            self.phase_dir(project, 3) / "status.xlsx",
            [["Item", "Status"], ["Track welds", "complete"]],
        )
        resp = self.client.get(
            reverse("hub:preview"),
            {"path": f"{project.slug}/03-phase-3/status.xlsx"},
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Track welds", html)
        self.assertIn("complete", html)

    def test_text_file_preview_inline(self):
        project = self.seed_project()
        target = self.phase_dir(project, 1) / "notes.txt"
        target.write_text("plain text content")
        resp = self.client.get(
            reverse("hub:preview"),
            {"path": f"{project.slug}/01-phase-1/notes.txt"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["Content-Type"].startswith("text/"))

    def test_cad_falls_back_to_notice(self):
        project = self.seed_project()
        make_fake_cad(self.phase_dir(project, 1) / "layout.dwg")
        resp = self.client.get(
            reverse("hub:preview"),
            {"path": f"{project.slug}/01-phase-1/layout.dwg"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("No in-browser preview", resp.content.decode())

    def test_preview_rejects_path_escape(self):
        resp = self.client.get(
            reverse("hub:preview"), {"path": "../../etc/hosts"}
        )
        self.assertEqual(resp.status_code, 400)
