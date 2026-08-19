from django.test import TestCase

from hub import revisions
from hub.models import ArchiveMove, Document, DocumentSeries
from hub.tests.helpers import WorkspaceTestCase, make_text_pdf


class SimilarityTests(TestCase):
    def test_revision_markers_are_normalized_away(self):
        self.assertEqual(
            revisions.normalize_stem("Ride-Control-IFC-Package_RevA.pdf"),
            revisions.normalize_stem("Ride-Control-IFC-Package_RevB.pdf"),
        )
        self.assertEqual(
            revisions.normalize_stem("Track Layout v2.dwg"),
            revisions.normalize_stem("track layout final.dwg"),
        )
        self.assertNotEqual(
            revisions.normalize_stem("Ride-Control-IFC-Package.pdf"),
            revisions.normalize_stem("Show-Lighting-Package.pdf"),
        )


class SupersedeTests(WorkspaceTestCase):
    def _drop(self, project, order, filename, text):
        from hub import ingest

        pdir = self.phase_dir(project, order)
        path = pdir / filename
        make_text_pdf(path, text)
        new_docs, _ = ingest.scan_project(project)
        return new_docs[-1]

    def test_supersede_moves_previous_to_archive(self):
        project = self.seed_project()
        doc1 = self._drop(project, 2, "Ride-Control-IFC_RevA.pdf", "IFC Rev A issued")
        doc2 = self._drop(project, 2, "Ride-Control-IFC_RevB.pdf", "IFC Rev B issued")

        suggestions = revisions.suggest_predecessors(doc2)
        self.assertIn(doc1, suggestions)

        series = revisions.supersede(doc2, doc1)
        doc1.refresh_from_db()
        doc2.refresh_from_db()
        self.assertEqual(series.revisions.count(), 2)
        self.assertEqual(doc1.series, series)
        self.assertEqual(doc2.series, series)
        self.assertEqual(doc1.revision_number, 1)
        self.assertEqual(doc2.revision_number, 2)
        self.assertFalse(doc1.is_latest)
        self.assertTrue(doc2.is_latest)
        # file physically moved into _archive/
        self.assertIn("_archive", doc1.file_path)
        self.assertTrue((self.root / doc1.file_path).exists())
        self.assertFalse((self.phase_dir(project, 2) / "Ride-Control-IFC_RevA.pdf").exists())
        move = ArchiveMove.objects.get(document=doc1)
        self.assertFalse(move.undone)

    def test_undo_archive_restores_file(self):
        project = self.seed_project()
        doc1 = self._drop(project, 1, "Concept Deck_Rev1.pdf", "v1")
        doc2 = self._drop(project, 1, "Concept Deck_Rev2.pdf", "v2")
        revisions.supersede(doc2, doc1)
        move = ArchiveMove.objects.get(document=doc1)

        self.assertTrue(revisions.undo_archive(move))
        doc1.refresh_from_db()
        doc2.refresh_from_db()
        self.assertTrue(doc1.is_latest)
        self.assertFalse(doc2.is_latest)
        self.assertNotIn("_archive", doc1.file_path)
        self.assertTrue(
            (self.phase_dir(project, 1) / "Concept Deck_Rev1.pdf").exists()
        )
        move.refresh_from_db()
        self.assertTrue(move.undone)

    def test_db_only_mode_never_touches_files(self):
        self.settings_obj.archive_mode = "db_only"
        self.settings_obj.save()
        project = self.seed_project()
        doc1 = self._drop(project, 3, "Test-Report_R1.pdf", "one")
        doc2 = self._drop(project, 3, "Test-Report_R2.pdf", "two")
        revisions.supersede(doc2, doc1)
        self.assertTrue((self.phase_dir(project, 3) / "Test-Report_R1.pdf").exists())
        self.assertEqual(ArchiveMove.objects.count(), 0)
        doc1.refresh_from_db()
        self.assertFalse(doc1.is_latest)

    def test_assign_new_series(self):
        project = self.seed_project()
        doc = self._drop(project, 1, "Site-Survey.pdf", "survey results")
        series = revisions.assign_new_series(doc, "Site Survey Report")
        doc.refresh_from_db()
        self.assertEqual(doc.series, series)
        self.assertEqual(doc.revision_number, 1)
        self.assertTrue(doc.is_latest)
        self.assertEqual(DocumentSeries.objects.count(), 1)

    def test_in_place_replacement_gets_strong_suggestion(self):
        from hub import ingest

        project = self.seed_project()
        pdir = self.phase_dir(project, 2)
        path = pdir / "Package.pdf"
        make_text_pdf(path, "original content")
        ingest.scan_project(project)
        make_text_pdf(path, "updated content")
        _, replaced_docs = ingest.scan_project(project)
        self.assertEqual(len(replaced_docs), 1)
        replaced = replaced_docs[0]
        old = Document.objects.filter(phase=replaced.phase).exclude(pk=replaced.pk).get()
        suggestions = revisions.suggest_predecessors(replaced)
        self.assertEqual(suggestions[0], old)
