"""Ask your project documents a question — answers cite source files."""

from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .. import workspace
from ..events import bus
from ..models import AppSettings, ExtractionJob, Phase, Project, Question


def ask(request):
    if request.method == "POST":
        text = request.POST.get("q", "").strip()
        if text:
            project = None
            project_id = request.POST.get("project", "")
            if project_id:
                project = Project.objects.filter(pk=project_id).first()
            question = Question.objects.create(question=text, project=project)
            ExtractionJob.objects.create(
                question=question, kind=ExtractionJob.Kind.ASK
            )
            bus.publish("ask", question_id=question.pk)
        return _ask_area(request)
    return render(
        request,
        "hub/ask.html",
        {"questions": _recent(), "projects": Project.objects.order_by("name")},
    )


@require_POST
def ask_folder(request, project_slug, order):
    """Ask from inside a browsed folder — the question is scoped to it."""
    phase = get_object_or_404(Phase, project__slug=project_slug, order=order)
    text = request.POST.get("q", "").strip()
    folder_path = _current_folder_path(request, phase)
    if text:
        question = Question.objects.create(
            question=text, project=phase.project, folder_path=folder_path
        )
        ExtractionJob.objects.create(
            question=question, kind=ExtractionJob.Kind.ASK
        )
        bus.publish("ask", question_id=question.pk)
    return _folder_ask_area(phase, folder_path)


def _current_folder_path(request, phase):
    """Validated workspace-relative path of the folder being browsed."""
    from pathlib import Path

    try:
        settings = AppSettings.load()
        current = (request.POST.get("path", "") or request.GET.get("path", "")).strip()
        base = workspace.phase_dir(settings, phase.project, phase).resolve()
        folder = workspace.safe_subpath(base, current)
        ws_root = Path(settings.expanded_workspace_root()).resolve()
        return folder.relative_to(ws_root).as_posix()
    except (RuntimeError, ValueError, OSError):
        return ""


def _folder_ask_area(phase, folder_path):
    questions = list(
        Question.objects.filter(project=phase.project, folder_path=folder_path)[:3]
    )
    current = ""
    if folder_path:
        prefix = f"{phase.project.slug}/{phase.folder_name}/"
        current = (
            folder_path[len(prefix):] if folder_path.startswith(prefix) else ""
        )
    return render(
        request,
        "hub/_ask_folder.html",
        {
            "project": phase.project,
            "phase": phase,
            "current": current,
            "folder_questions": questions,
        },
    )


@require_POST
def ask_clear(request):
    Question.objects.all().delete()
    return _ask_area(request)


def _recent():
    return Question.objects.select_related("project").order_by("-created_at")[:8]


def _ask_area(request):
    return render(
        request,
        "hub/_ask_area.html",
        {"questions": _recent(), "projects": Project.objects.order_by("name")},
    )
