# Meetings Integration Design — Ride Program Hub

Date: 2026-08-25
Status: Approved (in chat) — pending spec review
Source app: `MeetingAssitant/` (self-hosted bilingual meeting transcription, kept in-repo as reference only)

## 1. Goal

Fold the proven MeetingAssistant into the Ride Program Hub as a native
function: record a meeting inside the hub, get a live bilingual transcript
with speaker identification, generate LLM summaries, and file the minutes
into a project phase where the existing extraction pipeline turns them into
milestones. One Django process, one codebase, fully local.

User decisions (locked):

- **Topology: full absorption** into Django — no sidecar service.
- **UI scope: full surface** — live session, archive, meeting detail,
  speakers/voiceprints, recurring series.
- **Minutes flow: manual send-to-phase** — explicit project/phase picker on
  a finished meeting; nothing files itself.

## 2. Topology

- Django 6.1 app becomes ASGI via **channels 4.3 + daphne 4.2** (both
  verified to resolve for Python 3.14 on the Aliyun mirror).
  `manage.py runserver` keeps working and serves HTTP + WebSocket on the
  same port (daphne's runserver — requires `daphne` listed **first** in
  `INSTALLED_APPS` and `ASGI_APPLICATION` set in settings).
- ML stack installs into the hub venv: `funasr`, `modelscope`,
  `torchaudio`, `librosa`, `scikit-learn` (torch 2.13 resolves for cp314).
- ASR models (~1.5 GB: FSMN-VAD, SenseVoice-Small, ERes2NetV2) download
  lazily to `~/.cache/modelscope` on first use, then stay resident as
  process-global lazy singletons. CPU inference (funasr has no MPS
  support); heavy calls run in executor threads so async consumers and the
  dev server stay responsive. First-ever session start costs ~30–60 s of
  model loading; the live UI shows a loading state until the WS `ready`
  message arrives.
- `ridehub/asgi.py` becomes the entry point:
  `ProtocolTypeRouter({"http": get_asgi_application(), "websocket":
  URLRouter([...])})` with routing in `hub/routing.py`.
- The FastAPI backend, React frontend, and the whole `MeetingAssitant/`
  folder are **not used at runtime**; the folder stays as reference
  (gitignored).

## 3. Data model (one migration on `hub`)

| Model | Fields |
|---|---|
| `Meeting` | title, series (FK `MeetingSeries`, null), started_at, ended_at, status (`live`/`processing`/`done`), audio_path (relative name under `var/meetings/audio/`), summary (text, null), filed_document (FK `Document`, null — set by send-to-phase) |
| `Utterance` | meeting FK, seq (int), start_ts/end_ts (float s), text, lang (`en`/`zh`/`mixed`/`unknown`), translation (null), speaker_label (default `speaker_0`), is_final |
| `MeetingSeries` | title, description, frequency (`weekly`/`biweekly`/`monthly`), summary (null), created_at |
| `Speaker` | name, color |
| `Voiceprint` | speaker FK, embedding (192-dim float32 bytes), sample_path, created_at |

- `AppSettings` gains `asr_backend` (`stub` | `funasr_cpu`, default
  `funasr_cpu`; tests force `stub`). No other settings: the assistant's
  own settings table is dropped.
- WAV storage: `var/meetings/audio/meeting-{id}.wav` (gitignored with
  `var/`). Audio path is stored relative to that dir, mirroring the
  workspace-relative pattern used for documents.
- Deleting a meeting cascades utterances **and deletes its WAV** (fixes the
  assistant's orphaned-audio behavior).

## 4. Ported services — `hub/meetings/` package

Port from `MeetingAssitant/backend/app/services/` with logic unchanged
(it is proven behavior); adaptations noted:

| Source | Destination | Changes |
|---|---|---|
| `asr_client.py` | `hub/meetings/asr.py` | Keep `stub` and `funasr_cpu` backends. **Drop the external `funasr`-wss variant** (contradicts single-process). Keep stepped VAD (1.0 s → 0.6 s after 20 s monologue), 30 s force-flush, SenseVoice tag cleaning, CJK/Latin lang classification. Backend selected by `AppSettings.asr_backend` via the same lazy singleton. |
| `voiceprint.py` | `hub/meetings/voiceprint.py` | As-is (ERes2NetV2 embeddings, cosine match threshold 0.5). |
| `diarizer.py` | `hub/meetings/diarizer.py` | As-is (energy segmentation → embed → agglomerative clustering 2–6 by silhouette → utterance labeling by overlap → enrolled-voiceprint rename). |
| `enroll.py` | `hub/meetings/enroll.py` | As-is (slice WAV by utterance timestamps, concatenate, embed, store). |
| `translator.py` | — | **Replaced by `hub/llm.py`** (see §5). |
| `summarizer.py` | `hub/meetings/prompts.py` | Keep the two prompt shapes (3–5 bullet meeting summary; series ✅/🔄/⏭/📌 overview); execution goes through `hub/llm.py`. |
| `stream.py` (router) | `hub/consumers.py` | See §6. |
| `reprocess.py` | `hub/meetings/reprocess.py` | As-is offline pipeline (full-audio re-segment → re-transcribe → optional diarize/translate, replaces utterances). |

## 5. LLM — one configuration

All model calls go through the hub's existing LM Studio settings
(`AppSettings.lm_base_url` / `lm_model` / temperature / max tokens):

- **Live translation**: per final utterance, best-effort (failures never
  break the stream), toggle per session via the `translate` control frame.
- **Meeting summary** and **series summary**: same prompts as the
  assistant, executed via `hub/llm.py`.
- `hub/llm.py` gains `chat_stream(settings, messages)` — a generator over
  the OpenAI-compatible SSE `stream:true` response (requests
  `stream=True`), yielding text deltas. Non-streaming `chat()` unchanged.
  Errors follow the existing `LLMUnavailable` / `LLMError` taxonomy; SSE
  summarize endpoints emit an error event and stop cleanly on failure.

## 6. Live stream — channels consumer

`hub/consumers.py: MeetingStreamConsumer(AsyncWebsocketConsumer)` at
`/meetings/ws/` (URLRouter route in `hub/routing.py`).

- **Origin check** on connect (same-origin only), then accept.
- Query params: `?title=&series_id=` to start, or `?meeting_id=` to resume
  (seq continues; series auto-suffix logic ported: `W##`/`B##`/`YYYY-MM`).
- Client → server: **binary frames** = little-endian int16 mono 16 kHz PCM
  chunks; text frames = control JSON (`{"type":"translate","enabled":…}`).
- Server → client JSON messages, same protocol as the assistant:
  `{"type":"ready"|"partial"|"final"|"translation"|"error", …}`.
- 1.5 s receive-timeout flush and end-of-session flush (tail utterances
  never lost), full-session PCM accumulated in memory and written to WAV
  on disconnect; meeting → `done` + `ended_at`.
- Utterance rows insert immediately on `final` (own DB session via
  `sync_to_async`), translation runs as a fire-and-forget task through
  `hub/llm.py` in a thread.
- ASR inference runs in executor threads (`asyncio.to_thread` /
  `sync_to_async`), never on the event loop.
- Multiple simultaneous sessions allowed (each its own meeting + ASR
  session), same as the assistant.

## 7. HTTP surface (Django views under `hub/views/meetings*.py`)

Pages (htmx + Swiss style, nav gains **Meetings**):

| Route | Purpose |
|---|---|
| `/meetings/` | Archive: newest first, series grouping, client-side filter; "New live session" button; delete meeting |
| `/meetings/live/` | Live session host page (title, series pick, capture controls, live transcript) |
| `/meetings/<id>/` | Detail: summary panel (generate → SSE deltas render in place), transcript with inline edit (text/translation/speaker) and batch speaker rename, actions: diarize / reprocess / enroll voiceprint from this meeting / exports / **send to phase**; audio playback |
| `/meetings/speakers/` | Speaker CRUD + voiceprint enrollment (file upload; min 0.3 s) |
| `/meetings/series/`, `/meetings/series/<id>/` | Series CRUD + cross-meeting progress summary (streamed) |

Fragments/actions (htmx endpoints returning partials, consistent with the
rest of the hub): utterance inline-edit save, speaker rename, diarize,
reprocess, summarize-stream (SSE), series summarize-stream (SSE), meeting
title/status edit, delete. Binary/data endpoints: `/meetings/<id>/audio/`
(Django `FileResponse`, 404 if missing).

Search integration: the hub's main search page gains a **Meetings result
type** (LIKE over `Utterance.text` / `translation` + meeting title), with
highlighted snippets linking to the meeting detail.

## 8. Live page client (`hub/static/hub/js/meetings.js`)

Vanilla-JS ports of the React hooks, no build step:

- `useAudioCapture` → capture module: `getUserMedia` (mic,
  echoCancellation/noiseSuppression) and/or `getDisplayMedia` (system/tab
  audio), mixed via `MediaStreamAudioDestinationNode`, RMS level meter,
  `ScriptProcessorNode` frames → linear resample to 16 kHz → Int16 PCM
  `ArrayBuffer`s.
- `useLiveTranscript` → WS client: same-origin `/meetings/ws/`, binary
  frames, auto-reconnect (≤3 attempts, same meeting_id), message handling
  (append partials, commit finals, patch in translations), 译 toggle sends
  the control frame.
- Exports (`meetings-export.js`): client-side TXT / MD (grouped by
  speaker, translations as blockquotes) / styled HTML / SRT / JSON Blob
  downloads, ported from `lib/export.ts`.

## 9. Send-to-phase bridge

On a finished meeting, "Send to phase" opens a project → phase picker:

1. Build minutes markdown: title, date/duration/series, LLM summary (if
   generated), transcript grouped by speaker with translations as
   blockquotes — the assistant's proven MD export format.
2. Write `meeting-YYYY-MM-DD-<slug>.md` into the chosen phase folder via
   the workspace helpers (same path-safety rules as uploads).
3. Ingest + enqueue parse job — identical to the capture-inbox flow — so
   the extraction pipeline produces milestones into the ledger.
4. The meeting detail shows which document/phase it was filed to (simple
   link, stored on the meeting).

Deletion of the source file in Finder remains the undo, consistent with
folders-as-source-of-truth.

## 10. Security & placement

- Everything binds 127.0.0.1 as today; the WS consumer origin-checks
  before accept; POST actions ride the hub's existing CSRF setup.
- No new outbound network: ModelScope CDN (model download, first run only)
  and the already-configured LM Studio endpoint.
- New gitignored paths: `var/`.

## 11. Dependencies (`requirements.txt` additions)

`channels`, `daphne`, `funasr`, `modelscope`, `torchaudio`, `librosa`,
`scikit-learn` — all installed from the Aliyun mirror into the existing
Python 3.14 venv.

## 12. Testing

- Stub ASR backend everywhere in tests (as the assistant did).
- Channels `WebsocketCommunicator` tests: PCM in → `ready`/`final` out,
  tail flush on disconnect, translate toggle, resume by meeting_id.
- Unit tests: lang classification, SenseVoice tag cleaning, series title
  suffix, minutes markdown generation, send-to-phase with a real temp
  workspace (file lands in phase folder + Document created + parse job
  queued), audio FileResponse, deletion removes WAV, search integration.
- LLM mocked as in the existing suite. Suite grows from 115 to ~140.

## 13. Out of scope / dropped

- External FunASR wss server backend (contradicts single process).
- The assistant's own settings table/endpoint and its separate translator
  config (replaced by hub LM settings).
- React frontend, FastAPI backend, nginx deploy scripts (source folder
  kept as reference only).
- Post-meeting automation (jobs/`post_meeting.py`) — was never built in
  the source app either.

## 14. Carried-over limitations (known, accepted)

- FunASR model weights are under the FunASR Model Open Source License
  v1.1 — fine for personal/internal use; review before any external use.
- Diarization is pragmatic, tuned for 2–5 speakers, "not pyannote-grade".
- Code-switching accuracy unvalidated on audited corpora.
- CPU inference on this Mac: SenseVoice-Small is real-time-ish for
  meeting use (assistant benchmarks: CER ~7.8% zh).
- Live translation quality depends on the loaded LM Studio model; small
  models truncate long mixed-language utterances.
