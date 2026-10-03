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
# Vision Context & MiniCPM-V (Phase 3)
# ---------------------------------------------------------------------------
VISION_CONTEXT_ENABLED: bool = os.getenv("VISION_CONTEXT_ENABLED", "1") == "1"
MOCK_VISION_LLM: bool = os.getenv("MOCK_VISION_LLM", "0") == "1"
VISION_MODEL: str = os.getenv("VISION_MODEL", "minicpm-v4.5:8b")
VISION_VLM_ENABLED: bool = os.getenv("VISION_VLM_ENABLED", "1") == "1"
VISION_FRAME_INTERVAL_SEC: float = float(os.getenv("VISION_FRAME_INTERVAL_SEC", "2.5"))
VISION_FRAME_MAX_EDGE: int = int(os.getenv("VISION_FRAME_MAX_EDGE", "768"))
VISION_THINK_BUDGET_SEC: float = float(os.getenv("VISION_THINK_BUDGET_SEC", "0"))
VISION_DEDUP_THRESHOLD: float = float(os.getenv("VISION_DEDUP_THRESHOLD", "0"))

# YOLO detector and ByteTrack entity index
DETECTOR_ENABLED: bool = os.getenv("DETECTOR_ENABLED", "1") == "1"
DETECTOR_MODEL: str = os.getenv("DETECTOR_MODEL", "yolo11n.pt")
DETECTOR_GLOSSARY_PATH: str = os.getenv("DETECTOR_GLOSSARY_PATH", "")
DETECT_FPS: float = float(os.getenv("DETECT_FPS", "4"))
DETECT_SEGMENTATION: bool = os.getenv("DETECT_SEGMENTATION", "0") == "1"

