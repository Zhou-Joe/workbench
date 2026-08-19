"""Ask your project documents a question — answers cite source files."""

from django.shortcuts import render
from django.views.decorators.http import require_POST

from ..events import bus
from ..models import ExtractionJob, Project, Question


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
