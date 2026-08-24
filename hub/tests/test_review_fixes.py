"""Regression tests for the code-review fixes."""

import os
from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from hub import ingest
from hub.models import Document, ExtractionJob, Milestone, Project, make_phase
from hub.tests.helpers import WorkspaceTestCase, make_docx, make_text_pdf
from hub.worker import Worker


class P0FixesTests(WorkspaceTestCase):
    def test_phase_rename_rewrites_document_paths(self):
        project = self.seed_project()
        pdir = self.phase_dir(project, 1)
        make_docx(pdir / "x.docx", ["content"])
        ingest.scan_project(project)
        self.assertEqual(Document.objects.count(), 1)
        phase = project.phases.get(order=1)

        resp = self.client.post(
            reverse("hub:phase_rename", args=[project.slug, phase.pk]),
            {"name": "Renamed Phase", "extraction_focus": ""},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        doc = Document.objects.get()
        self.assertTrue(doc.file_path.startswith(f"{project.slug}/01-renamed-phase/"))
        # rescan must NOT create duplicates
        new, replaced = ingest.scan_project(project)
        self.assertEqual(len(new), 0)
        self.assertEqual(Document.objects.count(), 1)

    def test_phase_reorder_rewrites_document_paths(self):
        project = self.seed_project()
        make_docx(self.phase_dir(project, 1) / "a.docx", ["a"])
        ingest.scan_project(project)
        ph1 = project.phases.get(order=1)
        self.client.post(
            reverse("hub:phase_move", args=[project.slug, ph1.pk]),
            {"direction": "down"},
            headers={"HX-Request": "true"},
        )
        doc = Document.objects.get()
        self.assertTrue(doc.file_path.startswith(f"{project.slug}/02-phase-1/"))
        new, _ = ingest.scan_project(project)
        self.assertEqual(len(new), 0)
        self.assertEqual(Document.objects.count(), 1)

    def test_duplicate_phase_name_no_500(self):
        project = self.seed_project()
        make_phase(project, "Design", 4)
        resp = self.client.post(
            reverse("hub:phase_add", args=[project.slug]),
            {"name": "Design", "position": "end"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(project.phases.count(), 5)
        slugs = list(project.phases.values_list("slug", flat=True))
        self.assertEqual(len(slugs), len(set(slugs)))  # unique slugs

    def test_garbage_position_falls_back_to_end(self):
        project = self.seed_project()
        resp = self.client.post(
            reverse("hub:phase_add", args=[project.slug]),
            {"name": "Extra", "position": "after:x"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(project.phases.last().name, "Extra")


class SecurityFixesTests(WorkspaceTestCase):
    def test_svg_preview_sandboxed(self):
        project = self.seed_project()
        target = self.phase_dir(project, 1) / "icon.svg"
        target.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>")
        ingest.scan_project(project)
        resp = self.client.get(
            reverse("hub:preview"),
            {"path": f"{project.slug}/01-phase-1/icon.svg"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Security-Policy"], "sandbox")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")

    def test_safe_subpath_separator_boundary(self):
        import pathlib

        from hub import workspace

        base = pathlib.Path(self.root) / "proj" / "01-foo"
        base.mkdir(parents=True)
        sibling = pathlib.Path(self.root) / "proj" / "01-foo-backup"
        sibling.mkdir()
        os.symlink(sibling, base / "escape")
        result = workspace.safe_subpath(base, "escape")
        # must stay inside base, not resolve into the prefix-sibling
        self.assertEqual(result, base.resolve())

    def test_zip_skips_symlinks(self):
        import io
        import zipfile

        project = self.seed_project()
        pdir = self.phase_dir(project, 1)
        secret = self.root / "secret.txt"
        secret.write_text("outside secret")
        os.symlink(secret, pdir / "link.txt")
        make_docx(pdir / "real.docx", ["inside"])
        resp = self.client.get(
            reverse("hub:download_folder"),
            {"project": project.slug, "phase": 1, "path": ""},
        )
        buf = io.BytesIO(b"".join(resp.streaming_content))
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
        self.assertIn("real.docx", names)
        self.assertNotIn("link.txt", names)

    def test_zip_arcnames_sanitized(self):
        import io
        import zipfile

        project = self.seed_project()
        pdir = self.phase_dir(project, 1)
        (pdir / "sub").mkdir()
        make_docx(pdir / "sub" / "f.docx", ["x"])
        resp = self.client.get(
            reverse("hub:download_zip"),
            {"p": [f"{project.slug}/01-phase-1/../01-phase-1/sub/f.docx"]},
        )
        buf = io.BytesIO(b"".join(resp.streaming_content))
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
        self.assertEqual(names, [f"{project.slug}/01-phase-1/sub/f.docx"])
        self.assertNotIn("..", names[0])


class ReliabilityFixesTests(WorkspaceTestCase):
    def test_llm_unavailable_backs_off(self):
        from hub.llm import LLMUnavailable

        project = self.seed_project()
        make_text_pdf(self.phase_dir(project, 1) / "n.pdf", "text")
        ingest.scan_project(project)
        with patch(
            "hub.llm.chat",
            side_effect=LLMUnavailable("LM Studio not reachable"),
        ):
            worker = Worker()
            worker.run_pending()  # attempt 1 → requeued with backoff
        job = ExtractionJob.objects.filter(kind="llm").first()
        self.assertEqual(job.status, "queued")
        self.assertIsNotNone(job.run_after)
        self.assertGreater(job.run_after, timezone.now())
        # run_pending skips gated jobs
        Worker().run_pending()
        job.refresh_from_db()
        self.assertEqual(job.status, "queued")  # untouched while gated

    def test_job_retry_resets_attempts(self):
        project = self.seed_project()
        make_docx(self.phase_dir(project, 1) / "a.docx", ["x"])
        ingest.scan_project(project)
        job = ExtractionJob.objects.first()
        job.status = "failed"
        job.attempts = 3
        job.error = "boom"
        job.save()
        self.client.post(reverse("hub:job_retry", args=[job.pk]))
        job.refresh_from_db()
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.attempts, 0)
        self.assertIsNone(job.run_after)

    def test_llm_retry_does_not_duplicate_milestones(self):
        from hub.tests.test_pipeline import LLM_EXTRACTION_REPLY, fake_chat

        project = self.seed_project()
        make_docx(self.phase_dir(project, 2) / "m.docx", ["approved control system"])
        ingest.scan_project(project)
        doc = Document.objects.get()
        with patch("hub.llm.chat", side_effect=fake_chat):
            Worker().run_pending()
        self.assertEqual(Milestone.objects.count(), 2)
        # simulate a retry of the same llm job (e.g. after partial failure)
        ExtractionJob.objects.create(document=doc, kind="llm")
        with patch("hub.llm.chat", side_effect=fake_chat):
            Worker().run_pending()
        self.assertEqual(Milestone.objects.count(), 2)  # no duplicates

    def test_agent_broken_scope_reports_error(self):
        from hub.agent import _build_tools
        from hub.models import AppSettings

        project = self.seed_project()
        settings = AppSettings.load()
        tools = _build_tools(
            settings, None, lambda d: None, f"{project.slug}/01-phase-1/gone"
        )
        by_name = {t.__name__: t for t in tools}
        out = by_name["search_documents"]("anything")
        self.assertIn("no longer exists", out)
        out = by_name["list_projects_and_phases"]()
        self.assertIn("no longer exists", out)

    def test_checksum_cache_avoids_rehash(self):
        project = self.seed_project()
        target = self.phase_dir(project, 1) / "big.txt"
        target.write_text("x" * 100000)
        ingest.scan_project(project)
        self.assertIn(str(target), ingest._CKSUM_CACHE)
        calls = {"n": 0}
        real_hash = ingest.hashlib.sha256

        class CountingHash:
            def __init__(self, *a):
                calls["n"] += 1
                self._h = real_hash(*a)

            def update(self, c):
                self._h.update(c)

            def hexdigest(self):
                return self._h.hexdigest()

        with patch.object(ingest.hashlib, "sha256", CountingHash):
            new, _ = ingest.scan_project(project)
        self.assertEqual(len(new), 0)
        self.assertEqual(calls["n"], 0)  # cache hit — no rehash
