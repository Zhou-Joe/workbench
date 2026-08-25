"""Live meeting WebSocket consumer — protocol behavior with the stub ASR.

Runs against the real ASGI application via channels' WebsocketCommunicator.
TransactionTestCase so the consumer's sync_to_async DB calls (executed in
worker threads) see real committed rows.
"""

import json

from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase

from hub.models import AppSettings, Meeting, MeetingSeries, Utterance


class MeetingStreamTests(TransactionTestCase):
    async def _force_stub_backend(self):
        """Never load funasr in tests — force the stub ASR backend."""
        from asgiref.sync import sync_to_async

        def _set():
            settings = AppSettings.load()
            settings.asr_backend = "stub"
            settings.save()

        await sync_to_async(_set)()

    async def _connect(self, query):
        await self._force_stub_backend()
        from ridehub.asgi import application

        # Real browsers always send Origin on WebSocket; the validator
        # denies connections without one. Send a same-origin header.
        communicator = WebsocketCommunicator(
            application,
            f"/meetings/ws/?{query}",
            headers=[(b"origin", b"http://localhost:8000")],
        )
        connected, _ = await communicator.connect(5)
        self.assertTrue(connected)
        return communicator

    async def _receive_json(self, communicator, timeout=5):
        return json.loads(await communicator.receive_from(timeout))

    async def test_ready_then_final_on_feed(self):
        comm = await self._connect("title=Test%20Session")
        try:
            ready = await self._receive_json(comm)
            self.assertEqual(ready["type"], "ready")
            self.assertTrue(ready["meeting_id"])
            meeting_id = ready["meeting_id"]
            self.assertIn("Test Session", ready["title"])

            # Stub script utterance 1 is one CJK "word": feed 1 → partial,
            # feed 2 → final.
            await comm.send_to(bytes_data=b"\x00\x00" * 160)
            partial = await self._receive_json(comm)
            self.assertEqual(partial["type"], "partial")

            await comm.send_to(bytes_data=b"\x00\x00" * 160)
            final = await self._receive_json(comm)
            self.assertEqual(final["type"], "final")
            self.assertEqual(final["lang"], "zh")
            self.assertTrue(final["text"])

            utt = await Utterance.objects.aget(pk=final["utterance_id"])
            self.assertEqual(utt.meeting_id, meeting_id)
            self.assertEqual(utt.seq, 1)
        finally:
            await comm.disconnect()

        # Disconnect flushed the session: WAV written, meeting marked done.
        meeting = await Meeting.objects.aget(pk=meeting_id)
        self.assertEqual(meeting.status, "done")
        self.assertTrue(meeting.audio_path)
        self.assertIsNotNone(meeting.ended_at)

    async def test_resume_continues_seq(self):
        meeting = await Meeting.objects.acreate(title="Existing")
        await Utterance.objects.acreate(
            meeting=meeting, seq=1, start_ts=0, end_ts=1, text="old line"
        )
        comm = await self._connect(f"meeting_id={meeting.pk}")
        try:
            ready = await self._receive_json(comm)
            self.assertEqual(ready["type"], "ready")
            self.assertEqual(ready["meeting_id"], meeting.pk)

            await comm.send_to(bytes_data=b"\x00\x00" * 160)
            await self._receive_json(comm)  # partial
            await comm.send_to(bytes_data=b"\x00\x00" * 160)
            final = await self._receive_json(comm)
            self.assertEqual(final["type"], "final")
            utt = await Utterance.objects.aget(pk=final["utterance_id"])
            self.assertEqual(utt.seq, 2)  # continued after the existing row
        finally:
            await comm.disconnect()

    async def test_translate_toggle_control_frame(self):
        comm = await self._connect("title=T")
        try:
            await self._receive_json(comm)  # ready
            await comm.send_to(text_data=json.dumps({"type": "translate", "enabled": False}))
            # Control frame consumed; no crash, stream continues.
            await comm.send_to(bytes_data=b"\x00\x00" * 160)
            partial = await self._receive_json(comm)
            self.assertEqual(partial["type"], "partial")
        finally:
            await comm.disconnect()

    async def test_series_title_suffix_applied(self):
        series = await MeetingSeries.objects.acreate(title="Weekly", frequency="weekly")
        comm = await self._connect(f"title=Sync&series_id={series.pk}")
        try:
            ready = await self._receive_json(comm)
            self.assertIn("W", ready["title"])
            meeting = await Meeting.objects.aget(pk=ready["meeting_id"])
            self.assertEqual(meeting.series_id, series.pk)
        finally:
            await comm.disconnect()

    async def test_unknown_meeting_id_rejected(self):
        comm = await self._connect("meeting_id=99999")
        try:
            msg = await self._receive_json(comm)
            self.assertEqual(msg["type"], "error")
            self.assertIn("not found", msg["message"])
        finally:
            await comm.disconnect()

    async def test_translation_message_after_final(self):
        """With the stub ASR + a mocked LLM, a final is followed by a
        translation message that also lands in the DB row."""
        from unittest.mock import patch

        def fake_chat(settings, messages):
            return "translated!"

        comm = await self._connect("title=Translate%20me")
        try:
            await self._receive_json(comm)  # ready
            with patch("hub.llm.chat", side_effect=fake_chat):
                await comm.send_to(bytes_data=b"\x00\x00" * 160)
                await self._receive_json(comm)  # partial
                await comm.send_to(bytes_data=b"\x00\x00" * 160)
                final = await self._receive_json(comm)  # final
                translation = await self._receive_json(comm, timeout=10)
                self.assertEqual(translation["type"], "translation")
                self.assertEqual(translation["utterance_id"], final["utterance_id"])
                self.assertEqual(translation["translation"], "translated!")
                utt = await Utterance.objects.aget(pk=final["utterance_id"])
                self.assertEqual(utt.translation, "translated!")
        finally:
            await comm.disconnect()
