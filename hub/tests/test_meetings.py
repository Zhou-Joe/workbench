"""Meetings: models, minutes builder, views, send-to-phase bridge, search."""

import json
from unittest.mock import patch

from .helpers import WorkspaceTestCase
from hub.meetings.asr import clean_sensevoice_text, detect_lang
from hub.meetings.minutes import build_minutes_markdown, minutes_filename
from hub.models import AppSettings, Document, Meeting, MeetingSeries, Utterance


def make_meeting(**kwargs):
    defaults = dict(title="Design review")
    defaults.update(kwargs)
    meeting = Meeting.objects.create(**defaults)
    Utterance.objects.create(
        meeting=meeting, seq=1, start_ts=1.0, end_ts=3.0,
        text="大家好，我们开始", lang="zh", translation="Hello everyone, let's start",
        speaker_label="speaker_0",
    )
    Utterance.objects.create(
        meeting=meeting, seq=2, start_ts=4.0, end_ts=6.0,
        text="Revenue is up", lang="en", speaker_label="Chen",
    )
    return meeting


class AsrHelperTests(WorkspaceTestCase):
    def test_detect_lang(self):
        self.assertEqual(detect_lang("hello world"), "en")
        self.assertEqual(detect_lang("大家好"), "zh")
        self.assertEqual(detect_lang("使用 Django today"), "mixed")
        self.assertEqual(detect_lang(""), "unknown")
        self.assertEqual(detect_lang("123!"), "unknown")

    def test_clean_sensevoice_text(self):
        self.assertEqual(
            clean_sensevoice_text("<|zh|><|NEUTRAL|><|Speech|>你好"), "你好"
        )
        self.assertEqual(clean_sensevoice_text("plain text"), "plain text")


class MinutesTests(WorkspaceTestCase):
    def test_minutes_markdown_groups_speakers_and_quotes_translations(self):
        meeting = make_meeting(summary="- point one")
        md = build_minutes_markdown(meeting, meeting.utterances.order_by("seq"))
        self.assertIn("# Design review", md)
        self.assertIn("## Summary", md)
        self.assertIn("- point one", md)
        self.assertIn("**speaker_0**", md)
        self.assertIn("**Chen**", md)
        self.assertIn("> Hello everyone, let's start", md)
        self.assertIn("大家好，我们开始", md)
        # speaker headers appear exactly once each despite two utterances
        self.assertEqual(md.count("**speaker_0**"), 1)

    def test_minutes_filename(self):
        meeting = make_meeting(title="Weekly Sync 大小写 Test")
        name = minutes_filename(meeting)
        self.assertTrue(name.startswith("meeting-"))
        self.assertTrue(name.endswith(".md"))


class MeetingViewTests(WorkspaceTestCase):
    def test_archive_lists_meetings_and_series_groups(self):
        series = MeetingSeries.objects.create(title="Weekly", frequency="weekly")
        make_meeting(title="In series", series=series)
        make_meeting(title="Standalone")
        resp = self.client.get("/meetings/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "In series")
        self.assertContains(resp, "Standalone")
        self.assertContains(resp, "Weekly")

    def test_detail_shows_transcript_and_actions(self):
        meeting = make_meeting()
        resp = self.client.get(f"/meetings/{meeting.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "大家好，我们开始")
        # apostrophe arrives HTML-escaped by Django autoescape
        self.assertContains(resp, "Hello everyone, let&#x27;s start")
        self.assertContains(resp, "Send to phase")

    def test_utterance_edit_updates_row(self):
        meeting = make_meeting()
        utt = meeting.utterances.get(seq=1)
        resp = self.client.post(
            f"/meetings/utterances/{utt.pk}/edit/",
            {"text": "edited", "translation": "改", "speaker_label": "Chen"},
        )
        self.assertEqual(resp.status_code, 200)
        utt.refresh_from_db()
        self.assertEqual(utt.text, "edited")
        self.assertEqual(utt.translation, "改")
        self.assertEqual(utt.speaker_label, "Chen")

    def test_rename_speaker_updates_all_labels(self):
        meeting = make_meeting()
        Utterance.objects.create(
            meeting=meeting, seq=3, text="more", speaker_label="speaker_0"
        )
        resp = self.client.post(
            f"/meetings/{meeting.pk}/rename-speaker/",
            {"old_label": "speaker_0", "new_label": "Chen"},
        )
        self.assertEqual(resp.status_code, 200)
        labels = set(meeting.utterances.values_list("speaker_label", flat=True))
        self.assertEqual(labels, {"Chen"})

    def test_delete_removes_meeting_and_wav(self):
        from hub.meetings.audio import audio_dir, audio_file_name

        meeting = make_meeting()
        wav = audio_dir() / audio_file_name(meeting.pk)
        wav.write_bytes(b"RIFF")
        meeting.audio_path = wav.name
        meeting.save()

        resp = self.client.post(f"/meetings/{meeting.pk}/delete/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Meeting.objects.filter(pk=meeting.pk).exists())
        self.assertFalse(wav.exists())

    def test_audio_404_when_missing(self):
        meeting = make_meeting()
        resp = self.client.get(f"/meetings/{meeting.pk}/audio/")
        self.assertEqual(resp.status_code, 404)

    def test_audio_serves_wav(self):
        from hub.meetings.audio import audio_dir, audio_file_name

        meeting = make_meeting()
        wav = audio_dir() / audio_file_name(meeting.pk)
        wav.write_bytes(b"RIFF-data")
        meeting.audio_path = wav.name
        meeting.save()
        resp = self.client.get(f"/meetings/{meeting.pk}/audio/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "audio/wav")

    def test_meeting_edit_changes_title_and_series(self):
        meeting = make_meeting()
        series = MeetingSeries.objects.create(title="S")
        resp = self.client.post(
            f"/meetings/{meeting.pk}/edit/", {"title": "Renamed", "series_id": series.pk}
        )
        self.assertEqual(resp.status_code, 200)
        meeting.refresh_from_db()
        self.assertEqual(meeting.title, "Renamed")
        self.assertEqual(meeting.series, series)


class SendToPhaseTests(WorkspaceTestCase):
    def test_send_to_phase_writes_minutes_and_links_document(self):
        project = self.seed_project()
        phase = project.phases.get(order=2)
        meeting = make_meeting(summary="- decided")

        resp = self.client.post(
            f"/meetings/{meeting.pk}/send-to-phase/", {"phase_id": phase.pk}
        )
        self.assertEqual(resp.status_code, 200)

        meeting.refresh_from_db()
        self.assertIsNotNone(meeting.filed_document)
        doc = meeting.filed_document
        self.assertEqual(doc.phase, phase)
        name = minutes_filename(meeting)
        path = self.phase_dir(project, 2) / name
        self.assertTrue(path.exists())
        content = path.read_text()
        self.assertIn("大家好，我们开始", content)
        self.assertIn("- decided", content)
        self.assertEqual(doc.filename, name)
        # a parse job was enqueued by the ingest scan
        self.assertTrue(doc.jobs.filter(kind="parse").exists())

    def test_send_to_phase_requires_phase(self):
        meeting = make_meeting()
        resp = self.client.post(f"/meetings/{meeting.pk}/send-to-phase/", {"phase_id": 99999})
        self.assertEqual(resp.status_code, 404)


class SummarizeStreamTests(WorkspaceTestCase):
    def test_summarize_stream_persists_and_streams(self):
        meeting = make_meeting()

        def fake_stream(settings, messages):
            yield "point "
            yield "one"

        with patch("hub.llm.chat_stream", side_effect=fake_stream):
            resp = self.client.get(f"/meetings/{meeting.pk}/summarize-stream/")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp["Content-Type"], "text/event-stream")
            # consume inside the patch — the generator runs lazily
            body = b"".join(resp.streaming_content).decode()
        self.assertIn("data: point ", body)
        self.assertIn("[DONE]", body)
        meeting.refresh_from_db()
        self.assertEqual(meeting.summary, "point one")

    def test_series_summarize_stream_persists(self):
        series = MeetingSeries.objects.create(title="Weekly")
        make_meeting(title="one", series=series, summary="did things")

        def fake_stream(settings, messages):
            yield "## ✅ Achieved"
            yield " stuff"

        with patch("hub.llm.chat_stream", side_effect=fake_stream):
            resp = self.client.get(f"/meetings/series/{series.pk}/summarize-stream/")
            body = b"".join(resp.streaming_content).decode()
        self.assertIn("Achieved", body)
        series.refresh_from_db()
        self.assertIn("Achieved", series.summary)


class SeriesViewTests(WorkspaceTestCase):
    def test_series_crud_roundtrip(self):
        resp = self.client.post(
            "/meetings/series/new/", {"title": "Design review", "frequency": "weekly"}
        )
        self.assertEqual(resp.status_code, 200)
        series = MeetingSeries.objects.get(title="Design review")
        self.assertEqual(series.frequency, "weekly")

        resp = self.client.get(f"/meetings/series/{series.pk}/")
        self.assertContains(resp, "Design review")

        resp = self.client.post(
            f"/meetings/series/{series.pk}/edit/",
            {"title": "Design review 2", "frequency": "biweekly", "description": ""},
        )
        series.refresh_from_db()
        self.assertEqual(series.title, "Design review 2")
        self.assertEqual(series.frequency, "biweekly")

        resp = self.client.post(f"/meetings/series/{series.pk}/delete/")
        self.assertFalse(MeetingSeries.objects.filter(pk=series.pk).exists())


class SpeakerViewTests(WorkspaceTestCase):
    def test_speaker_create_and_delete(self):
        self.client.post("/speakers/new/", {"name": "Chen", "color": "#111111"})
        from hub.models import Speaker

        spk = Speaker.objects.get(name="Chen")
        self.client.post(f"/speakers/{spk.pk}/delete/")
        self.assertFalse(Speaker.objects.filter(pk=spk.pk).exists())

    def test_speaker_enroll_requires_clip(self):
        from hub.models import Speaker

        spk = Speaker.objects.create(name="X")
        resp = self.client.post(f"/speakers/{spk.pk}/enroll/", {})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No audio file uploaded")


class MeetingSearchTests(WorkspaceTestCase):
    def test_search_finds_meeting_transcript_and_title(self):
        make_meeting(title="Chassis sync")
        resp = self.client.get("/search/?q=Revenue")
        # snippet interleaves <mark> into the matched text — match around it
        self.assertContains(resp, "is up")
        self.assertContains(resp, "Chassis sync")

        resp = self.client.get("/search/?q=Chassis")
        self.assertContains(resp, "Chassis sync")


class MeetingDataScriptTests(WorkspaceTestCase):
    def test_detail_embeds_valid_json(self):
        meeting = make_meeting()
        resp = self.client.get(f"/meetings/{meeting.pk}/")
        text = resp.content.decode()
        start = text.index('id="meeting-data" type="application/json">')
        blob = text[text.index(">", start) + 1:]
        blob = blob[: blob.index("</script>")]
        data = json.loads(blob)
        self.assertEqual(data["id"], meeting.pk)
        self.assertEqual(len(data["utterances"]), 2)
        self.assertEqual(data["utterances"][0]["translation"], "Hello everyone, let's start")


class LlmStreamTests(WorkspaceTestCase):
    def test_chat_stream_parses_sse_deltas(self):
        class FakeResp:
            status_code = 200

            def iter_lines(self, decode_unicode=True):
                return iter([
                    "data: " + json.dumps({"choices": [{"delta": {"content": "a"}}]}),
                    "",
                    "data: " + json.dumps({"choices": [{"delta": {"content": "b"}}]}),
                    "data: [DONE]",
                ])

        settings = AppSettings.load()
        settings.lm_model = "test-model"
        settings.save()
        with patch("hub.llm.requests.post", return_value=FakeResp()):
            from hub import llm

            out = list(llm.chat_stream(settings, []))
        self.assertEqual(out, ["a", "b"])
