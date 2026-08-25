"""Reprocess a meeting's full audio — global re-segmentation + re-transcription.

Live VAD runs incrementally on a growing buffer, which can produce suboptimal
boundaries. Reprocessing runs VAD on the complete audio in one pass (cleaner
boundaries, better timestamps), re-transcribes each segment, and replaces
the meeting's utterances. Optionally re-runs diarization.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from hub.meetings.asr import clean_sensevoice_text, detect_lang
from hub.models import Meeting, Utterance

logger = logging.getLogger(__name__)
_SR = 16000


@dataclass
class ReprocessResult:
    meeting_id: int
    segments_found: int
    utterances_created: int
    speakers_found: list[str] = field(default_factory=list)


def reprocess_meeting(meeting_id: int, do_diarize: bool = True) -> ReprocessResult:
    from hub.meetings import funasr_models
    from hub.meetings.audio import resolve_audio_path

    meeting = Meeting.objects.filter(pk=meeting_id).first()
    if meeting is None:
        raise ValueError(f"meeting {meeting_id} not found")
    if not meeting.audio_path:
        raise ValueError("no audio saved for this meeting")
    audio_path = str(resolve_audio_path(meeting.audio_path))

    import librosa

    samples, _ = librosa.load(audio_path, sr=_SR, mono=True)
    samples = samples.astype(np.float32)
    logger.info("reprocess: loaded %.1fs from %s", len(samples) / _SR, audio_path)

    # Global VAD on the complete audio: more sensitive than live (full view),
    # 0.6 s pause closes a segment.
    def _vad():
        res = funasr_models.ensure_vad().generate(
            input=samples,
            cache={},
            batch_size=1,
            threshold=0.7,
            max_end_silence_time=600,
            speech_to_sil_time=200,
        )
        return res[0].get("value", []) if res else []

    vad_segments: list[tuple[int, int]] = _vad()
    logger.info("reprocess: VAD found %d segments", len(vad_segments))

    def _asr(seg):
        res = funasr_models.ensure_asr().generate(
            input=seg, cache={}, language="auto", use_itn=True
        )
        return res[0].get("text", "") if res else ""

    new_utterances: list[dict] = []
    for start_ms, end_ms in vad_segments:
        seg = samples[int(start_ms / 1000 * _SR) : int(end_ms / 1000 * _SR)]
        if len(seg) < _SR * 0.3:
            continue
        text = clean_sensevoice_text(_asr(seg))
        if not text:
            continue
        new_utterances.append({
            "seq": len(new_utterances) + 1,
            "start_ts": start_ms / 1000.0,
            "end_ts": end_ms / 1000.0,
            "text": text,
            "lang": detect_lang(text),
        })
    logger.info("reprocess: transcribed %d utterances", len(new_utterances))

    Utterance.objects.filter(meeting_id=meeting_id).delete()
    Utterance.objects.bulk_create([
        Utterance(
            meeting_id=meeting_id,
            seq=u["seq"],
            start_ts=u["start_ts"],
            end_ts=u["end_ts"],
            text=u["text"],
            lang=u["lang"],
        )
        for u in new_utterances
    ])

    speakers_found: list[str] = []
    if do_diarize:
        logger.info("reprocess: running diarization…")
        try:
            from hub.meetings.diarizer import diarize_meeting

            diarize_meeting(meeting_id, audio_path)
            speakers_found = sorted(
                Utterance.objects.filter(meeting_id=meeting_id)
                .exclude(speaker_label="")
                .values_list("speaker_label", flat=True)
                .distinct()
            )
        except Exception as e:
            logger.warning("reprocess: diarization failed: %s", e)

    return ReprocessResult(
        meeting_id=meeting_id,
        segments_found=len(vad_segments),
        utterances_created=len(new_utterances),
        speakers_found=speakers_found,
    )
