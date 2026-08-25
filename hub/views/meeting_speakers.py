"""Speakers and voiceprint enrollment."""

from django.shortcuts import render
from django.views.decorators.http import require_POST

from ..models import Speaker


def speakers(request):
    return render(request, "hub/speakers.html", _speakers_context())


def _speakers_context():
    return {
        "speakers": list(
            Speaker.objects.prefetch_related("voiceprints")
        ),
    }


@require_POST
def speaker_create(request):
    name = request.POST.get("name", "").strip()
    if name:
        Speaker.objects.create(name=name[:120], color=request.POST.get("color", "#FF4F00"))
    return render(request, "hub/speakers.html", _speakers_context())


@require_POST
def speaker_delete(request, speaker_id):
    Speaker.objects.filter(pk=speaker_id).delete()
    return render(request, "hub/speakers.html", _speakers_context())


@require_POST
def speaker_enroll(request, speaker_id):
    """Enroll a voiceprint from an uploaded audio clip (any librosa format,
    ≥ 0.3 s)."""
    error = ""
    upload = request.FILES.get("clip")
    if upload is None:
        error = "No audio file uploaded."
    else:
        import io

        try:
            import librosa

            data = upload.read()
            samples, _ = librosa.load(io.BytesIO(data), sr=16000, mono=True)
            samples = samples.astype("float32")
            if len(samples) < 16000 * 0.3:
                raise ValueError("clip too short — need at least 0.3 s")
            from hub.meetings.voiceprint import enroll_speaker

            enroll_speaker(speaker_id, samples, sample_path=upload.name)
        except Exception as e:
            error = str(e)
    ctx = _speakers_context()
    ctx["action_error"] = error
    return render(request, "hub/speakers.html", ctx)
