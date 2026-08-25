"""ASR backends for live meeting transcription.

Ported from the proven MeetingAssistant implementation. Two backends:

- ``stub`` — fake bilingual transcript driving the full pipeline with no
  models (tests, and UI work without a model download).
- ``funasr_cpu`` — in-process SenseVoice-Small + FSMN-VAD on CPU.

Strategy (funasr_cpu): SenseVoice is non-streaming (whole-utterance), so we
buffer PCM and use FSMN-VAD to detect speech-segment boundaries. Each closed
segment is transcribed as a final utterance. No partials. Stepped silence
tolerance: lenient (1000 ms) for natural speech, aggressive (600 ms) once a
segment grows past 20 s, hard force-flush at 30 s so a monologue shows live.
"""

from __future__ import annotations

import asyncio
import logging
import re
import struct
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Optional

logger = logging.getLogger(__name__)

_SR = 16000


@dataclass
class AsrResult:
    """One ASR emission — partial or final."""

    text: str
    is_final: bool
    lang: str = "unknown"  # en | zh | mixed | unknown
    start_ts: Optional[float] = None  # seconds from session start
    end_ts: Optional[float] = None


# ---------------------------------------------------------------------------
# Language detection — heuristic, good enough to route translation.
# ---------------------------------------------------------------------------

_CJK = set(range(0x4E00, 0x9FFF + 1)) | set(range(0x3400, 0x4DBF + 1))


def detect_lang(text: str) -> Literal["en", "zh", "mixed", "unknown"]:
    if not text:
        return "unknown"
    has_cjk = any(ord(ch) in _CJK for ch in text)
    has_latin = any(ch.isalpha() and ch.isascii() for ch in text)
    if has_cjk and has_latin:
        return "mixed"
    if has_cjk:
        return "zh"
    if has_latin:
        return "en"
    return "unknown"


# SenseVoice prefixes output with tags like <|zh|><|NEUTRAL|><|Speech|><|withitn|>
_TAG_RE = re.compile(r"<\|[^|]*\|>")


def clean_sensevoice_text(text: str) -> str:
    return _TAG_RE.sub("", text).strip()


# ---------------------------------------------------------------------------
# Stub backend — canned bilingual transcript, one word per fed chunk.
# ---------------------------------------------------------------------------

_STUB_SCRIPT: list[tuple[str, str]] = [
    ("zh", "大家好，我们开始今天的会议"),
    ("en", "Let's get started with the quarterly review"),
    ("zh", "首先看一下上季度的营收数据"),
    ("en", "Revenue is up fifteen percent year over year"),
    ("zh", "这个增长主要来自海外市场"),
    ("en", "Any questions before we move on?"),
    ("zh", "好的，那我们继续讨论下半年的计划"),
]


@dataclass
class _StubSession:
    start_time: float = field(default_factory=time.monotonic)
    finished: bool = False
    word_idx: int = 0
    utterance_idx: int = 0


class StubAsrClient:
    name = "stub"

    def __init__(self) -> None:
        self._sessions: dict[str, _StubSession] = {}

    async def start_session(self) -> str:
        sid = f"stub-{int(time.time() * 1000)}"
        self._sessions[sid] = _StubSession()
        return sid

    async def feed(self, session_id: str, audio: bytes) -> AsyncIterator[AsrResult]:
        session = self._sessions.get(session_id)
        if session is None or session.finished:
            return
        lang, full_text = _STUB_SCRIPT[session.utterance_idx % len(_STUB_SCRIPT)]
        words = full_text.split()
        if session.word_idx < len(words):
            current = words[: session.word_idx + 1]
            session.word_idx += 1
            elapsed = time.monotonic() - session.start_time
            yield AsrResult(
                text=" ".join(current), is_final=False, lang=lang,
                start_ts=elapsed, end_ts=elapsed,
            )
        else:
            elapsed = time.monotonic() - session.start_time
            yield AsrResult(
                text=full_text, is_final=True, lang=lang,
                start_ts=max(0.0, elapsed - 1.5), end_ts=elapsed,
            )
            session.word_idx = 0
            session.utterance_idx += 1

    async def flush_pending(self, session_id: str) -> AsyncIterator[AsrResult]:
        return
        yield  # nothing buffered in the stub

    async def end_session(self, session_id: str) -> AsyncIterator[AsrResult]:
        session = self._sessions.get(session_id)
        if session is not None:
            session.finished = True
        return
        yield

    async def close(self) -> None:
        self._sessions.clear()


# ---------------------------------------------------------------------------
# In-process funasr (CPU) backend.
# ---------------------------------------------------------------------------

@dataclass
class _FunasrCpuSession:
    buffer: list = field(default_factory=list)  # int16 samples
    unprocessed: int = 0
    # Absolute ms offset of buffer[0] from session start; grows as emitted
    # audio is trimmed from the front of the buffer.
    buffer_offset_ms: int = 0
    finished: bool = False


class FunasrCpuClient:
    name = "funasr_cpu"

    # Run VAD after this much new audio arrives.
    _VAD_CHECK_SEC = 2.0
    # Stepped VAD cutoff — see module docstring.
    _VAD_TIER1_SEC = 20.0
    _VAD_TIER1_SILENCE_MS = 1000
    _VAD_TIER2_SILENCE_MS = 600
    _VAD_TIER2_SEC = 30.0

    def __init__(self) -> None:
        self._sessions: dict[str, _FunasrCpuSession] = {}

    async def start_session(self) -> str:
        sid = f"cpufunasr-{int(time.time() * 1000)}"
        self._sessions[sid] = _FunasrCpuSession()
        return sid

    async def feed(self, session_id: str, audio: bytes) -> AsyncIterator[AsrResult]:
        session = self._sessions.get(session_id)
        if session is None or session.finished:
            return

        new_samples = struct.unpack(f"<{len(audio) // 2}h", audio)
        session.buffer.extend(new_samples)
        session.unprocessed += len(new_samples)

        if session.unprocessed < self._VAD_CHECK_SEC * _SR:
            return
        session.unprocessed = 0

        import numpy as np

        samples = np.asarray(session.buffer, dtype=np.float32) / 32768.0
        silence_ms = self._VAD_TIER1_SILENCE_MS
        vad_segments = await self._run_vad(samples, silence_ms=silence_ms)

        # If the still-growing tail segment has passed tier 1, re-run with the
        # aggressive tolerance; past the tier-2 hard cap, force-flush it.
        force_flush_tail = False
        if vad_segments:
            last_start_ms, _ = vad_segments[-1]
            cur_len_sec = (len(session.buffer) / _SR) - (last_start_ms / 1000.0)
            if cur_len_sec > self._VAD_TIER1_SEC:
                silence_ms = self._VAD_TIER2_SILENCE_MS
                vad_segments = await self._run_vad(samples, silence_ms=silence_ms)
                if len(vad_segments) == 1:
                    last_start_ms2, _ = vad_segments[-1]
                    cur_len_sec2 = (len(session.buffer) / _SR) - (last_start_ms2 / 1000.0)
                    if cur_len_sec2 > self._VAD_TIER2_SEC:
                        force_flush_tail = True

        if not vad_segments:
            return

        # The last segment is final when enough trailing silence has passed
        # (its end sits well before the buffer edge); otherwise it is still
        # growing and only earlier segments are emitted.
        buffer_end_ms = len(session.buffer) / _SR * 1000.0
        tail_end_ms = vad_segments[-1][1]
        tail_closed = (buffer_end_ms - tail_end_ms) >= silence_ms

        to_emit: list[tuple[int, int]] = []
        if force_flush_tail or tail_closed:
            to_emit = list(vad_segments)
        elif len(vad_segments) > 1:
            to_emit = vad_segments[:-1]

        for start_ms, end_ms in to_emit:
            seg = self._slice(samples, start_ms, end_ms)
            if len(seg) < 1600:  # < 0.1 s
                continue
            abs_start = start_ms + session.buffer_offset_ms
            abs_end = end_ms + session.buffer_offset_ms
            yield await self._transcribe(seg, abs_start, abs_end)

        # Trim emitted audio so the next VAD run doesn't re-transcribe it.
        if to_emit:
            if to_emit[-1] == vad_segments[-1]:
                session.buffer_offset_ms += int(len(session.buffer) / _SR * 1000)
                session.buffer.clear()
            else:
                keep_from_ms = vad_segments[-1][0]
                keep_from_sample = int(keep_from_ms / 1000 * _SR)
                if 0 < keep_from_sample < len(session.buffer):
                    session.buffer = session.buffer[keep_from_sample:]
                    session.buffer_offset_ms += keep_from_ms

    async def _run_vad(self, samples, silence_ms: int) -> list[tuple[int, int]]:
        """FSMN-VAD → [(start_ms, end_ms)]; silence_ms closes a segment."""

        def _infer():
            from hub.meetings import funasr_models

            res = funasr_models.ensure_vad().generate(
                input=samples,
                cache={},
                batch_size=1,
                threshold=0.85,
                max_end_silence_time=silence_ms,
                speech_to_sil_time=200,
            )
            return res[0].get("value", []) if res else []

        try:
            return await asyncio.to_thread(_infer)
        except Exception as e:
            logger.warning("VAD error: %s", e)
            return []

    def _slice(self, samples, start_ms: int, end_ms: int):
        s = int(start_ms / 1000 * _SR)
        e = int(end_ms / 1000 * _SR)
        return samples[s:e]

    async def _transcribe(self, seg_samples, start_ms: int, end_ms: int) -> AsrResult:
        def _infer():
            from hub.meetings import funasr_models

            return funasr_models.ensure_asr().generate(
                input=seg_samples, cache={}, language="auto", use_itn=True
            )

        try:
            result = await asyncio.to_thread(_infer)
        except Exception as e:
            logger.warning("SenseVoice inference error: %s", e)
            return AsrResult(text="", is_final=True, lang="unknown")

        text = ""
        if result:
            raw = result[0].get("text") or ""
            text = clean_sensevoice_text(raw)

        return AsrResult(
            text=text,
            is_final=True,
            lang=detect_lang(text),
            start_ts=start_ms / 1000.0,
            end_ts=end_ms / 1000.0,
        )

    async def flush_pending(self, session_id: str) -> AsyncIterator[AsrResult]:
        """Force-emit the growing segment (speaker paused / stopped talking).

        Without this the last utterance of a meeting is stuck in the buffer
        until someone speaks again or the user hits Stop.
        """
        session = self._sessions.get(session_id)
        if session is None or session.finished:
            return
        if len(session.buffer) < 1600:
            return

        import numpy as np

        samples = np.asarray(session.buffer, dtype=np.float32) / 32768.0
        vad_segments = await self._run_vad(samples, self._VAD_TIER1_SILENCE_MS)
        if not vad_segments:
            vad_segments = [(0, int(len(session.buffer) / _SR * 1000))]

        for start_ms, end_ms in vad_segments:
            seg = self._slice(samples, start_ms, end_ms)
            if len(seg) < 1600:
                continue
            abs_start = start_ms + session.buffer_offset_ms
            abs_end = end_ms + session.buffer_offset_ms
            yield await self._transcribe(seg, abs_start, abs_end)

        session.buffer_offset_ms += int(len(samples) / _SR * 1000)
        session.buffer.clear()

    async def end_session(self, session_id: str) -> AsyncIterator[AsrResult]:
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.finished = True

        import numpy as np

        samples = np.asarray(session.buffer, dtype=np.float32) / 32768.0
        if len(samples) > 1600:
            vad_segments = await self._run_vad(samples, self._VAD_TIER1_SILENCE_MS)
            for start_ms, end_ms in vad_segments:
                seg = self._slice(samples, start_ms, end_ms)
                if len(seg) < 1600:
                    continue
                abs_start = start_ms + session.buffer_offset_ms
                abs_end = end_ms + session.buffer_offset_ms
                yield await self._transcribe(seg, abs_start, abs_end)
        return
        yield

    async def close(self) -> None:
        self._sessions.clear()


# ---------------------------------------------------------------------------
# Singleton accessor — backend chosen per AppSettings.asr_backend; rebuilt
# when the setting changes (each WS connection gets its own session id).
# ---------------------------------------------------------------------------

_client = None
_client_backend: Optional[str] = None


def get_asr_client():
    global _client, _client_backend
    from hub.models import AppSettings

    backend = AppSettings.load().asr_backend
    if _client is None or _client_backend != backend:
        if backend == "funasr_cpu":
            _client = FunasrCpuClient()
        else:
            _client = StubAsrClient()
        _client_backend = backend
    return _client
