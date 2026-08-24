"""Task board: three statuses, editing, time progress, gantt integration."""

from datetime import date, timedelta

from django.urls import reverse

from hub.models import Task
from hub.tests.helpers import WorkspaceTestCase


def _iso(d):
    return d.strftime("%Y-%m-%d")


class TaskBoardTests(WorkspaceTestCase):
    def test_create_move_edit_delete(self):
        project = self.seed_project()
        resp = self.client.post(
            reverse("hub:task_new", args=[project.slug]),
            {
                "title": "Close vendor weld report",
                "status": "planned",
                "start_date": _iso(date.today() - timedelta(days=2)),
                "end_date": _iso(date.today() + timedelta(days=8)),
            },
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        task = Task.objects.get()
        self.assertEqual(task.status, "planned")
        self.assertEqual(task.percent, 20)  # 2 of 10 days elapsed

        # planned → current → done
        self.client.post(
            reverse("hub:task_status", args=[task.pk]),
            {"status": "current"},
            headers={"HX-Request": "true"},
        )
        task.refresh_from_db()
        self.assertEqual(task.status, "current")
        self.assertIsNone(task.completed_at)
        self.client.post(
            reverse("hub:task_status", args=[task.pk]),
            {"status": "done"},
            headers={"HX-Request": "true"},
        )
        task.refresh_from_db()
        self.assertEqual(task.status, "done")
        self.assertIsNotNone(task.completed_at)
        self.assertEqual(task.percent, 100)

        # edit
        self.client.post(
            reverse("hub:task_edit", args=[task.pk]),
            {"title": "Weld report closed", "notes": "final rev received",
             "start_date": _iso(date.today() - timedelta(days=5)),
             "end_date": _iso(date.today())},
            headers={"HX-Request": "true"},
        )
        task.refresh_from_db()
        self.assertEqual(task.title, "Weld report closed")

        # delete
        self.client.post(
            reverse("hub:task_delete", args=[task.pk]),
            headers={"HX-Request": "true"},
        )
        self.assertFalse(Task.objects.exists())

    def test_timeline_page_shows_three_columns(self):
        project = self.seed_project()
        Task.objects.create(project=project, title="A", status="planned")
        Task.objects.create(project=project, title="B", status="current")
        Task.objects.create(project=project, title="C", status="done")
        page = self.client.get(
            reverse("hub:project_timeline", args=[project.slug])
        )
        html = page.content.decode()
        self.assertIn("Planned", html)
        self.assertIn("In progress", html)
        self.assertIn("Done", html)
        self.assertIn("A", html)
        self.assertIn("B", html)
        self.assertIn("C", html)
        # the ledger page stays a pure extracted-record view
        ledger = self.client.get(reverse("hub:project", args=[project.slug]))
        self.assertNotIn("taskcols", ledger.content.decode())

    def test_overdue_detection(self):
        project = self.seed_project()
        late = Task.objects.create(
            project=project, title="Late", status="current",
            start_date=date.today() - timedelta(days=10),
            end_date=date.today() - timedelta(days=2),
        )
        self.assertTrue(late.overdue)
        self.assertEqual(late.percent, 100)  # capped

    def test_gantt_renders_task_bars_and_today_line(self):
        project = self.seed_project()
        Task.objects.create(
            project=project, title="Install track", status="current",
            start_date=date.today() - timedelta(days=3),
            end_date=date.today() + timedelta(days=3),
        )
        resp = self.client.get(reverse("hub:project_timeline", args=[project.slug]))
        html = resp.content.decode()
        self.assertIn('class="gtask gtask-current"', html)
        self.assertIn("Install track", html)
        self.assertIn("gtoday", html)  # today falls inside the range
        # gantt is a live region (auto-refresh after task edits)
        self.assertIn('id="gantt-region"', html)
        self.assertIn("hx-get=", html)

    def test_task_actions_carry_refresh_trigger(self):
        project = self.seed_project()
        task = Task.objects.create(project=project, title="T")
        resp = self.client.post(
            reverse("hub:task_status", args=[task.pk]),
            {"status": "done"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp["HX-Trigger"], "rph:tick")
