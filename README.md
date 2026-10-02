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

## Architecture

See [CONTEXT.md](CONTEXT.md) for full spec, team ownership, and API contracts.

```
Meetily webhook → verify HMAC → fetch transcript → Ollama LLM → anchor to timecode
  → SQLite → Review UI → approved items → EDL / CSV
```

## Ownership

| Person | Files |
|---|---|
| Sreedhar | models, config, store, review API, entire frontend, Context.md |
| Karthik | meetily_client, ingest, export routers, exporters, scripts |
| Sivapriyan | llm, extraction, anchoring, pipeline, redaction |
