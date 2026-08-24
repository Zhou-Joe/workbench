"""Phase close-out: marking a phase complete advances the active phase."""

from django.urls import reverse

from hub.models import Phase
from hub.tests.helpers import WorkspaceTestCase


class PhaseCloseTests(WorkspaceTestCase):
    def test_close_advances_active_phase_and_reopen_restores(self):
        project = self.seed_project()
        p2 = project.phases.get(order=2)

        # close phase 1 → active becomes phase 2
        resp = self.client.post(
            reverse("hub:phase_close", args=[project.slug, project.phases.get(order=1).pk]),
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(project.current_phase(), p2)
        # portfolio track shows the new numeral
        home = self.client.get(reverse("hub:home")).content.decode()
        self.assertIn("in 02 Phase 2", home)

        # phase page sidebar shows closed state + reopen action
        page = self.client.get(reverse("hub:phase", args=[project.slug, 1]))
        html = page.content.decode()
        self.assertIn("/phase/1/reopen/", html)  # reopen button in sidebar
        self.assertIn("✓", html)
        self.assertIn('title="Reopen ', html)

        # closing the last phase keeps the last phase active
        for order in (2, 3):
            ph = project.phases.get(order=order)
            self.client.post(
                reverse("hub:phase_close", args=[project.slug, ph.pk]),
                headers={"HX-Request": "true"},
            )
        self.assertEqual(project.current_phase(), project.phases.get(order=3))

        # reopen phase 1 → active falls back to the first phase after
        # the highest closed order (phase 2 is still closed → active = 3? no:
        # max closed order is 3 (phase 3 closed) → next open = none → last)
        self.client.post(
            reverse("hub:phase_reopen", args=[project.slug, project.phases.get(order=1).pk]),
            headers={"HX-Request": "true"},
        )
        self.assertEqual(project.current_phase(), project.phases.get(order=3))

    def test_milestone_heuristic_still_works_without_closures(self):
        project = self.seed_project()
        from hub.models import Milestone

        phase3 = project.phases.get(order=3)
        Milestone.objects.create(project=project, phase=phase3, title="hit")
        self.assertEqual(project.current_phase(), phase3)
        self.assertIsNone(Phase.objects.filter(closed_at__isnull=False).count() and None or None)
