# Frameline

> AI-powered client feedback review for video editors — runs 100 % locally.

Frameline listens for Meetily webhook events, extracts timecoded feedback from transcripts using a local LLM (Ollama), and presents them in a web review screen where you can approve/reject items and export a DaVinci Resolve EDL or CSV.

## 5-line quickstart

```bash
cp .env.example .env          # fill in your Meetily key + webhook secret
pip install -r backend/requirements.txt
cd frontend && npm install && npm run dev &   # http://localhost:5173
cd .. && MOCK_LLM=1 uvicorn backend.app.main:app --reload --port 8000
# open http://localhost:5173, import samples/sample_transcript.json
```

## Demo script (hackathon)

1. **Start services** — run the two commands above (backend + frontend).
2. **Import sample** — click ⬆ in the sidebar, pick `samples/sample_transcript.json`.
3. **Load video** — on the meeting page, click "Choose video" and pick any MP4.
4. **Review** — click an item to seek the video to that moment; edit note/type/priority inline.
5. **Approve all** — hit "Approve all high-confidence" then check a few manually.
6. **Export** — click ⬇ EDL to download a DaVinci Resolve marker file.

## Full pipeline (with Ollama)

```bash
# pull the model once
ollama pull qwen2.5:7b
# run without mock
MOCK_LLM=0 uvicorn backend.app.main:app --reload --port 8000
# register webhook (Karthik)
python scripts/register_webhook.py
# simulate a webhook event (Karthik)
python scripts/simulate_webhook.py
```

## Vision Pass & Edit Effects (Phase 3)

Frameline converts video frames into rich text context using local vision models (`minicpm-v4.5:8b` via Ollama) and generates structured edit instructions using `qwen2.5`:

- **Vision Pass**: Samples frames every 2 seconds, deduplicates near-identical scenes, and runs MiniCPM-V with a 0.6s soft thinking budget.
- **Video Context & Entity Index**: Builds scene timelines and tracks entity appearances (e.g. `red car: 0:12-0:18`).
- **Edit Effects Engine**: Maps feedback items to closed effect vocabulary (`color_pop`, `zoom_in`, `saturation`, `volume`, etc.) with safe, code-compiled `ffmpeg` filter strings.
- **Side-by-Side Preview**: Renders 480p split-screen before/after clips (`data/previews/`).
- **DaVinci Resolve Markers**: Exports approved edit effects directly into Resolve marker notes (e.g. `[COLOR POP] red car 0:12-0:18`).

### Helper Scripts

```bash
# Pull required text & vision models via Ollama
python scripts/pull_models.py

# Benchmark vision pass latency & frames/sec throughput
python scripts/bench_vision.py <path_to_video.mp4>

# Run evaluation harness (hit rate, accuracy, latency)
python eval/eval_edit_effects.py
```

## Architecture

See [CONTEXT.md](CONTEXT.md) for full spec, team ownership, and API contracts.

```
Meetily webhook → verify HMAC → fetch transcript → Ollama LLM → MiniCPM-V Vision Pass
  → Video Context & Entity Index → Qwen Edit Instructions → Side-by-Side Preview → EDL / CSV Export
```

## Ownership

| Person | Files |
|---|---|
| Sreedhar | models, config, store, review API, video indexer, vision pass, video context, edit instructions, preview renderer, entire frontend, Context.md |
| Karthik | meetily_client, ingest, export routers, exporters, scripts |
| Sivapriyan | llm, extraction, anchoring, pipeline, redaction |

