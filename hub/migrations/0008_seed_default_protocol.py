"""Seed the default Ride Project Protocol (the original six-phase template)."""

from django.db import migrations

RIDE_TEMPLATE = [
    ("Blue Sky", "creative directions explored, show concepts, approvals to advance a direction"),
    ("Concept Design", "concept lock decisions, ride system selections, capacity and throughput targets"),
    ("Feasibility Analysis", "site constraints, budget and schedule findings, go/no-go recommendations"),
    ("Detail Design and Review", "review submissions, comment resolutions, approvals and rejections, IFC dates"),
    ("Installation", "deliveries to site, site milestones, installation completion"),
    ("Testing and Commissioning", "test campaigns, punch lists, certification and sign-offs, readiness reviews"),
]


def seed(apps, schema_editor):
    Protocol = apps.get_model("hub", "Protocol")
    ProtocolPhase = apps.get_model("hub", "ProtocolPhase")
    if Protocol.objects.exists():
        return
    proto = Protocol.objects.create(
        name="Ride Project Protocol",
        description="Six-phase amusement ride development lifecycle",
        is_default=True,
    )
    for order, (name, focus) in enumerate(RIDE_TEMPLATE, start=1):
        ProtocolPhase.objects.create(
            protocol=proto, name=name, order=order, extraction_focus=focus
        )


def unseed(apps, schema_editor):
    Protocol = apps.get_model("hub", "Protocol")
    Protocol.objects.filter(name="Ride Project Protocol").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0007_protocol_project_protocol_protocolphase"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
