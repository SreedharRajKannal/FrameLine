# Frameline Phase 2 — Baseline Audit

> Generated: 2026-10-03 from actual code inspection.

## Actual file layout

```
frameline/
  .env / .env.example
  CONTEXT.md / CLAUDE.md / AGENTS.md / README.md
  frameline.db          ← live SQLite, already has data
  backend/app/
    config.py           ← env loader (no VISION vars)
    models.py           ← Segment, Transcript, ProjectSettings, FeedbackItem
    store.py            ← SQLite CRUD: meetings / items / settings / processed_events
    main.py             ← FastAPI entry, try/except router imports
    pipeline.py         ← extract_feedback + anchor_items
    extraction.py       ← LLM chunking, validation, dedup
    anchoring.py        ← parse_spoken_time, anchor_items, FrameGrounder (inactive)
    llm.py              ← Ollama client, MOCK_LLM=1 path
    ingest.py           ← parse_uploaded_transcript
    meetily_client.py / meetily_poller.py / redaction.py
    routers/review.py ingest.py export.py privacy.py
    exporters/timecode.py edl.py csv_export.py
  backend/tests/        ← 79 tests, all passing
  frontend/src/         ← App.jsx (729 lines), api.js, timecode.js
  samples/              ← review_call_1.json, expected_items.json
  scripts/              ← register_webhook.py, simulate_webhook.py
```

## DB tables (actual)

| Table | Purpose |
|---|---|
| meetings | meeting_id PK, title, summary, raw_json, status |
| items | id PK, meeting_id FK, status, data JSON |
| settings | meeting_id PK, data JSON |
| processed_events | event_id PK, received_at |

**No video / shot / frame tables exist yet.**

## API endpoints (actual)

Sreedhar: GET /health, GET/DELETE /meetings, GET /meetings/{id}, PATCH /items/{id}, PUT /meetings/{id}/settings|title, POST /meetings/{id}/reanchor|reprocess

Karthik: POST /webhooks/meetily, POST /meetings/import, GET /meetily/status, GET /meetings/{id}/export.edl|export.csv

Sivapriyan: GET /meetings/{id}/safe-transcript

## Deviations from CONTEXT.md

- OLLAMA_MODEL default in CONTEXT.md is `qwen2.5:7b`; .env.example has `qwen2.5:3b-instruct`
- `anchor_source` Literal has no "vision" yet (planned for Phase 2)
- `FrameGrounder` Protocol exists but `grounder=None` everywhere — not activated
- Frontend uses `URL.createObjectURL` (local pick, no upload) — to be replaced
- Vision is "out of scope for MVP" in CONTEXT.md — Phase 2 changes this

## Test baseline: 79 passed, 7 warnings (MOCK_LLM=1)
