import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from hub import extract
from hub.tests.helpers import (
    make_docx,
    make_eml,
    make_fake_cad,
    make_pptx,
    make_text_pdf,
    make_xlsx,
)


class ExtractorTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rph_extract_")
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_docx(self):
        path = self.dir / "review.docx"
        make_docx(path, ["Design review held 2026-08-12", "Control system approved"])
        text, tier, note = extract.extract(str(path))
        self.assertEqual(tier, "native")
        self.assertIn("Control system approved", text)

    def test_pptx(self):
        path = self.dir / "concept.pptx"
        make_pptx(path, [("Slide A", "Show concept locked"), ("Slide B", "Capacity 2400 pph")])
        text, tier, note = extract.extract(str(path))
        self.assertEqual(tier, "native")
        self.assertIn("Show concept locked", text)
        self.assertIn("Capacity 2400 pph", text)

    def test_xlsx(self):
        path = self.dir / "status.xlsx"
        make_xlsx(path, [["Item", "Status"], ["Track welds", "complete"]])
        text, tier, note = extract.extract(str(path))
        self.assertEqual(tier, "native")
        self.assertIn("Track welds", text)

    def test_eml(self):
        path = self.dir / "note.eml"
        make_eml(path, "IFC package issued", "Issue for construction Rev C attached.")
        text, tier, note = extract.extract(str(path))
        self.assertEqual(tier, "email")
        self.assertIn("IFC package issued", text)
        self.assertIn("Rev C", text)

    def test_text_pdf_falls_back_to_pypdf(self):
        path = self.dir / "minutes.pdf"
        make_text_pdf(path, "Design review approved on 2026-08-12")
        text, tier, note = extract.extract(str(path), mineru_path="mineru-not-installed")
        self.assertIn("Design review approved", text)
        self.assertEqual(tier, "native")
        self.assertIn("MinerU unavailable", note)

    def test_garbage_pdf_becomes_metadata(self):
        path = self.dir / "scan.pdf"
        path.write_bytes(b"%PDF-1.4 garbage-bytes-not-a-real-pdf")
        text, tier, note = extract.extract(str(path), mineru_path="mineru-not-installed")
        self.assertEqual(tier, "metadata")
        self.assertIn("no machine-readable content", text)

    def test_cad_is_metadata_tier(self):
        path = self.dir / "layout.dwg"
        make_fake_cad(path)
        text, tier, note = extract.extract(str(path))
        self.assertEqual(tier, "metadata")
        self.assertIn("layout.dwg", text)
        self.assertEqual(extract.kind_for_extension(".dwg"), "cad")

    def test_kind_routing(self):
        cases = {
            ".pdf": "pdf",
            ".png": "image",
            ".docx": "office",
            ".eml": "email",
            ".rvt": "cad",
            ".zip": "other",
        }
        for ext, expected in cases.items():
            self.assertEqual(extract.kind_for_extension(ext), expected)
