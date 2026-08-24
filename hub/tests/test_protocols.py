"""Protocol templates: management + project creation with a chosen protocol."""

from django.urls import reverse

from hub.models import Project, Protocol, ProtocolPhase
from hub.tests.helpers import WorkspaceTestCase


class ProtocolTests(WorkspaceTestCase):
    def test_default_protocol_seeded(self):
        proto = Protocol.objects.get(is_default=True)
        self.assertEqual(proto.name, "Ride Project Protocol")
        self.assertEqual(proto.phases.count(), 6)
        self.assertEqual(proto.phases.first().name, "Blue Sky")

    def test_create_project_uses_selected_protocol(self):
        show = Protocol.objects.create(name="Show Development")
        for order, name in enumerate(["Ideation", "Design", "Fabrication"], 1):
            ProtocolPhase.objects.create(protocol=show, name=name, order=order)

        resp = self.client.post(
            reverse("hub:project_create"),
            {"name": "Night Parade Float", "protocol": str(show.pk)},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        project = Project.objects.get(slug="night-parade-float")
        self.assertEqual(project.protocol, show)
        self.assertEqual(
            list(project.phases.values_list("name", flat=True)),
            ["Ideation", "Design", "Fabrication"],
        )

    def test_create_project_defaults_to_default_protocol(self):
        self.client.post(reverse("hub:project_create"), {"name": "Standard Ride"})
        project = Project.objects.get(slug="standard-ride")
        self.assertEqual(project.protocol.name, "Ride Project Protocol")
        self.assertEqual(project.phases.count(), 6)

    def test_protocol_management_flow(self):
        # create a copy of the default
        default = Protocol.objects.get(is_default=True)
        self.client.post(
            reverse("hub:protocol_new"),
            {"name": "Mini Attraction", "copy_from": str(default.pk)},
            headers={"HX-Request": "true"},
        )
        mini = Protocol.objects.get(name="Mini Attraction")
        self.assertEqual(mini.phases.count(), 6)

        # add a phase between 1 and 2
        self.client.post(
            reverse("hub:protocol_phase_add", args=[mini.pk]),
            {"name": "Permitting", "position": "after:1"},
            headers={"HX-Request": "true"},
        )
        names = list(mini.phases.values_list("name", flat=True))
        self.assertEqual(names[1], "Permitting")
        self.assertEqual(len(names), 7)

        # move it down
        permitting = mini.phases.get(order=2)
        self.client.post(
            reverse("hub:protocol_phase_move", args=[mini.pk, permitting.pk]),
            {"direction": "down"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(
            list(mini.phases.values_list("name", flat=True))[2], "Permitting"
        )

        # rename
        self.client.post(
            reverse("hub:protocol_phase_rename", args=[mini.pk, permitting.pk]),
            {"name": "Permits & Approvals", "extraction_focus": ""},
            headers={"HX-Request": "true"},
        )
        permitting.refresh_from_db()
        self.assertEqual(permitting.name, "Permits & Approvals")

        # delete the phase
        self.client.post(
            reverse("hub:protocol_phase_delete", args=[mini.pk, permitting.pk]),
            headers={"HX-Request": "true"},
        )
        self.assertEqual(mini.phases.count(), 6)

        # set as default, then delete — default falls back
        self.client.post(
            reverse("hub:protocol_default", args=[mini.pk]),
            headers={"HX-Request": "true"},
        )
        mini.refresh_from_db()
        self.assertTrue(mini.is_default)
        self.client.post(
            reverse("hub:protocol_delete", args=[mini.pk]),
            headers={"HX-Request": "true"},
        )
        self.assertTrue(Protocol.objects.get(is_default=True).name.startswith("Ride"))

    def test_editing_protocol_does_not_touch_existing_projects(self):
        default = Protocol.objects.get(is_default=True)
        self.client.post(reverse("hub:project_create"), {"name": "Frozen Ride"})
        project = Project.objects.get(slug="frozen-ride")
        phase = default.phases.first()
        self.client.post(
            reverse("hub:protocol_phase_rename", args=[default.pk, phase.pk]),
            {"name": "Renamed In Protocol", "extraction_focus": ""},
            headers={"HX-Request": "true"},
        )
        project.refresh_from_db()
        self.assertEqual(project.phases.first().name, "Blue Sky")
