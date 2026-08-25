from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .. import llm
from ..events import bus
from ..models import AppSettings


def settings_view(request):
    settings = AppSettings.load()
    if request.method == "POST":
        settings.workspace_root = request.POST.get("workspace_root", "").strip()
        settings.lm_base_url = (
            request.POST.get("lm_base_url", "").strip()
            or "http://localhost:1234/v1"
        )
        settings.lm_model = request.POST.get("lm_model", "").strip()
        try:
            settings.lm_temperature = float(
                request.POST.get("lm_temperature", 0.2)
            )
        except ValueError:
            pass
        try:
            settings.lm_max_tokens = int(request.POST.get("lm_max_tokens", 2048))
        except ValueError:
            pass
        settings.mineru_path = request.POST.get("mineru_path", "").strip() or "mineru"
        try:
            settings.mineru_timeout = int(request.POST.get("mineru_timeout", 900))
        except ValueError:
            pass
        settings.archive_mode = request.POST.get("archive_mode", settings.archive_mode)
        settings.watch_enabled = request.POST.get("watch_enabled") == "on"
        if request.POST.get("asr_backend") in ("stub", "funasr_cpu"):
            settings.asr_backend = request.POST["asr_backend"]
        settings.save()
        _restart_watcher(settings)
        messages.success(request, "Settings saved.")
        return redirect("hub:settings")
    ok, detail = _status(settings)
    return render(
        request,
        "hub/settings.html",
        {
            "settings": settings,
            "lm_ok": ok,
            "lm_detail": detail,
            "mineru_ok": _mineru_ok(settings),
        },
    )


def lm_status(request):
    settings = AppSettings.load()
    ok, detail = _status(settings)
    return render(
        request,
        "hub/_lm_status.html",
        {"lm_ok": ok, "lm_detail": detail, "lm_model": settings.lm_model},
    )


def _status(settings):
    try:
        return llm.check_connection(settings)
    except Exception as exc:
        return False, str(exc)


def _mineru_ok(settings):
    from ..extract import mineru_available

    return mineru_available(settings.mineru_path)


def _restart_watcher(settings):
    if not settings.watch_enabled or not settings.expanded_workspace_root():
        from ..watcher import watchers

        watchers.stop()
        return
    from ..watcher import watchers

    watchers.start()
    bus.publish("settings")
