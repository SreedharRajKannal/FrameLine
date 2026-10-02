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
- (nothing yet)
### Karthik
- (nothing yet)
### Sivapriyan
- (nothing yet)

## 11. Decisions log (append only: `YYYY-MM-DD HH:MM, name: decision`)

## 12. Open questions / blockers (append only: `name: question`)

## 13. How to run
(Sreedhar keeps this current: install steps, env setup, start commands.)