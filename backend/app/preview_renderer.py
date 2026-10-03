"""
preview_renderer.py – Renders side-by-side before/after preview video clips for edit instructions.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from backend.app import config, store
from backend.app.video_index import _get_ffmpeg_bin, probe_video

logger = logging.getLogger(__name__)

PREVIEWS_DIR = Path("data/previews")


def render_preview_clip(video_path: Path, instruction: dict) -> str:
    """
    Render a 480p side-by-side before/after preview MP4 clip for an edit instruction.
    Left: original video slice.
    Right: effect-applied slice.
    Includes 1s padding before/after and 30ms audio fade.
    Returns relative path to rendered file.
    """
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    inst_id = instruction.get("id", "inst")
    out_path = PREVIEWS_DIR / f"preview_{inst_id}.mp4"

    # Fast return if already rendered
    if out_path.exists() and out_path.stat().st_size > 0:
        return str(out_path).replace("\\", "/")

    # Check mock mode or missing video
    if config.MOCK_VISION or config.MOCK_LLM or not video_path.exists():
        logger.info("Mock preview rendering for %s", inst_id)
        out_path.write_bytes(b"MOCK_PREVIEW_VIDEO_DATA")
        return str(out_path).replace("\\", "/")

    meta = probe_video(video_path)
    duration = meta.get("duration_sec", 60.0)

    start_sec = max(0.0, instruction.get("start_sec", 0.0) - 1.0)
    end_sec = min(duration, instruction.get("end_sec", 10.0) + 1.0)
    clip_len = max(1.0, end_sec - start_sec)

    filter_str = instruction.get("filter_string", "eq=saturation=1.4:contrast=1.2")

    # Split-screen filter graph: Left = original (scale 426x480), Right = effect (scale 426x480), hstack -> 852x480
    filter_complex = (
        f"[0:v]crop=iw/2:ih:0:0,scale=426:480[left];"
        f"[0:v]{filter_str},crop=iw/2:ih:iw/2:0,scale=426:480[right];"
        f"[left][right]hstack=inputs=2[v];"
        f"[0:a]afade=t=in:ss=0:d=0.03,afade=t=out:st={clip_len-0.03:.2f}:d=0.03[a]"
    )

    try:
        ffmpeg = _get_ffmpeg_bin()
        subprocess.run(
            [
                ffmpeg,
                "-ss", f"{start_sec:.2f}",
                "-t", f"{clip_len:.2f}",
                "-i", str(video_path),
                "-filter_complex", filter_complex,
                "-map", "[v]",
                "-map", "[a]",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "28",
                "-c:a", "aac",
                "-y", str(out_path),
            ],
            capture_output=True, check=True, timeout=45,
        )
        logger.info("Rendered preview clip: %s", out_path.name)
    except Exception as exc:
        logger.warning("Failed rendering preview clip (%s); creating fallback preview file", exc)
        out_path.write_bytes(b"FALLBACK_PREVIEW_VIDEO_DATA")

    return str(out_path).replace("\\", "/")
