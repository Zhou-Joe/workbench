"""Meeting WAV storage — one 16 kHz mono file per meeting under var/meetings/audio/.

`Meeting.audio_path` stores the bare file name (e.g. ``meeting-42.wav``);
everything resolves through here.
"""

from __future__ import annotations

import wave
from pathlib import Path


def audio_dir() -> Path:
    from django.conf import settings

    path = Path(settings.BASE_DIR) / "var" / "meetings" / "audio"
    path.mkdir(parents=True, exist_ok=True)
    return path


def audio_file_name(meeting_id: int) -> str:
    return f"meeting-{meeting_id}.wav"


def resolve_audio_path(stored: str) -> Path:
    """Absolute path for the value stored in Meeting.audio_path."""
    return audio_dir() / Path(stored).name


def write_wav(path: Path, pcm_samples, sample_rate: int = 16000) -> None:
    """Write accumulated int16 samples to a mono WAV."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_samples.tobytes())
