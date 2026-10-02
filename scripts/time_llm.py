#!/usr/bin/env python3
"""
scripts/time_llm.py  –  Time a short JSON-mode request against each model.

Usage (from repo root):
    python scripts/time_llm.py

Requirements: Ollama must be running (`ollama serve` or the tray app).
Set OLLAMA_NO_GPU=1 first if you get "Unable to init instance" errors.
"""
import json
import sys
import time
import httpx

OLLAMA_URL = "http://localhost:11434"
MODELS = ["qwen2.5:7b", "llama3.2:3b"]  # primary + fallback

PROMPT = (
    'Extract feedback from this transcript segment as JSON. '
    'Reply with ONLY a JSON array of objects, each with keys: '
    '"quote","note","type","category". '
    'Transcript: "At around thirty seconds the logo feels a bit big. '
    'Also love the music drop at 1:05."'
)

SYSTEM = (
    "You extract video-edit feedback. Return ONLY a JSON array. No extra text."
)

def time_model(model: str) -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": PROMPT},
        ],
        "format": "json",
        "stream": False,
    }
    url = f"{OLLAMA_URL}/api/chat"
    t0 = time.perf_counter()
    try:
        resp = httpx.post(url, json=payload, timeout=180)
        elapsed = time.perf_counter() - t0
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        parsed = json.loads(content)
        return {
            "model": model,
            "ok": True,
            "elapsed_sec": round(elapsed, 2),
            "items_returned": len(parsed) if isinstance(parsed, list) else "?",
            "raw_preview": content[:200],
        }
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return {
            "model": model,
            "ok": False,
            "elapsed_sec": round(elapsed, 2),
            "error": str(exc),
        }


def main():
    print("=" * 60)
    print("Frameline LLM timing benchmark")
    print("=" * 60)
    results = []
    for model in MODELS:
        print(f"\nTiming {model}...")
        r = time_model(model)
        results.append(r)
        if r["ok"]:
            print(f"  ✅  {r['elapsed_sec']}s  →  {r['items_returned']} item(s)")
            print(f"      Preview: {r['raw_preview']}")
        else:
            print(f"  ❌  {r['elapsed_sec']}s  →  ERROR: {r['error']}")

    print("\n" + "=" * 60)
    print("RECOMMENDATION:")
    ok = [r for r in results if r["ok"]]
    if not ok:
        print("  ⚠️  No models available. Check Ollama is running.")
        print("  Try: set OLLAMA_NO_GPU=1 && ollama serve")
        sys.exit(1)

    fastest = min(ok, key=lambda r: r["elapsed_sec"])
    print(f"  Use OLLAMA_MODEL={fastest['model']}")
    print(f"  Latency: {fastest['elapsed_sec']}s for a short request")
    if fastest["elapsed_sec"] > 60:
        print("  ⚠️  Slow! Running on CPU. Consider a 3B model if this is too slow.")
    print("=" * 60)


if __name__ == "__main__":
    main()
