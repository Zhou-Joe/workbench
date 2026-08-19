from django.test import TestCase

from hub.models import AppSettings, Milestone, Project, make_phase


class PhaseModelTests(TestCase):
    def test_order_unique_per_project(self):
        project = Project.objects.create(name="A", slug="a")
        make_phase(project, "One", 1)
        make_phase(project, "Two", 2)
        from django.db import IntegrityError, transaction

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                make_phase(project, "Clash", 1)
        self.assertEqual(project.phases.count(), 2)

    def test_folder_name_uses_order_and_slug(self):
        project = Project.objects.create(name="A", slug="a")
        phase = make_phase(project, "Detail Design and Review", 4)
        self.assertEqual(phase.folder_name, "04-detail-design-and-review")

    def test_current_phase_prefers_latest_with_milestones(self):
        project = Project.objects.create(name="A", slug="a")
        p1 = make_phase(project, "One", 1)
        p2 = make_phase(project, "Two", 2)
        p3 = make_phase(project, "Three", 3)
        Milestone.objects.create(project=project, phase=p2, title="hit p2")
        self.assertEqual(project.current_phase(), p2)
        Milestone.objects.create(project=project, phase=p1, title="hit p1 too")
        self.assertEqual(project.current_phase(), p2)
        self.assertNotEqual(project.current_phase(), p3)


class AppSettingsTests(TestCase):
    def test_singleton_always_pk_1(self):
        a = AppSettings.load()
        b = AppSettings.load()
        self.assertEqual(a.pk, 1)
        self.assertEqual(b.pk, 1)
        self.assertEqual(AppSettings.objects.count(), 1)
