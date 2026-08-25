"""Channels consumer for live meeting transcription.

Protocol (ported verbatim from the proven MeetingAssistant implementation):

- Client → server: binary frames of little-endian int16 mono 16 kHz PCM;
  text frames as control JSON: {"type": "translate", "enabled": true|false}.
- Server → client JSON:
    {"type": "ready", "meeting_id": 1, "title": "..."}
    {"type": "partial", "text": "...", "lang": "zh", "start_ts": 1.2}
    {"type": "final", "utterance_id": 42, "text": "...", "lang": "zh",
     "translation": null, "start_ts": 1.2, "end_ts": 4.5}
    {"type": "translation", "utterance_id": 42, "translation": "..."}
    {"type": "error", "message": "..."}

Query params: ?title=&series_id= to start a meeting, or ?meeting_id= to
resume one. A 1.5 s inactivity watchdog flushes the ASR buffer so the last
sentence of any pause shows up live.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from array import array
from datetime import datetime
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from hub.meetings.asr import AsrResult, get_asr_client
from hub.meetings.audio import audio_file_name, write_wav
from hub.models import Meeting, Utterance

logger = logging.getLogger(__name__)

_INACTIVITY_FLUSH_SEC = 1.5
_WATCHDOG_TICK_SEC = 0.5


def _title_suffix(frequency: str | None) -> str:
    """Auto title suffix matched to the series' recurrence.

    weekly → W34 (ISO week) · biweekly → B17 (half-period) ·
    monthly → 2026-08 · anything else → 08-25 (plain date).
    """
    from django.utils import timezone

    now = timezone.localtime()
    if frequency == "weekly":
        return f"W{now.isocalendar()[1]}"
    if frequency == "biweekly":
        return f"B{(now.isocalendar()[1] + 1) // 2}"
    if frequency == "monthly":
        return now.strftime("%Y-%m")
    return now.strftime("%m-%d")


class MeetingStreamConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Origin already validated against ALLOWED_HOSTS by the router wrapper.
        await self.accept()
        self._asr = None
        self._session_id = None
        self._meeting_id = None
        self._seq = 0
        self._audio_buffer = array("h")
        self._translate_enabled = True
        self._last_audio = 0.0
        self._flushing = False
        self._watchdog = None

        try:
            await self._setup_meeting()
        except Exception as e:
            logger.exception("meeting setup failed: %s", e)
            await self._send({"type": "error", "message": str(e)})
            await self.close()
            return

        self._asr = get_asr_client()
        self._session_id = await self._asr.start_session()
        await self._send(
            {"type": "ready", "meeting_id": self._meeting_id, "title": self._title}
        )
        self._last_audio = time.monotonic()
        self._watchdog = asyncio.create_task(self._inactivity_watchdog())

    async def disconnect(self, close_code):
        if self._watchdog is not None:
            self._watchdog.cancel()
        if self._asr is None or self._session_id is None:
            return
        try:
            async for result in self._asr.end_session(self._session_id):
                await self._handle_result(result)
        except Exception as e:
            logger.warning("end_session flush failed: %s", e)
        await self._save_audio()
        await self._mark_done()

    async def receive(self, text_data=None, bytes_data=None):
        if text_data is not None:
            try:
                ctrl = json.loads(text_data)
            except (json.JSONDecodeError, TypeError):
                return
            if ctrl.get("type") == "translate" and "enabled" in ctrl:
                self._translate_enabled = bool(ctrl["enabled"])
            return
        if not bytes_data or self._asr is None:
            return
        self._last_audio = time.monotonic()
        # Little-endian int16 frames; array('h') ingests directly (trim odd byte).
        if len(bytes_data) % 2 == 0:
            self._audio_buffer.frombytes(bytes_data)
        else:
            self._audio_buffer.frombytes(bytes_data[:-1])
        try:
            async for result in self._asr.feed(self._session_id, bytes_data):
                await self._handle_result(result)
        except Exception as e:
            logger.exception("asr feed error: %s", e)
            await self._send({"type": "error", "message": str(e)})

    # ------------------------------------------------------------------
    # Setup + teardown helpers
    # ------------------------------------------------------------------

    async def _setup_meeting(self):
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        meeting_id = qs.get("meeting_id", [None])[0]
        if meeting_id is not None:
            meeting = await sync_to_async(Meeting.objects.filter(pk=meeting_id).first)()
            if meeting is None:
                raise ValueError("meeting not found")
            self._meeting_id = meeting.id
            self._title = meeting.title
            await sync_to_async(
                Meeting.objects.filter(pk=meeting.id).update
            )(status=Meeting.Status.LIVE)
        else:
            title = (qs.get("title", [""])[0] or "Live session").strip() or "Live session"
            series_id = qs.get("series_id", [None])[0]
            series = None
            if series_id:
                from hub.models import MeetingSeries

                series = await sync_to_async(
                    MeetingSeries.objects.filter(pk=series_id).first
                )()
            suffix = _title_suffix(series.frequency if series else None)
            clean_title = title if suffix in title else f"{title} · {suffix}"
            meeting = await sync_to_async(Meeting.objects.create)(
                title=clean_title,
                series=series,
                status=Meeting.Status.LIVE,
            )
            self._meeting_id = meeting.id
            self._title = clean_title
        self._seq = await sync_to_async(
            Utterance.objects.filter(meeting_id=self._meeting_id).count
        )()

    async def _save_audio(self):
        if not self._audio_buffer:
            return
        try:
            from hub.meetings.audio import audio_dir

            name = audio_file_name(self._meeting_id)
            write_wav(audio_dir() / name, self._audio_buffer)
            await sync_to_async(
                Meeting.objects.filter(pk=self._meeting_id).update
            )(audio_path=name)
            logger.info("saved %d samples for meeting %d", len(self._audio_buffer), self._meeting_id)
        except Exception as e:
            logger.warning("audio save failed: %s", e)

    async def _mark_done(self):
        from django.utils import timezone

        await sync_to_async(Meeting.objects.filter(pk=self._meeting_id).update)(
            status=Meeting.Status.DONE, ended_at=timezone.now()
        )

    # ------------------------------------------------------------------
    # Result handling
    # ------------------------------------------------------------------

    async def _handle_result(self, result: AsrResult):
        if not result.is_final:
            await self._send(
                {
                    "type": "partial",
                    "text": result.text,
                    "lang": result.lang,
                    "start_ts": result.start_ts,
                    "end_ts": result.end_ts,
                }
            )
            return
        if not result.text:
            return  # skip empty finals (VAD boundary with no speech)
        self._seq += 1
        utt = await sync_to_async(Utterance.objects.create)(
            meeting_id=self._meeting_id,
            seq=self._seq,
            start_ts=result.start_ts or 0.0,
            end_ts=result.end_ts or 0.0,
            text=result.text,
            lang=result.lang,
        )
        # Transcript text reaches the user first; translation follows async.
        await self._send(
            {
                "type": "final",
                "utterance_id": utt.id,
                "text": result.text,
                "lang": result.lang,
                "translation": None,
                "start_ts": result.start_ts,
                "end_ts": result.end_ts,
            }
        )
        if self._translate_enabled:
            asyncio.create_task(self._translate_and_send(utt.id, result.text, result.lang))

    async def _translate_and_send(self, utterance_id: int, text: str, lang: str):
        from hub.meetings.translate import translate

        def _run():
            from hub.models import AppSettings

            return translate(AppSettings.load(), text, lang)

        try:
            translation = await sync_to_async(_run)()
        except Exception as e:
            logger.warning("translation failed (utt %d): %s", utterance_id, e)
            return
        if not translation:
            return
        await sync_to_async(
            Utterance.objects.filter(pk=utterance_id).update
        )(translation=translation)
        try:
            await self._send(
                {"type": "translation", "utterance_id": utterance_id, "translation": translation}
            )
        except Exception:
            pass  # client may be gone; the row is still updated

    # ------------------------------------------------------------------
    # Inactivity watchdog — flush the growing segment after 1.5 s of no
    # audio so the last sentence of a meeting shows up live.
    # ------------------------------------------------------------------

    async def _inactivity_watchdog(self):
        try:
            while True:
                await asyncio.sleep(_WATCHDOG_TICK_SEC)
                if self._flushing or self._asr is None:
                    continue
                if time.monotonic() - self._last_audio < _INACTIVITY_FLUSH_SEC:
                    continue
                self._flushing = True
                try:
                    async for result in self._asr.flush_pending(self._session_id):
                        await self._handle_result(result)
                except Exception as e:
                    logger.warning("inactivity flush failed: %s", e)
                finally:
                    self._flushing = False
                    self._last_audio = time.monotonic()
        except asyncio.CancelledError:
            return

    async def _send(self, payload: dict):
        await self.send(text_data=json.dumps(payload))
