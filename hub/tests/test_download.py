import io
import zipfile

from django.urls import reverse

from hub import ingest
from hub.tests.helpers import WorkspaceTestCase, make_docx, make_text_pdf


class DownloadTests(WorkspaceTestCase):
    def _zip_names(self, resp):
        buf = io.BytesIO(b"".join(resp.streaming_content))
        with zipfile.ZipFile(buf) as zf:
            return zf.namelist()

    def test_download_single_file(self):
        project = self.seed_project()
        make_text_pdf(self.phase_dir(project, 1) / "note.pdf", "hello world")
        ingest.scan_project(project)
        resp = self.client.get(
            reverse("hub:download_file"),
            {"path": f"{project.slug}/01-phase-1/note.pdf"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertIn("note.pdf", resp["Content-Disposition"])
        body = b"".join(resp.streaming_content)
        self.assertTrue(body.startswith(b"%PDF"))

    def test_download_rejects_path_escape(self):
        project = self.seed_project()
        resp = self.client.get(
            reverse("hub:download_file"), {"path": "../../etc/hosts"}
        )
        self.assertEqual(resp.status_code, 400)
        resp = self.client.get(reverse("hub:download_file"), {"path": "/etc/hosts"})
        self.assertEqual(resp.status_code, 400)

    def test_download_folder_as_zip(self):
        project = self.seed_project()
        pdir = self.phase_dir(project, 2)
        (pdir / "structural" / "calcs").mkdir(parents=True)
        make_text_pdf(pdir / "structural" / "calcs" / "deep.pdf", "deep")
        make_docx(pdir / "structural" / "top.docx", ["top"])
        (pdir / "structural" / ".DS_Store").write_bytes(b"junk")

        resp = self.client.get(
            reverse("hub:download_folder"),
            {"project": project.slug, "phase": 2, "path": "structural"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("structural.zip", resp["Content-Disposition"])
        names = self._zip_names(resp)
        self.assertIn("calcs/deep.pdf", names)
        self.assertIn("top.docx", names)
        self.assertEqual(len(names), 2)  # dotfile excluded

    def test_download_selection_as_zip(self):
        project = self.seed_project()
        pdir = self.phase_dir(project, 3)
        (pdir / "a").mkdir()
        make_docx(pdir / "a" / "one.docx", ["1"])
        make_docx(pdir / "two.docx", ["2"])
        ingest.scan_project(project)

        resp = self.client.get(
            reverse("hub:download_zip"),
            {"p": [f"{project.slug}/03-phase-3/a/one.docx", f"{project.slug}/03-phase-3/two.docx"]},
        )
        self.assertEqual(resp.status_code, 200)
        names = self._zip_names(resp)
        self.assertEqual(len(names), 2)
        self.assertIn(f"{project.slug}/03-phase-3/two.docx", names)

    def test_download_selection_empty_is_rejected(self):
        resp = self.client.get(reverse("hub:download_zip"))
        self.assertEqual(resp.status_code, 400)
