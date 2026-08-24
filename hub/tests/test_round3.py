"""Saved searches with alerts, project export, revision diff."""

import io
import json
import zipfile

from django.urls import reverse

from hub.models import Document, DocumentSeries, Milestone, SavedSearch
from hub.tests.helpers import WorkspaceTestCase, make_docx
from hub.tests.test_pipeline import fake_chat
from unittest.mock import patch


class SavedSearchTests(WorkspaceTestCase):
    def _doc(self, project, filename, text):
        phase = project.phases.get(order=1)
        return Document.objects.create(
            phase=phase,
            file_path=f"{project.slug}/01-phase-1/{filename}",
            filename=filename, extension=".txt", doc_kind="other",
            extraction_status="done", extracted_text=text,
        )

    def test_pin_alert_and_mark_seen(self):
        project = self.seed_project()
        self._doc(project, "a.txt", "weld inspection scheduled")
        # pin the search (baseline = current count = 1)
        self.client.post(reverse("hub:search_save"), {"q": "weld inspection"})
        saved = SavedSearch.objects.get()
        self.assertEqual(saved.last_count, 1)

        # a new matching document lands
        self._doc(project, "b.txt", "second weld inspection note")
        home = self.client.get(reverse("hub:home")).content.decode()
        self.assertIn("Saved-search alerts", home)
        self.assertIn("1 new", home)

        # viewing via the saved link marks it seen
        self.client.get(
            reverse("hub:search"),
            {"q": "weld inspection", "seen": saved.pk},
        )
        saved.refresh_from_db()
        self.assertEqual(saved.last_count, 2)
        home = self.client.get(reverse("hub:home")).content.decode()
        self.assertNotIn("Saved-search alerts", home)

    def test_unpin(self):
        self.seed_project()
        SavedSearch.objects.create(name="x", query="weld", last_count=0)
        saved = SavedSearch.objects.get()
        self.client.post(reverse("hub:search_delete", args=[saved.pk]))
        self.assertFalse(SavedSearch.objects.exists())


class ProjectExportTests(WorkspaceTestCase):
    def test_export_contains_files_and_data(self):
        from datetime import date

        project = self.seed_project()
        make_docx(self.phase_dir(project, 1) / "note.docx", ["hello export"])
        phase = project.phases.get(order=1)
        Milestone.objects.create(
            project=project, phase=phase, date=date(2026, 8, 1),
            title="Gate hit", mtype="gate", status="confirmed",
        )
        resp = self.client.get(reverse("hub:project_export", args=[project.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("export", resp["Content-Disposition"])
        buf = io.BytesIO(b"".join(resp.streaming_content))
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            self.assertIn("ridehub-data.json", names)
            self.assertIn(f"{project.slug}/01-phase-1/note.docx", names)
            data = json.loads(zf.read("ridehub-data.json"))
        self.assertEqual(data["project"]["slug"], project.slug)
        self.assertEqual(data["milestones"][0]["title"], "Gate hit")


class DiffViewTests(WorkspaceTestCase):
    def _series(self):
        project = self.seed_project()
        phase = project.phases.get(order=1)
        series = DocumentSeries.objects.create(phase=phase, title="IFC Package")
        old = Document.objects.create(
            phase=phase, series=series, revision_number=1, is_latest=False,
            file_path=f"{project.slug}/01-phase-1/pkg_r1.txt", filename="pkg_r1.txt",
            extension=".txt", doc_kind="other", extraction_status="done",
            extracted_text="scope line\nunchanged line\nold conclusion",
        )
        new = Document.objects.create(
            phase=phase, series=series, revision_number=2, is_latest=True,
            file_path=f"{project.slug}/01-phase-1/pkg_r2.txt", filename="pkg_r2.txt",
            extension=".txt", doc_kind="other", extraction_status="done",
            extracted_text="scope line\nunchanged line\nnew conclusion with weld detail",
        )
        return series, old, new

    def test_diff_defaults_to_last_two_revisions(self):
        series, old, new = self._series()
        resp = self.client.get(reverse("hub:series_diff", args=[series.pk]))
        html = resp.content.decode()
        self.assertIn("old conclusion", html)
        self.assertIn("new conclusion with weld detail", html)
        self.assertIn("diff-changed", html)      # changed line highlighted
        self.assertIn("unchanged line", html)    # context shown

    def test_diff_picker_selects_specific_revisions(self):
        series, old, new = self._series()
        resp = self.client.get(
            reverse("hub:series_diff", args=[series.pk]),
            {"a": str(old.pk), "b": str(new.pk)},
        )
        self.assertEqual(resp.status_code, 200)

    def test_series_with_one_revision_shows_notice(self):
        project = self.seed_project()
        phase = project.phases.get(order=1)
        series = DocumentSeries.objects.create(phase=phase, title="Solo")
        Document.objects.create(
            phase=phase, series=series, revision_number=1, is_latest=True,
            file_path=f"{project.slug}/01-phase-1/solo.txt", filename="solo.txt",
            extension=".txt", doc_kind="other", extraction_status="done",
            extracted_text="only one",
        )
        resp = self.client.get(reverse("hub:series_diff", args=[series.pk]))
        self.assertIn("fewer than two revisions", resp.content.decode())
