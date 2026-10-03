"""
video_index.py – Video indexing pipeline.
Owned by Sreedhar.

Responsibilities:
  - Run ffprobe to get video metadata (fps, duration, resolution)
  - Detect shots with PySceneDetect (fallback: fixed segments)
  - Extract keyframe JPEGs (320px wide) for each shot
  - Compute CLIP image embeddings for keyframes and sampled frames
  - Generate captions at index time with a small vision LLM (Ollama moondream)
  - Persist shots and frame embeddings to SQLite via store.py

MOCK_VISION=1: skips all model calls and produces deterministic fake shots
(suitable for CI and tests without GPU/models).
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import time as _time
import uuid
from pathlib import Path

import httpx

from backend.app import config, store
from backend.app.models import Shot, Video

logger = logging.getLogger(__name__)

# ── Lazy CLIP model (singleton, CPU only) ─────────────────────────────────────

_clip_model = None


def _get_clip():
    """Return the CLIP SentenceTransformer model, or None if unavailable."""
    global _clip_model
    if _clip_model is not None:
        return _clip_model
    try:
        from sentence_transformers import SentenceTransformer
        device = config.CLIP_DEVICE if config.CLIP_DEVICE not in ("auto", "") else "cpu"
        logger.info("Loading CLIP model (clip-ViT-B-32) on device=%s …", device)
        _clip_model = SentenceTransformer("clip-ViT-B-32", device=device)
        logger.info("CLIP model loaded")
        return _clip_model
    except ImportError:
        logger.warning("sentence-transformers not installed; CLIP embeddings disabled")
        return None
    except Exception as exc:
        logger.warning("CLIP model failed to load (%s); embeddings disabled", exc)
        return None


# ── ffmpeg/ffprobe binary resolution ──────────────────────────────────────────

def _get_ffmpeg_bin() -> str:
    """Return path to ffmpeg binary (system PATH or imageio-ffmpeg bundle)."""
    import shutil
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    raise RuntimeError(
        "ffmpeg not found. Install it: winget install Gyan.FFmpeg  "
        "or: pip install imageio-ffmpeg"
    )


def _get_ffprobe_bin() -> str:
    """Return path to ffprobe binary (system PATH or imageio-ffmpeg bundle)."""
    import shutil
    found = shutil.which("ffprobe")
    if found:
        return found
    # imageio-ffmpeg ships ffprobe next to ffmpeg
    try:
        import imageio_ffmpeg
        ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
        probe = ffmpeg_path.parent / "ffprobe.exe"
        if probe.exists():
            return str(probe)
        # Try without .exe
        probe2 = ffmpeg_path.parent / "ffprobe"
        if probe2.exists():
            return str(probe2)
    except ImportError:
        pass
    # Last resort: ffprobe ships with the same package as ffmpeg on Windows
    # Fall back to ffmpeg's probe capability or raise
    raise RuntimeError(
        "ffprobe not found. Install ffmpeg: winget install Gyan.FFmpeg  "
        "or: pip install imageio-ffmpeg"
    )


# ── ID helpers ────────────────────────────────────────────────────────────────

def generate_video_id() -> str:
    return str(uuid.uuid4())


def _make_shot_id(video_id: str, index: int) -> str:
    h = hashlib.sha1(f"{video_id}:{index}".encode()).hexdigest()[:12]
    return f"shot-{h}"


def _make_frame_id(shot_id: str, time_sec: float) -> str:
    h = hashlib.sha1(f"{shot_id}:{time_sec:.3f}".encode()).hexdigest()[:12]
    return f"frame-{h}"


# ── Directory helpers ─────────────────────────────────────────────────────────

def get_video_dir(video_id: str) -> Path:
    d = Path(config.VIDEO_DATA_DIR) / video_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_thumb_dir(video_id: str) -> Path:
    d = get_video_dir(video_id) / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── ffprobe ────────────────────────────────────────────────────────────────────

def probe_video(video_path: Path) -> dict:
    """Run ffprobe; return {fps, duration_sec, width, height}."""
    try:
        ffprobe = _get_ffprobe_bin()
    except RuntimeError:
        # Fallback: try ffmpeg -i and parse output
        logger.warning("ffprobe not found; using ffmpeg -i fallback for metadata")
        return _probe_via_ffmpeg(video_path)

    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "quiet",
                "-print_format", "json",
                "-show_streams", "-show_format",
                str(video_path),
            ],
            capture_output=True, text=True, check=True, timeout=30,
        )
        data = json.loads(result.stdout)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffprobe failed: {exc.stderr[:300]}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffprobe timed out after 30 s")

    return _parse_ffprobe(data)


def _probe_via_ffmpeg(video_path: Path) -> dict:
    """Use ffmpeg -i (stderr) to get basic metadata when ffprobe is absent."""
    try:
        ffmpeg = _get_ffmpeg_bin()
        result = subprocess.run(
            [ffmpeg, "-i", str(video_path)],
            capture_output=True, text=True, timeout=15,
        )
        # ffmpeg -i always exits with code 1 when no output is specified; that's expected
        stderr = result.stderr
        fps = 24.0
        duration_sec = 0.0
        width, height = 0, 0
        import re
        m = re.search(r"(\d+)x(\d+)", stderr)
        if m:
            width, height = int(m.group(1)), int(m.group(2))
        m = re.search(r"(\d+(?:\.\d+)?)\s*fps", stderr)
        if m:
            fps = float(m.group(1))
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
        if m:
            h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            duration_sec = h * 3600 + mn * 60 + s
        return {"fps": fps, "duration_sec": duration_sec, "width": width, "height": height}
    except Exception as exc:
        logger.warning("ffmpeg probe fallback failed: %s; using defaults", exc)
        return {"fps": 24.0, "duration_sec": 60.0, "width": 0, "height": 0}


def _parse_ffprobe(data: dict) -> dict:
    fps = 24.0
    duration_sec = 0.0
    width = 0
    height = 0
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = stream.get("width", 0)
            height = stream.get("height", 0)
            for key in ("r_frame_rate", "avg_frame_rate"):
                val = stream.get(key, "")
                if val and "/" in val:
                    n_s, d_s = val.split("/")
                    try:
                        d_f = float(d_s)
                        if d_f > 0:
                            fps = float(n_s) / d_f
                    except ValueError:
                        pass
                    break
            break
    fmt = data.get("format", {})
    duration_sec = float(fmt.get("duration", 0))
    return {"fps": fps, "duration_sec": duration_sec, "width": width, "height": height}


# ── Shot detection ─────────────────────────────────────────────────────────────

_MAX_SHOTS = 60
_MIN_SHOT_SEC = 1.0


def detect_shots(video_path: Path, fps: float, duration_sec: float) -> list[dict]:
    """Return [{start_sec, end_sec}, …] for each detected shot."""
    shots = _detect_with_scenedetect(video_path)
    if shots is None or len(shots) < 2:
        logger.info(
            "Using fixed-segment fallback (scenedetect gave %s shots)",
            len(shots) if shots else "None",
        )
        shots = _fixed_segments(duration_sec, seg_len=10.0)

    # Filter minimum length
    shots = [s for s in shots if s["end_sec"] - s["start_sec"] >= _MIN_SHOT_SEC]

    # Cap at MAX_SHOTS by merging adjacent shots
    if len(shots) > _MAX_SHOTS:
        shots = _cap_shots(shots, _MAX_SHOTS)

    return shots


def _detect_with_scenedetect(video_path: Path) -> list[dict] | None:
    """Try PySceneDetect; return list or None on any failure."""
    try:
        from scenedetect import detect, ContentDetector
        scenes = detect(str(video_path), ContentDetector(threshold=config.SCENE_THRESHOLD))
        result = []
        for start_tc, end_tc in scenes:
            result.append({
                "start_sec": start_tc.get_seconds(),
                "end_sec": end_tc.get_seconds(),
            })
        logger.info("PySceneDetect: %d scenes found", len(result))
        return result
    except ImportError:
        logger.warning("scenedetect not installed; using fixed-length fallback")
        return None
    except Exception as exc:
        logger.warning("PySceneDetect failed (%s); using fixed-length fallback", exc)
        return None


def _fixed_segments(duration_sec: float, seg_len: float = 10.0) -> list[dict]:
    if duration_sec <= 0:
        return [{"start_sec": 0.0, "end_sec": 10.0}]
    segs = []
    t = 0.0
    while t < duration_sec:
        end = min(t + seg_len, duration_sec)
        if end - t >= _MIN_SHOT_SEC:
            segs.append({"start_sec": round(t, 3), "end_sec": round(end, 3)})
        t = end
    return segs


def _cap_shots(shots: list[dict], max_n: int) -> list[dict]:
    """Evenly subsample shots to at most max_n. Returns input unchanged if already within limit."""
    if len(shots) <= max_n:
        return shots
    # Select max_n evenly-spaced shots
    step = len(shots) / max_n
    kept = []
    for k in range(max_n):
        idx = int(k * step)
        idx = min(idx, len(shots) - 1)
        kept.append(shots[idx])
    # Fix end_sec of each kept shot to match the next one's start_sec
    for j in range(len(kept) - 1):
        kept[j]["end_sec"] = kept[j + 1]["start_sec"]
    return kept


# ── Keyframe extraction ────────────────────────────────────────────────────────

def extract_keyframe(video_path: Path, time_sec: float, out_path: Path) -> bool:
    """Extract one frame at time_sec as 320px-wide JPEG. Returns True on success."""
    try:
        ffmpeg = _get_ffmpeg_bin()
        subprocess.run(
            [
                ffmpeg,
                "-ss", f"{max(0.0, time_sec):.3f}",
                "-i", str(video_path),
                "-vframes", "1",
                "-vf", "scale=320:-1",
                "-q:v", "3",
                "-y", str(out_path),
            ],
            capture_output=True, check=True, timeout=20,
        )
        return out_path.exists() and out_path.stat().st_size > 0
    except FileNotFoundError:
        logger.error("ffmpeg binary not found")
        return False
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "ffmpeg keyframe failed at t=%.2f: %s",
            time_sec,
            (exc.stderr or b"")[:200],
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg keyframe timed out at t=%.2f", time_sec)
        return False


# ── CLIP embedding ─────────────────────────────────────────────────────────────

def clip_embed_image(image_path: Path) -> bytes | None:
    """Return CLIP embedding as serialized float32 bytes, or None."""
    model = _get_clip()
    if model is None:
        return None
    try:
        from PIL import Image
        import numpy as np
        img = Image.open(image_path).convert("RGB")
        emb = model.encode(img)
        return np.array(emb, dtype=np.float32).tobytes()
    except Exception as exc:
        logger.warning("CLIP embed failed for %s: %s", image_path.name, exc)
        return None


# ── Caption generation ─────────────────────────────────────────────────────────

def generate_caption(keyframe_path: Path, shot_index: int) -> str | None:
    """
    Call Ollama with CAPTION_MODEL (e.g. moondream) to describe a keyframe.
    Returns None silently on any failure (caption is optional).
    """
    if not config.CAPTION_MODEL:
        return None
    try:
        import base64
        img_b64 = base64.b64encode(keyframe_path.read_bytes()).decode()
        url = f"{config.OLLAMA_URL.rstrip('/')}/api/chat"
        payload = {
            "model": config.CAPTION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Describe this video frame in one concise sentence "
                        "for a video editor reviewing client feedback. "
                        "Focus on the main subject and action visible."
                    ),
                    "images": [img_b64],
                }
            ],
            "stream": False,
        }
        resp = httpx.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        text = resp.json().get("message", {}).get("content", "").strip()
        return text or None
    except Exception as exc:
        logger.debug("Caption skipped for shot %d: %s", shot_index, exc)
        return None


# ── Mock indexing ──────────────────────────────────────────────────────────────

def _mock_index(video_id: str) -> None:
    """MOCK_VISION=1: create deterministic fake shots without any real processing."""
    logger.info("MOCK_VISION: fake-indexing video %s", video_id)
    duration_sec = 60.0
    store.update_video_meta(
        video_id, fps=24.0, duration_sec=duration_sec, width=1920, height=1080
    )
    store.update_video_status(video_id, "running", 10.0)

    n_shots = 6
    shots: list[Shot] = []
    mock_captions = [
        "A product logo animates on screen.",
        "Close-up of a glass bottle rotating.",
        "Text overlays appear on a dark background.",
        "Wide shot of a brand lifestyle scene.",
        "Slow-motion pour of liquid.",
        "Final product shot with tagline.",
    ]
    for i in range(n_shots):
        start = i * (duration_sec / n_shots)
        end = (i + 1) * (duration_sec / n_shots)
        shot_id = _make_shot_id(video_id, i)
        shots.append(Shot(
            id=shot_id,
            video_id=video_id,
            shot_index=i,
            start_sec=round(start, 3),
            end_sec=round(end, 3),
            keyframe_path=None,     # no real file in mock mode
            caption=mock_captions[i % len(mock_captions)],
        ))
        store.update_video_status(video_id, "running", 10.0 + (i + 1) * 15.0)

    store.save_shots(shots)
    store.update_video_status(video_id, "done", 100.0)
    logger.info("MOCK_VISION: created %d fake shots for video %s", n_shots, video_id)


# ── Main index pipeline ────────────────────────────────────────────────────────

def index_video(video_id: str, video_path: Path) -> None:
    """
    Full indexing pipeline — runs as a FastAPI BackgroundTask.

    Steps:
      1. ffprobe (metadata)
      2. Shot detection (PySceneDetect or fixed fallback)
      3. Per shot: extract keyframe → CLIP embed → caption → sample extra frames
      4. Persist shots and frame embeddings to DB
      5. Mark status = done (or failed)
    """
    if config.MOCK_VISION:
        _mock_index(video_id)
        return

    try:
        store.update_video_status(video_id, "running", 0.0)

        # 1. ffprobe
        logger.info("[%s] Probing video metadata …", video_id[:8])
        meta = probe_video(video_path)
        fps = meta["fps"]
        duration_sec = meta["duration_sec"]
        store.update_video_meta(
            video_id,
            fps=fps,
            duration_sec=duration_sec,
            width=meta["width"],
            height=meta["height"],
        )
        logger.info(
            "[%s] Metadata: %.2f fps, %.1f s, %dx%d",
            video_id[:8], fps, duration_sec, meta["width"], meta["height"],
        )

        # 2. Shot detection
        store.update_video_status(video_id, "running", 5.0)
        raw_shots = detect_shots(video_path, fps, duration_sec)
        total = len(raw_shots)
        logger.info("[%s] %d shots to process", video_id[:8], total)

        # 3. Per-shot processing
        thumb_dir = get_thumb_dir(video_id)
        shots: list[Shot] = []
        frame_rows: list[tuple[str, str, float, bytes | None]] = []  # (frame_id, shot_id, t, emb)

        for i, s in enumerate(raw_shots):
            shot_id = _make_shot_id(video_id, i)
            start_sec = s["start_sec"]
            end_sec = s["end_sec"]
            mid_sec = (start_sec + end_sec) / 2.0

            # a. Keyframe at shot midpoint
            kf_path = thumb_dir / f"{shot_id}.jpg"
            kf_ok = extract_keyframe(video_path, mid_sec, kf_path)
            kf_str = str(kf_path) if kf_ok else None

            # b. CLIP embed keyframe
            kf_emb = clip_embed_image(kf_path) if kf_ok else None

            # c. Caption at index time
            caption = generate_caption(kf_path, i) if kf_ok else None

            shot = Shot(
                id=shot_id,
                video_id=video_id,
                shot_index=i,
                start_sec=start_sec,
                end_sec=end_sec,
                keyframe_path=kf_str,
                caption=caption,
            )
            shots.append(shot)

            # d. Keyframe frame record
            frame_id = _make_frame_id(shot_id, mid_sec)
            frame_rows.append((frame_id, shot_id, mid_sec, kf_emb))

            # e. Additional sampled frames every FRAME_INTERVAL_SEC within shot
            t = start_sec + config.FRAME_INTERVAL_SEC
            while t < end_sec - 0.5:
                extra_path = thumb_dir / f"f_{shot_id}_{t:.1f}.jpg"
                if extract_keyframe(video_path, t, extra_path):
                    emb = clip_embed_image(extra_path)
                    fid = _make_frame_id(shot_id, t)
                    frame_rows.append((fid, shot_id, t, emb))
                    # Remove extra JPEG — only keep keyframes for thumbnails
                    try:
                        extra_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                t += config.FRAME_INTERVAL_SEC

            pct = 10.0 + (i + 1) / total * 85.0
            store.update_video_status(video_id, "running", round(pct, 1))
            logger.debug("[%s] Shot %d/%d done (caption=%s)", video_id[:8], i + 1, total, bool(caption))

        # 4. Persist
        store.save_shots(shots)
        for frame_id, shot_id, time_sec, emb_bytes in frame_rows:
            if emb_bytes is not None:
                store.save_frame_embedding(frame_id, shot_id, time_sec, emb_bytes)

        store.update_video_status(video_id, "done", 100.0)
        logger.info(
            "[%s] Indexing complete: %d shots, %d frame embeddings",
            video_id[:8], len(shots), sum(1 for _, _, _, e in frame_rows if e is not None),
        )

    except Exception as exc:
        logger.exception("[%s] Indexing failed: %s", video_id[:8], exc)
        store.update_video_status(video_id, "failed", 0.0)


# ── Shot sheet (for LLM prompts in Phase 3) ────────────────────────────────────

def get_shot_sheet(video_id: str) -> str:
    """
    Human-readable shot list for LLM prompts.
    Format: Shot N (M:SS-M:SS): <caption>
    """
    shots = store.get_shots(video_id)
    if not shots:
        return "(no shots indexed)"
    lines = []
    for s in shots:
        m_s, ss_s = int(s.start_sec // 60), int(s.start_sec % 60)
        m_e, ss_e = int(s.end_sec // 60), int(s.end_sec % 60)
        tc = f"{m_s}:{ss_s:02d}-{m_e}:{ss_e:02d}"
        cap = f": {s.caption}" if s.caption else ""
        lines.append(f"Shot {s.shot_index + 1} ({tc}){cap}")
    return "\n".join(lines)
