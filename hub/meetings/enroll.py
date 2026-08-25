"""Enroll a speaker's voiceprint from an existing meeting's audio.

Slices out the utterances diarized under one speaker label, concatenates
them, embeds the combined clip — future meetings then auto-identify this
person by voice.
"""

from __future__ import annotations

import logging

import numpy as np

from hub.meetings.voiceprint import extract_embedding
from hub.models import Meeting, Speaker, Utterance, Voiceprint

logger = logging.getLogger(__name__)
_SR = 16000


def enroll_from_meeting(
    meeting_id: int,
    speaker_label: str,
    speaker_name: str | None = None,
    color: str = "#FF4F00",
) -> dict:
    meeting = Meeting.objects.filter(pk=meeting_id).first()
    if meeting is None or not meeting.audio_path:
        raise ValueError("Meeting or audio not found")

    utterances = list(
        Utterance.objects.filter(
            meeting_id=meeting_id, speaker_label=speaker_label
        ).order_by("seq")
    )
    if not utterances:
        raise ValueError(f"No utterances found for speaker '{speaker_label}'")

    import librosa

    from hub.meetings.audio import resolve_audio_path

    audio, _ = librosa.load(resolve_audio_path(meeting.audio_path), sr=_SR, mono=True)

    slices: list[np.ndarray] = []
    for utt in utterances:
        s = int((utt.start_ts or 0) * _SR)
        e = min(int((utt.end_ts or 0) * _SR), len(audio))
        if e - s >= _SR * 0.3:  # at least 0.3 s
            slices.append(audio[s:e].astype(np.float32))

    if not slices:
        raise ValueError("No audio segments long enough for this speaker")

    combined = np.concatenate(slices)
    logger.info(
        "enroll: extracted %.1fs for '%s' from %d utterances",
        len(combined) / _SR, speaker_label, len(slices),
    )

    emb = extract_embedding(combined)

    name = speaker_name or speaker_label
    spk = Speaker.objects.filter(name=name).first()
    if spk is None:
        spk = Speaker.objects.create(name=name, color=color)

    Voiceprint.objects.create(
        speaker=spk,
        embedding=emb.tobytes(),
        sample_path=f"{meeting.audio_path}#{speaker_label}",
    )
    return {
        "speaker_id": spk.id,
        "speaker_name": spk.name,
        "audio_seconds": round(len(combined) / _SR, 1),
        "segments_used": len(slices),
    }
