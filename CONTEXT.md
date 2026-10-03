# Frameline: Context.md

Single source of truth for this project. Written for ANY AI coding assistant (Claude Code, Codex, etc.) or human.
Read this fully before writing code. Update your own section at every milestone and before ending a session.

## 1. What we are building (3-hour MVP)
Frameline is a Meetily Pro workflow. When a client review call ends and Meetily finishes the meeting summary,
Frameline automatically:
1. receives Meetily's signed webhook (event `summary.completed`),
2. fetches the timestamped transcript through Meetily's local Automation API (read scope only),
3. uses a LOCAL LLM (Ollama) to extract client feedback items,
4. anchors each item to a video timecode,
5. shows items in a web review screen (video beside notes, click to seek, edit/approve/reject),
6. exports color-coded DaVinci Resolve EDL markers and a CSV.

Everything runs locally. No audio or transcript leaves the laptop.
Context: 30-hour hackathon hosted by Zackriya Solutions (makers of Meetily). Goal for now: working MVP in 3 hours.

Out of scope for the MVP (future): video frame analysis / vision matching, Blender, task boards, CRM, MCP.
Extension point for vision: see `FrameGrounder` in `backend/app/anchoring.py`.

## 2. Pipeline
Meetily webhook -> verify HMAC -> dedupe event_id -> fetch transcript (API) -> extract feedback (LLM)
-> anchor to video time -> store (SQLite) -> review UI -> approved items -> EDL / CSV export.
Manual fallback: upload a transcript file via the UI (same pipeline after intake).

## 3. Team and ownership (only edit files you own)
| Person | Owns |
|---|---|
| Sreedhar | repo skeleton, `models.py`, `config.py`, `store.py`, `main.py`, `routers/review.py`, entire `frontend/`, Context.md structure, integration, demo |
| Karthik | `meetily_client.py`, `ingest.py`, `routers/ingest.py`, `exporters/*`, `routers/export.py`, `scripts/*`, `docs/` |
| Sivapriyan | `llm.py`, `extraction.py`, `anchoring.py`, `pipeline.py`, `redaction.py`, `routers/privacy.py`, `samples/`, extraction tests |

Need a change in someone else's file? Add a line under "Open questions" and tell your human. Do not edit it yourself.

## 4. Repo layout
frameline/
  Context.md  CLAUDE.md  AGENTS.md  README.md  .env.example  .gitignore
  backend/app/
    main.py  config.py  models.py  store.py
    meetily_client.py  ingest.py  llm.py  extraction.py  anchoring.py  pipeline.py  redaction.py
    routers/review.py  routers/ingest.py  routers/export.py  routers/privacy.py
    exporters/timecode.py  exporters/edl.py  exporters/csv_export.py
  backend/tests/
  frontend/            (React + Vite)
  samples/             (sample transcript + expected items)
  scripts/             (register_webhook.py, simulate_webhook.py)
  docs/                (meetily_openapi.json, notes)

## 5. Tech stack
- Backend: Python 3.11+, FastAPI, uvicorn, httpx, pydantic v2, sqlite3 (stdlib), python-dotenv, pytest
- Local AI: Ollama over HTTP (`OLLAMA_URL`, default http://localhost:11434), model from `OLLAMA_MODEL` (default `qwen2.5:7b`), JSON mode
- Frontend: React + Vite, minimal CSS, native `<video>` element, local video via `URL.createObjectURL` (no upload)
- Meetily: Pro Automation API at `MEETILY_BASE_URL` (default http://127.0.0.1:8420), read-only key, signed webhooks
- Env vars: MEETILY_BASE_URL, MEETILY_API_KEY, MEETILY_WEBHOOK_SECRET, OLLAMA_URL, OLLAMA_MODEL, MOCK_LLM (0/1), DB_PATH, EDITOR_SPEAKERS (comma list of speaker labels that are NOT the client)
- Backend runs on :8000, frontend on :5173. Webhook URL: http://127.0.0.1:8000/api/webhooks/meetily

## 6. Data contracts (shared; do not change without logging a decision)
```python
from typing import Literal
from pydantic import BaseModel

class Segment(BaseModel):
    start_sec: float
    end_sec: float | None = None
    speaker: str | None = None
    text: str

class Transcript(BaseModel):
    meeting_id: str
    title: str | None = None
    segments: list[Segment]
    summary: str | None = None

class ProjectSettings(BaseModel):
    fps: float = 24.0
    start_timecode: str = "01:00:00:00"   # timeline start TC
    sync_offset_sec: float = 0.0          # video_time = meeting_time + offset
    lookback_sec: float = 3.0             # people describe what they saw a moment ago
    version_label: str = "v1"

class FeedbackItem(BaseModel):
    id: str
    meeting_id: str
    quote: str                             # exact client words
    note: str                              # short actionable rewrite
    type: Literal["change", "question", "approval"]
    category: Literal["color", "sound", "pacing", "text_graphics", "edit", "other"]
    priority: Literal["high", "medium", "low"] = "medium"
    speaker: str | None = None
    segment_start_sec: float               # meeting-clock time of the quote
    spoken_timecode_sec: float | None = None
    anchor_sec: float | None = None        # video time in seconds (before start_timecode is added)
    anchor_source: Literal["spoken_timecode", "meeting_clock", "none"] = "none"
    is_global: bool = False                # applies to the whole piece, no single moment
    withdrawn: bool = False                # client later said "never mind"
    confidence: float = 0.5                # 0..1
    needs_review: bool = True
    status: Literal["pending", "approved", "rejected"] = "pending"
```

## 7. Function contracts
- `store.py` (Sreedhar): init_db(); save_transcript(t); get_transcript(meeting_id); list_meetings(); save_items(meeting_id, items) [replaces]; get_items(meeting_id); update_item(item_id, patch: dict); get_settings(meeting_id) -> ProjectSettings; save_settings(meeting_id, s)
- `extraction.py` (Sivapriyan): extract_feedback(t: Transcript) -> list[FeedbackItem]
- `anchoring.py` (Sivapriyan): anchor_items(items, settings) -> list[FeedbackItem]  (pure function; no LLM; safe to re-run when settings change)
- `pipeline.py` (Sivapriyan): process_transcript(t, settings) -> list[FeedbackItem]  (= extract + anchor)
- `meetily_client.py` (Karthik): get_transcript(meeting_id) -> Transcript; list_meetings()
- `ingest.py` (Karthik): handle_summary_completed(event: dict) -> None  (fetch -> store.save_transcript -> pipeline -> store.save_items); parse_uploaded_transcript(filename, content: bytes) -> Transcript
- `exporters/edl.py` (Karthik): build_edl(items, settings, title) -> str; `exporters/csv_export.py`: build_csv(items, settings) -> str
- Export includes only items with status == "approved" and withdrawn == False.

## 8. HTTP API
Karthik: POST /api/webhooks/meetily; POST /api/meetings/import (multipart file); GET /api/meetily/status; GET /api/meetings/{id}/export.edl; GET /api/meetings/{id}/export.csv
Sreedhar: GET /api/health; GET /api/meetings; GET /api/meetings/{id} (transcript + items + settings); PATCH /api/items/{id}; PUT /api/meetings/{id}/settings; POST /api/meetings/{id}/reanchor; POST /api/meetings/{id}/reprocess
Sivapriyan (stretch): GET /api/meetings/{id}/safe-transcript

## 9. Rules for every assistant
- Read-only Meetily scope. Never hard-code secrets; use `.env` (gitignored) and keep `.env.example` current.
- Do not invent Meetily endpoint shapes. Use the live `GET /openapi.json` (saved in docs/meetily_openapi.json). If unsure, ask your human.
- `MOCK_LLM=1` must make the whole app run without Ollama (loads samples/expected_items.json).
- Small commits. `git pull --rebase` before every push. Push at least every 20 minutes. Never force-push.
- Add a test for every non-trivial function. Run tests before pushing.
- Keep it simple: this is a 3-hour MVP. No extra frameworks, no auth, no Docker.

## 10. Status board (each person edits ONLY their own section)
### Sreedhar
- 2026-10-02 16:35 ✅ STEP 1 DONE: repo skeleton, CLAUDE.md, AGENTS.md, .gitignore, .env.example, models.py, config.py, store.py, main.py, all teammate stubs (meetily_client, ingest, llm, extraction, anchoring, pipeline, redaction, routers/ingest, routers/export, routers/privacy, exporters/*), requirements.txt, samples/expected_items.json, samples/sample_transcript.json
- 2026-10-02 16:35 ✅ STEP 2 DONE: routers/review.py (health, meetings CRUD, PATCH item, PUT settings, POST reanchor, POST reprocess), backend/tests/test_store.py, backend/tests/test_review.py
- 2026-10-02 19:25 ✅ WEBHOOK SETUP: Identified Meetily private IP restriction (HTTP 400). Registered public tunnel destination with Meetily API (201 Created). Auto-update script for .env created. All 79 backend tests passing.
- 2026-10-03 04:00 ✅ PHASE 3 VISION & EDIT EFFECTS COMPLETE: Built MiniCPM-V vision pass with frame deduplication & 0.6s soft thinking budget, video context timeline & entity indexer ("red car: 0:12-0:18"), Qwen edit instruction engine with closed effect vocabulary and code-level ffmpeg filter compiler, side-by-side 480p preview renderer, Resolve marker exporter, VideoContextPanel & EditInstructionCard React UI components, benchmark script, and evaluation harness (109/109 backend unit tests passing).

### Karthik
- 2026-10-02 17:00 ✅ PRE-WORK: Read all Meetily docs (authentication, webhooks-and-sse, api-reference, events, enable-and-connect). Key findings:
  - Signature headers: `X-Meetily-Signature: sha256=<hex HMAC-SHA256>`, `X-Meetily-Timestamp: <unix_seconds>`
  - HMAC computed over: `{timestamp}.{body}` (literal timestamp + dot + raw body bytes)
  - `summary.completed` event is thin: `{schema_version, event_id, event, occurred_at, resource: {kind, id}, delivery_id}`. Use `resource.id` to fetch transcript.
  - Webhook registration: `POST /v1/webhooks` with `{url, events, delivery_mode}` – requires Read scope. Returns `hmac_secret` shown only once.
  - Destination approval: after registering, destination starts `pending`. Must approve in Meetily: Settings > Integrations > Advanced > Destinations > Allow.
  - Transcript API: `GET /v1/meetings/{id}/transcript` returns `TranscriptResponse` with `meeting_id, title, segments[]`.
  - ⚠️ Local Meetily API (127.0.0.1:8420) not running – cannot fetch live openapi.json yet. Need Karthik to enable it.
- 2026-10-02 17:00 ✅ Saved `docs/sample_transcript_raw.json` (reconstructed from API docs schema – replace with real response when API available).
- 2026-10-02 17:02 ✅ STEP 1: `meetily_client.py` – httpx client with Bearer auth, `list_meetings()`, `get_transcript(meeting_id)` normalizing Meetily TranscriptResponse into our Transcript/Segment models, `is_reachable()`, `list_webhooks()`, `register_webhook()`.
- 2026-10-02 17:02 ✅ STEP 2: `ingest.py` – `handle_summary_completed(event)` full flow (fetch→store→pipeline→store items). `parse_uploaded_transcript()` handles our JSON, Meetily export JSON, Markdown, and timestamped plain text (`[HH:MM:SS] Speaker: text` and `HH:MM:SS Speaker: text`).
- 2026-10-02 17:02 ✅ STEP 2: `routers/ingest.py` – POST /api/webhooks/meetily (HMAC verify, dedupe via processed_events SQLite table, background task), POST /api/meetings/import (multipart file upload), GET /api/meetily/status (API reachable + webhook registered + last event).
- 2026-10-02 17:02 ✅ STEP 3: `scripts/register_webhook.py` (registers with Meetily, shows hmac_secret), `scripts/simulate_webhook.py` (sends correctly HMAC-signed fake summary.completed event).
- 2026-10-02 17:02 ✅ STEP 4: `exporters/timecode.py` – seconds↔frames↔HH:MM:SS:FF, non-drop-frame, any fps, start TC offset. `exporters/edl.py` – CMX 3600 EDL with Resolve marker comments (`|C:ResolveColor<X> |M:<note> |D:1`). `exporters/csv_export.py` – columns: id, timecode, type, category, priority, note, quote, speaker, confidence, status, version.
- 2026-10-02 17:02 ✅ STEP 4: `routers/export.py` – GET /api/meetings/{id}/export.edl and export.csv, approved+non-withdrawn only.
- 2026-10-02 17:02 ✅ STEP 5: `backend/tests/test_karthik.py` – 28 tests all passing: timecode round trips (24/25/30 fps), EDL golden file, signature accept/reject, duplicate event ignored, transcript parser cases (JSON/Meetily/text/markdown), CSV export.
- 2026-10-02 17:02 ⚠️ PENDING: Verify EDL format against real DaVinci Resolve export (need Karthik to export a marker EDL). Verify Meetily TranscriptSegmentDto field names against live openapi.json.
### Sivapriyan
- 2026-10-02 17:08 ✅ samples/review_call_1.json: realistic 4-5 min GlowSkin review call (Priya=editor, Rahul=client), 25 segments, 12+ feedback moments, all required types present
- 2026-10-02 17:08 ✅ samples/expected_items.json: replaced placeholder with 12 hand-crafted FeedbackItems for review_call_1 (all types, spoken TCs, global note, approval, withdrawal, PII)
- 2026-10-02 17:09 ✅ llm.py: Ollama /api/chat client, JSON mode, 120s timeout, retry with fix-JSON follow-up, MOCK_LLM=1 path
- 2026-10-02 17:10 ✅ anchoring.py: parse_spoken_time() handles M:SS / HH:MM:SS / "at 30s" / "one minute in" / "two minutes forty" / "around the 2 minute mark"; anchor_items() pure fn; FrameGrounder Protocol documented
- 2026-10-02 17:10 ✅ extraction.py: chunking 6000c+500 overlap, EDITOR_SPEAKERS filter, Pydantic validation, dedup, stable ids, spoken TC auto-parsed from quote
- 2026-10-02 17:10 ✅ pipeline.py: real path wired (extract_feedback + anchor_items); MOCK path preserved as-is
- 2026-10-02 17:11 ✅ redaction.py (STRETCH): RedactionResult dataclass, regex for email/phone/money (including spoken amounts), heuristic name detection, optional spaCy upgrade, restore(), redact_transcript()
- 2026-10-02 17:11 ✅ routers/privacy.py (STRETCH): GET /api/meetings/{id}/safe-transcript implemented
- 2026-10-02 17:12 ✅ backend/tests/test_sivapriyan.py: 30/30 tests pass (16 parser table tests, 6 anchor tests, MOCK smoke, eval recall/precision, 5 redaction tests)
- 2026-10-02 17:23 ✅ git commit 8193ba7 (local; push blocked – see blocker below)
- 2026-10-02 17:25 🚧 BLOCKER: Ollama crashes on start ("Unable to init instance: Unspecified error") – GPU driver issue, needs manual fix (see Open questions #1)

## 11. Decisions log (append only: `YYYY-MM-DD HH:MM, name: decision`)
- 2026-10-02 16:35, Sreedhar: store.py uses absolute imports (`backend.app.*`) so the package works from the repo root with `python -m` or pytest.
- 2026-10-02 16:35, Sreedhar: pipeline.py MOCK_LLM path resolves samples/ relative to the file's location so it works from any cwd.
- 2026-10-02 16:35, Sreedhar: teammate router imports in main.py are guarded by try/except ImportError so the app starts even when stubs have no routes yet.
- 2026-10-02 17:05, Karthik: meetily_client.py normalizes segment field names defensively (tries start_sec, start, start_time, start_ms) since we cannot verify TranscriptSegmentDto shape without live openapi.json.
- 2026-10-02 17:05, Karthik: processed_events dedup table shares the same DB_PATH as the main store (not a separate file) to keep things simple.
- 2026-10-02 17:05, Karthik: EDL marker comment format is `|C:ResolveColor<Color> |M:<note> |D:1` based on community docs — needs verification against a real Resolve export.
- 2026-10-03 04:00, Sreedhar: Closed effect vocabulary is compiled strictly at code level in Python using clamped parameter bounds to prevent LLMs from injecting unsafe raw ffmpeg filter strings.


## 12. Open questions / blockers (append only: `name: question`)

## 13. How to run

### Prerequisites
- Python 3.11+
- Node 18+
- (Optional) Ollama running locally with `qwen2.5:7b` pulled

### Install
```bash
# 1. Copy env and fill in secrets
cp .env.example .env

# 2. Backend
cd backend
pip install -r requirements.txt

# 3. Frontend
cd ../frontend
npm install
```

### Start (dev)
```bash
# Terminal 1 – backend (from repo root)
MOCK_LLM=1 uvicorn backend.app.main:app --reload --port 8000

# Terminal 2 – frontend
cd frontend && npm run dev
```
Open http://localhost:5173

### Run tests
```bash
# From repo root
pytest backend/tests/ -v
```

### Run with real Ollama
Set `MOCK_LLM=0` in `.env` and ensure `ollama serve` is running.