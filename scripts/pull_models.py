"""
scripts/pull_models.py – Utility script to verify and pull required Ollama models.
"""
import sys
from pathlib import Path

# Ensure root directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from backend.app import config



def check_and_pull(model_name: str) -> None:
    if not model_name:
        return
    url_tags = f"{config.OLLAMA_URL.rstrip('/')}/api/tags"
    try:
        resp = httpx.get(url_tags, timeout=10)
        resp.raise_for_status()
        tags_data = resp.json()
        models = [m.get("name", "") for m in tags_data.get("models", [])]
        print(f"Current local models: {models}")
        if model_name in models or f"{model_name}:latest" in models:
            print(f"✓ Model '{model_name}' is already present.")
            return
    except Exception as exc:
        print(f"Warning: Could not list Ollama models: {exc}")

    print(f"Pulling model '{model_name}' via Ollama...")
    url_pull = f"{config.OLLAMA_URL.rstrip('/')}/api/pull"
    try:
        with httpx.stream("POST", url_pull, json={"name": model_name}, timeout=1800) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    print(line)
        print(f"✓ Successfully pulled '{model_name}'.")
    except Exception as exc:
        print(f"Error pulling model '{model_name}': {exc}")
        sys.exit(1)


def main():
    print(f"Checking models for Frameline (Ollama URL: {config.OLLAMA_URL})...")
    print(f"Text Model: {config.OLLAMA_MODEL}")
    check_and_pull(config.OLLAMA_MODEL)
    
    print(f"Vision Model: {config.VISION_MODEL}")
    check_and_pull(config.VISION_MODEL)


if __name__ == "__main__":
    main()
