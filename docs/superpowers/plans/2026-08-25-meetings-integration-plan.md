# Meetings Integration — Implementation Plan

Spec: `docs/superpowers/specs/2026-08-25-meetings-integration-design.md`
Nine phases, each ends green (tests) and committed.

## P1 — Foundation: deps, ASGI, models
1. `requirements.txt` += channels, daphne, funasr, modelscope, torchaudio,
   librosa, scikit-learn; install via Aliyun mirror into the 3.14 venv.
2. `ridehub/settings.py`: `daphne` first in INSTALLED_APPS,
   `ASGI_APPLICATION = "ridehub.asgi.application"`.
3. `ridehub/asgi.py` → ProtocolTypeRouter (http + websocket); empty
   `hub/routing.py`.
4. `.gitignore` += `/var/`.
5. Models: MeetingSeries, Speaker, Voiceprint, Meeting (incl.
   filed_document FK), Utterance; AppSettings.asr_backend (default
   funasr_cpu). Migration.
6. Verify: existing 115 tests pass; runserver still boots (daphne); SSE
   stream works.

## P2 — Port services → `hub/meetings/`
Port from `MeetingAssitant/backend/app/services/`, logic unchanged:
- `asr.py` (stub + funasr_cpu; drop wss variant) — lazy singleton by
  AppSettings.asr_backend.
- `voiceprint.py`, `diarizer.py`, `enroll.py`, `reprocess.py`,
  `prompts.py` (summarizer prompt shapes).
- ORM rewrite SQLAlchemy → Django models; DB session semantics → plain
  ORM calls.
- Unit tests: lang classify, SenseVoice tag cleaning, stub backend
  session behavior (stepped-VAD fields not testable without models —
  keep stub).

## P3 — LLM integration
- `hub/llm.py`: `chat_stream(settings, messages)` generator
  (requests stream=True); error taxonomy preserved.
- `hub/meetings/translate.py`: per-utterance translate via llm.chat;
  `hub/meetings/summarize.py`: meeting + series prompts via chat/chat_stream.
- Tests with mocked endpoint.

## P4 — WS consumer
- `hub/consumers.py` MeetingStreamConsumer: origin check, PCM frames →
  stub/funasr feed, control frames, ready/partial/final/translation,
  1.5 s tail flush, WAV write on disconnect, resume by meeting_id,
  series auto-suffix (W##/B##/YYYY-MM).
- `hub/routing.py`: route "meeting_stream" → /meetings/ws/.
- Tests: WebsocketCommunicator (stub backend) — ready, final on bytes,
  tail flush, translate toggle (mock LLM), resume seq continuation.

## P5 — Archive + detail views
- `hub/views/meetings.py`: archive (series groups, newest first), detail
  (summary panel, transcript, actions), utterance inline edit, speaker
  rename, title edit, delete (+WAV cleanup), audio FileResponse.
- Templates: `meetings.html`, `meeting_detail.html` + partials (Swiss
  style, htmx patterns, `rph:tick` SSE refresh).
- Nav entry + palette entries.
- Tests: page renders, edit endpoints, delete cascades + WAV removal,
  audio 404/200.

## P6 — Actions: diarize / reprocess / summarize / enroll
- POST endpoints running CPU work via threads; SSE summarize-stream
  (meeting + series) using chat_stream.
- Enroll voiceprint from meeting + file upload.
- Tests with stub ASR + mocked LLM.

## P7 — Live page + send-to-phase
- `hub/static/hub/js/meetings.js` (capture + WS client + level meter +
  译 toggle), `meetings-export.js` (TXT/MD/HTML/SRT/JSON blobs).
- `/meetings/live/` template; model-loading state until `ready`.
- Send-to-phase: project→phase picker, minutes .md (summary + grouped
  transcript), write via workspace helpers, ingest + parse job (capture
  flow), link back on detail.
- Tests: minutes content, file lands in phase, Document + job created.

## P8 — Speakers, series, search
- Speakers page (CRUD + enroll upload, min 0.3 s).
- Series pages (CRUD + cross-meeting summary).
- Hub search gains Meetings section (LIKE over utterances/title,
  snippet + link).
- Tests for each surface.

## P9 — Settings + final pass
- Settings page: asr_backend selector; hint about first-run model
  download + CPU-only.
- Full regression (target ~140 tests), restart dev server, smoke all
  pages + a stub-backend live session, final commit.

## Porting map (source → dest)
| MeetingAssitant/backend/app | Hub |
|---|---|
| services/asr_client.py | hub/meetings/asr.py |
| services/voiceprint.py | hub/meetings/voiceprint.py |
| services/diarizer.py | hub/meetings/diarizer.py |
| services/enroll.py | hub/meetings/enroll.py |
| services/reprocess.py | hub/meetings/reprocess.py |
| services/summarizer.py | hub/meetings/prompts.py + summarize.py |
| services/translator.py | hub/meetings/translate.py (via hub/llm.py) |
| routers/stream.py | hub/consumers.py |
| routers/meetings.py, speakers.py, series.py | hub/views/meetings*.py |
| models.py | hub/models.py |
| frontend/src/hooks/*.ts | hub/static/hub/js/meetings.js |
| frontend/src/lib/export.ts | hub/static/hub/js/meetings-export.js |
