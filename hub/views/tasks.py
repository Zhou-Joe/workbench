"""User task board on the project page: planned / current / done."""

from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..events import bus
from ..models import Project, Task
from ..worker import parse_date


def tasks_context(project):
    tasks = list(project.tasks.all())
    return {
        "project": project,
        "planned": [t for t in tasks if t.status == Task.Status.PLANNED],
        "current": [t for t in tasks if t.status == Task.Status.CURRENT],
        "done": [t for t in tasks if t.status == Task.Status.DONE],
    }


def _panel(request, project):
    return render(request, "hub/_tasks_panel.html", tasks_context(project))


def task_panel(request, slug):
    project = get_object_or_404(Project, slug=slug)
    return _panel(request, project)


def task_new(request, slug):
    project = get_object_or_404(Project, slug=slug)
    title = request.POST.get("title", "").strip()
    if title:
        Task.objects.create(
            project=project,
            title=title[:300],
            notes=request.POST.get("notes", "").strip(),
            status=_valid_status(request.POST.get("status")),
            start_date=parse_date(request.POST.get("start_date", "")),
            end_date=parse_date(request.POST.get("end_date", "")),
        )
        bus.publish("task", project_id=project.pk)
    return _panel(request, project)


@require_POST
def task_status(request, task_id):
    task = get_object_or_404(Task, pk=task_id)
    task.status = _valid_status(request.POST.get("status"))
    if task.status == Task.Status.DONE:
        task.completed_at = timezone.now()
    else:
        task.completed_at = None
    task.save(update_fields=["status", "completed_at", "updated_at"])
    bus.publish("task", project_id=task.project_id)
    return _panel(request, task.project)


@require_POST
def task_edit(request, task_id):
    task = get_object_or_404(Task, pk=task_id)
    title = request.POST.get("title", "").strip()
    if title:
        task.title = title[:300]
    task.notes = request.POST.get("notes", "").strip()
    task.start_date = parse_date(request.POST.get("start_date", ""))
    task.end_date = parse_date(request.POST.get("end_date", ""))
    task.save()
    bus.publish("task", project_id=task.project_id)
    return _panel(request, task.project)


@require_POST
def task_delete(request, task_id):
    task = get_object_or_404(Task, pk=task_id)
    project = task.project
    task.delete()
    bus.publish("task", project_id=project.pk)
    return _panel(request, project)


def _valid_status(value):
    values = {c.value for c in Task.Status}
    return value if value in values else Task.Status.PLANNED
