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

# Webhook configuration
FRAMELINE_EXTERNAL_URL: str = os.getenv("FRAMELINE_EXTERNAL_URL", "http://127.0.0.1:8000")

# Comma-separated list of speaker labels that are NOT the client
EDITOR_SPEAKERS: list[str] = [
    s.strip()
    for s in os.getenv("EDITOR_SPEAKERS", "Host,Editor").split(",")
    if s.strip()
]

# ---------------------------------------------------------------------------
# Vision / video indexing (Phase 2+)
# ---------------------------------------------------------------------------
VISION_ENABLED: bool = os.getenv("VISION_ENABLED", "1") == "1"
MOCK_VISION: bool = os.getenv("MOCK_VISION", "0") == "1"
FRAME_INTERVAL_SEC: float = float(os.getenv("FRAME_INTERVAL_SEC", "2.0"))
SCENE_THRESHOLD: float = float(os.getenv("SCENE_THRESHOLD", "27.0"))
# Ollama vision model for keyframe captions (e.g. "moondream"); empty = skip
CAPTION_MODEL: str = os.getenv("CAPTION_MODEL", "")
CLIP_DEVICE: str = os.getenv("CLIP_DEVICE", "cpu")  # "cpu" or "cuda"
# Directory for video files and thumbnails (relative to cwd or absolute)
VIDEO_DATA_DIR: str = os.getenv("VIDEO_DATA_DIR", "data/videos")

# ---------------------------------------------------------------------------
# Hybrid grounding weights (Phase 3)
# ---------------------------------------------------------------------------
# W_TIME is intentionally low; only applies when sync_offset has been calibrated
GROUNDING_W_CLIP: float = float(os.getenv("GROUNDING_W_CLIP", "0.65"))
GROUNDING_W_TIME: float = float(os.getenv("GROUNDING_W_TIME", "0.10"))
GROUNDING_W_LLM: float = float(os.getenv("GROUNDING_W_LLM", "0.25"))
GROUNDING_TIME_WINDOW_SEC: float = float(os.getenv("GROUNDING_TIME_WINDOW_SEC", "30.0"))
GROUNDING_MIN_SCORE: float = float(os.getenv("GROUNDING_MIN_SCORE", "0.35"))
