# Frameline Phase 3 — Baseline Audit

> Generated: 2026-10-03 from live code inspection.

## 1. Current Code Architecture & Ownership

| Component / Module | Path | Ownership / Description |
|---|---|---|
| Data Models | `backend/app/models.py` | `Segment`, `Transcript`, `ProjectSettings`, `Video`, `Shot`, `CandidateShot`, `FeedbackItem` |
| Database Store | `backend/app/store.py` | SQLite tables: `meetings`, `items`, `settings`, `videos`, `shots`, `frames`, `processed_events` |
| Fast API Main | `backend/app/main.py` | Entrypoint with dynamic router imports and CORS |
| Video Indexer | `backend/app/video_index.py` | PySceneDetect shot detection, keyframe extraction, CLIP embeddings, `generate_caption` via Ollama |
| Routers | `backend/app/routers/` | `review.py` (meetings, items, settings), `video.py` (video upload/status/shots/link), `ingest.py` (webhooks & imports), `export.py` (EDL/CSV), `privacy.py` |
| Ingestion & Pipeline | `backend/app/ingest.py`, `backend/app/pipeline.py` | Transcript ingestion, Meetily webhook handler, feedback extraction (`extraction.py`) & anchoring (`anchoring.py`) |
| Local LLM Layer | `backend/app/llm.py` | Ollama client with fallback/retry logic, `MOCK_LLM=1` support |
| Frontend | `frontend/src/` | React + Vite (`App.jsx`, `api.js`, `timecode.js`, `index.css`) |

## 2. Active Database Schema (SQLite)

- `meetings`: `meeting_id` (PK), `title`, `summary`, `raw_json`, `status`, `video_id`
- `items`: `id` (PK), `meeting_id` (FK), `status`, `data` (JSON)
- `settings`: `meeting_id` (PK), `data` (JSON)
- `videos`: `video_id` (PK), `filename`, `path`, `fps`, `duration_sec`, `width`, `height`, `index_status`, `index_pct`, `created_at`, `updated_at`
- `shots`: `id` (PK), `video_id` (FK), `shot_index`, `start_sec`, `end_sec`, `keyframe_path`, `caption`
- `frames`: `id` (PK), `shot_id` (FK), `time_sec`, `embedding` (BLOB)
- `processed_events`: `event_id` (PK), `received_at`

## 3. Existing Video Indexing & Grounding Capabilities

- **Shot Detection**: Uses PySceneDetect (with fixed-segment fallback) to break videos into shot intervals (`Shot`).
- **Keyframe Extraction**: Uses `ffmpeg` to extract a 320px JPEG thumbnail per shot midpoint.
- **CLIP Embeddings**: `SentenceTransformer("clip-ViT-B-32")` embeds keyframe images and sub-sampled frame images.
- **Shot Captions**: `generate_caption` calls Ollama vision models (e.g. `moondream`) at shot index time.
- **Grounding**: `anchoring.py` ranks candidate shots per feedback item using visual CLIP similarity, LLM scoring, and time priors.

## 4. Gaps to Address for Phase 3 (MiniCPM-V Vision Context & Qwen Edit Effects)

1. **Vision Frame Description Pass**:
   - Need dense sampling (1 frame / 2 sec) with `ffmpeg` max edge 768px.
   - Frame deduplication (perceptual hashing / image difference threshold `VISION_DEDUP_THRESHOLD`).
   - Thinking budget control (`VISION_THINK_BUDGET_SEC=0.6`) for `minicpm-v4.5:8b` via Ollama with strict Pydantic JSON response.
   - Resource safety: Model lock ensuring Vision LLM and Text LLM never execute concurrently, unloading vision model with `keep_alive: 0`.

2. **Video Context & Entity Index Store**:
   - New database tables: `frame_descriptions`, `video_context`, `entities`.
   - Builder algorithm to aggregate frame JSONs into scene segments, canonical entity indexes ("red car: 0:12-0:18"), and global summary.
   - `get_relevant_context(...)` helper to extract context slices within prompt token limits (`num_ctx`).

3. **Client Feedback to Edit Instructions Engine**:
   - `qwen2.5` prompt logic to convert feedback items requiring changes into structured `EditInstruction` models.
   - Closed effect vocabulary (`color_pop`, `saturation`, `contrast`, `zoom_in`, `speed`, `volume`, etc.).
   - Code-level ffmpeg filter compiler with parameter clamping and validation.
   - Ambiguity detection (multiple target entity appearances) returning `candidate_intervals`.

4. **Preview Renderer & Marker Export**:
   - Side-by-side 480p before/after preview video generator (`data/previews/`).
   - Marker note formatter updating DaVinci Resolve EDL notes with `[COLOR POP] red car 0:12-0:18`.

5. **Frontend Extensions**:
   - Modular UI components for Video Context (Timeline, Entity Browser, Vision Progress) and Edit Instruction controls (Effect parameters, Ambiguity Picker, Side-by-Side Preview player).

6. **Evaluation & Mocking**:
   - `MOCK_VISION_LLM=1` canned descriptions (with worked example "red car" at 0:12-0:18).
   - Evaluation script `eval/eval_edit_effects.py` and vision benchmark script `scripts/bench_vision.py`.
