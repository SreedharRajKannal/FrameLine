"""
config.py – loads all env vars via python-dotenv with sensible defaults.
Owned by Sreedhar. Do not add secrets here; put them in .env (gitignored).
"""
import os
from dotenv import load_dotenv

load_dotenv()


# Meetily Pro Automation API
MEETILY_BASE_URL: str = os.getenv("MEETILY_BASE_URL", "http://127.0.0.1:8420")
MEETILY_API_KEY: str = os.getenv("MEETILY_API_KEY", "")
MEETILY_WEBHOOK_SECRET: str = os.getenv("MEETILY_WEBHOOK_SECRET", "")

# Ollama
OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

# Dev / testing flags
MOCK_LLM: bool = os.getenv("MOCK_LLM", "0") == "1"

# Storage
DB_PATH: str = os.getenv("DB_PATH", "frameline.db")

# Comma-separated list of speaker labels that are NOT the client
EDITOR_SPEAKERS: list[str] = [
    s.strip()
    for s in os.getenv("EDITOR_SPEAKERS", "Host,Editor").split(",")
    if s.strip()
]
