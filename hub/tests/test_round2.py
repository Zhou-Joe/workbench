"""Quick capture inbox, dependencies + gantt, palette, .ics export."""

import json
from datetime import date
from unittest.mock import patch

from django.urls import reverse

from hub.models import Capture, Document, ExtractionJob, Milestone
from hub.tests.helpers import WorkspaceTestCase
from hub.worker import Worker

CAPTURE_REPLY = json.dumps(
    {
        "project_slug": "cosmic-coaster",
        "phase_order": 4,
        "confidence": 0.8,
        "tags": ["vendor-correspondence"],
        "rationale": "Vendor commitment belongs in detail design",
    }
)


def capture_chat(settings, messages):
    return CAPTURE_REPLY


class CaptureTests(WorkspaceTestCase):
    def test_capture_suggest_and_file(self):
        project = self.seed_project()  # phases 1-3; suggestion says 4 → miss
        # make a 4th phase so the suggestion resolves
        from hub.models import make_phase

        make_phase(project, "Detail Design and Review", 4)

        resp = self.client.post(reverse("hub:capture"), {"q": "Vendor X promised the weld report by Friday"})
        self.assertEqual(resp.status_code, 200)
        capture_obj = Capture.objects.first()
        self.assertEqual(capture_obj.status, "inbox")
        self.assertTrue(
            ExtractionJob.objects.filter(capture=capture_obj, kind="capture").exists()
        )

        with patch("hub.llm.chat", side_effect=capture_chat):
            Worker().run_pending()
        capture_obj.refresh_from_db()
        self.assertEqual(capture_obj.suggested_phase.order, 4)
        self.assertEqual(
            list(capture_obj.tags.values_list("name", flat=True)),
            ["vendor-correspondence"],
        )

        # File it → markdown note lands in the suggested phase folder
        resp = self.client.post(
            reverse("hub:capture_file", args=[capture_obj.pk]),
            {"phase_id": capture_obj.suggested_phase.pk},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        capture_obj.refresh_from_db()
        self.assertEqual(capture_obj.status, "filed")
        pdir = self.phase_dir(project, 4)
        notes = list(pdir.glob("capture-*.md"))
        self.assertEqual(len(notes), 1)
        self.assertIn("Vendor X promised", notes[0].read_text())
        # flowed into the pipeline as a document
        self.assertTrue(
            Document.objects.filter(filename=notes[0].name).exists()
        )

    def test_capture_skip(self):
        self.seed_project()
        self.client.post(reverse("hub:capture"), {"q": "random thought"})
        capture_obj = Capture.objects.first()
        self.client.post(
            reverse("hub:capture_skip", args=[capture_obj.pk]),
            headers={"HX-Request": "true"},
        )
        capture_obj.refresh_from_db()
        self.assertEqual(capture_obj.status, "skipped")

    def test_markdown_files_extract_as_text(self):
        from hub import extract as ex

        target = self.root / "note.md"
        target.write_text("# Title\n\nBody text here")
        text, tier, note = ex.extract(str(target))
        self.assertEqual(tier, "native")
        self.assertIn("Body text here", text)


class DependencyTests(WorkspaceTestCase):
    def _two_milestones(self):
        project = self.seed_project()
        phase = project.phases.get(order=1)
        first = Milestone.objects.create(
            project=project, phase=phase, date=date(2026, 8, 1),
            title="IFC package issued", mtype="deliverable", status="extracted",
        )
        second = Milestone.objects.create(
            project=project, phase=phase, date=date(2026, 9, 1),
            title="Start commissioning", mtype="gate", status="extracted",
        )
        return project, first, second

    def test_dependency_blocks_until_confirmed(self):
        project, first, second = self._two_milestones()
        self.client.post(
            reverse("hub:milestone_edit", args=[second.pk]),
            {
                "title": second.title,
                "date": "2026-09-01",
                "mtype": "gate",
                "notes": "",
                "depends_on": [str(first.pk)],
            },
        )
        second.refresh_from_db()
        self.assertEqual(list(second.depends_on.values_list("pk", flat=True)), [first.pk])
        self.assertTrue(second.is_blocked)  # dependency still 'extracted'

        self.client.post(
            reverse("hub:milestone_action", args=[first.pk]), {"action": "confirm"}
        )
        second.refresh_from_db()
        self.assertFalse(second.is_blocked)  # dependency now confirmed

    def test_timeline_page_and_ics(self):
        project, first, second = self._two_milestones()
        second.depends_on.set([first])
        resp = self.client.get(reverse("hub:project_timeline", args=[project.slug]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("gantt", html)
        self.assertIn("garrow", html)  # dependency arrow rendered
        self.assertIn("1 milestone blocked", html)

        ics = self.client.get(reverse("hub:project_calendar", args=[project.slug]))
        self.assertEqual(ics.status_code, 200)
        self.assertEqual(ics["Content-Type"], "text/calendar")
        body = ics.content.decode()
        self.assertIn("BEGIN:VCALENDAR", body)
        self.assertIn("SUMMARY:[deliverable] IFC package issued".replace(",", "\\,"), body)
        self.assertIn("DTSTART;VALUE=DATE:20260801", body)


class PaletteTests(WorkspaceTestCase):
    def test_palette_returns_items(self):
        project = self.seed_project()
        resp = self.client.get(reverse("hub:palette"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        labels = " ".join(i["label"] for i in data["items"])
        self.assertIn("Portfolio", labels)
        self.assertIn(project.name, labels)
        self.assertIn(f"{project.name} / 02 Phase 2", labels)


class IaTabsTests(WorkspaceTestCase):
    def test_project_tabs_active_states(self):
        project = self.seed_project()
        ledger = self.client.get(
            reverse("hub:project", args=[project.slug])
        ).content.decode()
        self.assertIn("Ledger", ledger)
        self.assertIn("Decisions", ledger)
        timeline = self.client.get(
            reverse("hub:project_timeline", args=[project.slug])
        ).content.decode()
        self.assertIn("Timeline", timeline)
        phase = self.client.get(
            reverse("hub:phase", args=[project.slug, 1])
        ).content.decode()
        self.assertIn("Phases", phase)

    def test_masthead_shows_inbox_badge(self):
        from hub.models import Capture

        self.seed_project()
        Capture.objects.create(text="pending note")
        page = self.client.get(reverse("hub:home")).content.decode()
        self.assertIn("navbadge", page)
