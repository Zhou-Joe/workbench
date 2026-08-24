"""Protocol management: named phase templates for project creation."""

from django.db.models import Max
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from ..events import bus
from ..models import Protocol, ProtocolPhase


def protocols(request):
    return render(request, "hub/protocols.html", _context())


def _context():
    return {"protocols": Protocol.objects.prefetch_related("phases")}


def _area(request):
    return render(request, "hub/_protocols_area.html", _context())


@require_POST
def protocol_new(request):
    name = request.POST.get("name", "").strip()
    if name:
        proto = Protocol.objects.create(
            name=name[:200],
            description=request.POST.get("description", "").strip()[:400],
        )
        copy_from = request.POST.get("copy_from", "")
        source = Protocol.objects.filter(pk=copy_from).first() if copy_from else None
        if source:
            for src in source.phases.all():
                ProtocolPhase.objects.create(
                    protocol=proto,
                    name=src.name,
                    order=src.order,
                    extraction_focus=src.extraction_focus,
                )
        bus.publish("protocol")
    return _area(request)


@require_POST
def protocol_default(request, protocol_id):
    proto = get_object_or_404(Protocol, pk=protocol_id)
    proto.is_default = True
    proto.save()  # save() clears is_default on all other protocols
    return _area(request)


@require_POST
def protocol_delete(request, protocol_id):
    proto = get_object_or_404(Protocol, pk=protocol_id)
    if Protocol.objects.count() > 1:
        was_default = proto.is_default
        proto.delete()
        if was_default:
            first = Protocol.objects.first()
            if first:
                first.is_default = True
                first.save()
    return _area(request)


@require_POST
def protocol_phase_add(request, protocol_id):
    proto = get_object_or_404(Protocol, pk=protocol_id)
    name = request.POST.get("name", "").strip()
    if name:
        focus = request.POST.get("extraction_focus", "").strip()
        position = request.POST.get("position", "end")
        existing = list(proto.phases.all())
        if position.startswith("after:"):
            after = int(position.split(":", 1)[1])
            # shift from the highest order down so each move lands in an
            # already-vacated slot (avoids the unique (protocol, order))
            for ph in reversed(existing):
                if ph.order >= after + 1:
                    ph.order += 1
                    ph.save(update_fields=["order"])
            order = after + 1
        else:
            order = len(existing) + 1
        ProtocolPhase.objects.create(
            protocol=proto, name=name[:200], order=order, extraction_focus=focus
        )
        _renumber(proto)
    return _area(request)


@require_POST
def protocol_phase_rename(request, protocol_id, phase_id):
    proto = get_object_or_404(Protocol, pk=protocol_id)
    phase = get_object_or_404(ProtocolPhase, pk=phase_id, protocol=proto)
    name = request.POST.get("name", "").strip()
    if name:
        phase.name = name[:200]
    phase.extraction_focus = request.POST.get("extraction_focus", "").strip()
    phase.save()
    return _area(request)


@require_POST
def protocol_phase_move(request, protocol_id, phase_id):
    proto = get_object_or_404(Protocol, pk=protocol_id)
    phase = get_object_or_404(ProtocolPhase, pk=phase_id, protocol=proto)
    direction = request.POST.get("direction", "up")
    phases = list(proto.phases.all())
    idx = phases.index(phase)
    swap_with = idx - 1 if direction == "up" else idx + 1
    if 0 <= swap_with < len(phases):
        other = phases[swap_with]
        # three-step swap via temp slot (unique (protocol, order) constraint)
        temp = (proto.phases.aggregate(m=Max("order"))["m"] or 0) + 1
        old_phase, old_other = phase.order, other.order
        phase.order = temp
        phase.save(update_fields=["order"])
        other.order = old_phase
        other.save(update_fields=["order"])
        phase.order = old_other
        phase.save(update_fields=["order"])
        _renumber(proto)
    return _area(request)


@require_POST
def protocol_phase_delete(request, protocol_id, phase_id):
    proto = get_object_or_404(Protocol, pk=protocol_id)
    phase = get_object_or_404(ProtocolPhase, pk=phase_id, protocol=proto)
    phase.delete()
    _renumber(proto)
    return _area(request)


def _renumber(proto):
    for i, ph in enumerate(proto.phases.all(), start=1):
        if ph.order != i:
            ph.order = i
            ph.save(update_fields=["order"])
