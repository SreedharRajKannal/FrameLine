"""
vision_pass.py – Vision pass pipeline for frame sampling, deduplication, and description via MiniCPM-V (Ollama).
"""
from __future__ import annotations

import base64
import json
import logging
import math
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

import httpx
from pydantic import BaseModel, Field

from backend.app import config, store
from backend.app.models import Video
from backend.app.model_lock import LOCAL_INFERENCE_LOCK
from backend.app.video_index import _get_ffmpeg_bin, get_video_dir


logger = logging.getLogger(__name__)

# Global thread lock to prevent concurrent vision and text LLM calls
OLLAMA_MODEL_LOCK = LOCAL_INFERENCE_LOCK


class ObjectDetail(BaseModel):
    name: str
    color: str | None = None
    position: str | None = None  # left/center/right/top/bottom
    size: str | None = None      # small/medium/large
    attributes: list[str] = Field(default_factory=list)


class FrameDescription(BaseModel):
    scene: str
    mood: str | None = None
    objects: list[ObjectDetail] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    text_on_screen: str | None = None
    action: str | None = None
    shot_type: str | None = None
    lighting_and_palette: str | None = None
    changed_from_previous: bool = False


def unload_ollama_model(model_name: str) -> None:
    """Send keep_alive: 0 to Ollama to unload model weights from memory."""
    if not model_name:
        return
    url = f"{config.OLLAMA_URL.rstrip('/')}/api/chat"
    try:
        with OLLAMA_MODEL_LOCK:
            httpx.post(url, json={"model": model_name, "keep_alive": 0}, timeout=10)
        logger.info("Unloaded Ollama model '%s'", model_name)
    except Exception as exc:
        logger.warning("Failed to unload model '%s': %s", model_name, exc)


def _compute_image_diff(path1: Path, path2: Path) -> float:
    """
    Compute a simple perceptual/small-image difference score between two JPEGs.
    Returns float (lower means more similar).
    """
    try:
        from PIL import Image
        import numpy as np

        img1 = Image.open(path1).convert("L").resize((32, 32))
        img2 = Image.open(path2).convert("L").resize((32, 32))
        arr1 = np.array(img1, dtype=np.float32)
        arr2 = np.array(img2, dtype=np.float32)
        return float(np.mean(np.abs(arr1 - arr2)))
    except Exception as exc:
        logger.debug("Image diff computation failed (%s); defaulting to 999", exc)
        return 999.0


def extract_sampled_frames(video_path: Path, video_id: str) -> list[tuple[float, Path]]:
    """
    Extract frames every VISION_FRAME_INTERVAL_SEC with long edge max VISION_FRAME_MAX_EDGE.
    Returns list of (time_sec, frame_path).
    """
    from backend.app.video_index import probe_video

    meta = probe_video(video_path)
    duration = meta.get("duration_sec", 0.0)
    if duration <= 0:
        return []

    interval = max(0.5, config.VISION_FRAME_INTERVAL_SEC)
    max_edge = config.VISION_FRAME_MAX_EDGE
    out_dir = get_video_dir(video_id) / "vision_frames"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    t = 0.0
    ffmpeg = _get_ffmpeg_bin()

    # Scale filter preserving aspect ratio with max edge
    vf_scale = f"scale='if(gt(iw,ih),min(iw,{max_edge}),-1)':'if(gt(iw,ih),-1,min(ih,{max_edge}))'"

    while t < duration:
        t_round = round(t, 2)
        out_path = out_dir / f"frame_{t_round:.2f}.jpg"
        if not out_path.exists() or out_path.stat().st_size == 0:
            try:
                subprocess.run(
                    [
                        ffmpeg,
                        "-ss", f"{t_round:.2f}",
                        "-i", str(video_path),
                        "-vframes", "1",
                        "-vf", vf_scale,
                        "-q:v", "3",
                        "-y", str(out_path),
                    ],
                    capture_output=True, check=True, timeout=15,
                )
            except Exception as exc:
                logger.warning("Failed extracting frame at t=%.2f: %s", t_round, exc)
        if out_path.exists() and out_path.stat().st_size > 0:
            results.append((t_round, out_path))
        t += interval

    return results


def _mock_vision_descriptions(video_id: str, duration_sec: float = 60.0) -> list[dict]:
    """
    Generate deterministic canned descriptions for testing/CI.
    Includes the worked example entity 'red car' between 0:12 - 0:18 and 0:40 - 0:43.
    """
    # Ensure parent Video row exists in DB for foreign key constraint
    if not store.get_video(video_id):
        store.save_video(Video(
            video_id=video_id,
            filename="mock_video.mp4",
            path="/tmp/mock_video.mp4",
            duration_sec=duration_sec,
            index_status="done",
        ))

    interval = config.VISION_FRAME_INTERVAL_SEC
    results = []
    t = 0.0


    while t <= duration_sec:
        t_round = round(t, 2)
        is_red_car = (12.0 <= t_round <= 18.0) or (40.0 <= t_round <= 43.0)
        
        if is_red_car:
            desc = FrameDescription(
                scene="A sleek red sports car drives along a scenic coastal road.",
                objects=[
                    ObjectDetail(
                        name="red car",
                        color="red",
                        position="center",
                        size="large",
                        attributes=["sports car", "glossy", "moving"],
                    ),
                    ObjectDetail(
                        name="coastal road",
                        color="grey",
                        position="bottom",
                        size="large",
                        attributes=["asphalt", "curved"],
                    )
                ],
                people=[],
                text_on_screen=None,
                action="Car speeding past camera",
                shot_type="medium wide",
                lighting_and_palette="Bright daylight, vivid red and blue palette",
                changed_from_previous=True,
            )
        elif t_round < 12.0:
            desc = FrameDescription(
                scene="Opening title sequence with brand logo animation.",
                objects=[
                    ObjectDetail(
                        name="brand logo",
                        color="white",
                        position="center",
                        size="medium",
                        attributes=["animated", "clean"],
                    )
                ],
                people=[],
                text_on_screen="GLOWSKIN REVEAL",
                action="Logo fade in",
                shot_type="close-up",
                lighting_and_palette="Dark moody background with glowing white text",
                changed_from_previous=False,
            )
        else:
            desc = FrameDescription(
                scene="Studio close-up product shot of cosmetic glass bottle.",
                objects=[
                    ObjectDetail(
                        name="glass bottle",
                        color="amber",
                        position="center",
                        size="medium",
                        attributes=["dropper cap", "serum"],
                    )
                ],
                people=["Model"],
                text_on_screen="50ml e 1.7 fl.oz",
                action="Model holds bottle up to lighting",
                shot_type="macro close-up",
                lighting_and_palette="Warm studio lighting, gold highlights",
                changed_from_previous=True,
            )

        d_dict = desc.model_dump()
        store.save_frame_description(
            video_id=video_id,
            time_sec=t_round,
            data=d_dict,
            think_text="Canned mock thinking note.",
            latency_ms=15.0,
            reused=False,
            model="mock-minicpm",
        )
        results.append({
            "time_sec": t_round,
            "data": d_dict,
            "think_text": "Canned mock thinking note.",
            "latency_ms": 15.0,
            "reused": False,
            "model": "mock-minicpm",
        })
        t += interval

    return results


def describe_single_frame(
    frame_path: Path,
    prev_summary: str = "",
    think_budget_sec: float = 0.6,
) -> tuple[FrameDescription, str, float]:
    """
    Call MiniCPM-V via Ollama to describe one frame with strict JSON schema.
    Returns (FrameDescription, think_text, latency_ms).
    """
    img_b64 = base64.b64encode(frame_path.read_bytes()).decode("utf-8")

    prompt = (
        "Describe this video frame as part of an editor's continuous timeline, not as a list of detected categories. "
        f"Context from previous frame: '{prev_summary}'.\n"
        "Explain what is happening, what the main subject is doing, how the shot relates to the previous frame, "
        "and any visible product, setting, camera movement, or on-screen text. Be concrete and avoid generic labels. "
        "If uncertain, describe only visible evidence.\n"
        "Output ONLY valid JSON matching this schema:\n"
        "{\n"
        '  "scene": "One sentence summary of visual scene",\n'
        '  "mood": "visual mood or atmosphere",\n'
        '  "objects": [{"name": "normalized lowercase singular name", "color": "color", "position": "left|center|right|top|bottom", "size": "small|medium|large", "attributes": ["attr"]}],\n'
        '  "people": ["person description"],\n'
        '  "text_on_screen": "any visible text or null",\n'
        '  "action": "visible action or null",\n'
        '  "shot_type": "close-up|medium|wide",\n'
        '  "lighting_and_palette": "lighting description",\n'
        '  "changed_from_previous": true|false\n'
        "}"
    )

    system_prompt = (
        "You are a visual-story analyst helping a video editor understand a sequence of sampled frames. "
        "Prioritize scene meaning, action, continuity, composition, product/subject details, and readable text. "
        "Do not return generic object lists in place of a scene description. "
        "Always output valid JSON. Use normalized singular lowercase object names (e.g. 'red car', 'glass bottle')."
    )

    url = f"{config.OLLAMA_URL.rstrip('/')}/api/chat"
    start_time = time.time()
    think_text = ""

    # Acquire model lock so text & vision models don't compete for VRAM/RAM
    with OLLAMA_MODEL_LOCK:
        # Step 1: Pre-pass thinking / observation if budget > 0
        if think_budget_sec > 0:
            try:
                # 15 tokens/sec estimated fallback
                think_tokens = max(10, int(think_budget_sec * 20))
                t_resp = httpx.post(
                    url,
                    json={
                        "model": config.VISION_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {
                                "role": "user",
                                "content": f"Briefly observe key objects and colors in this frame within 0.5s: {prev_summary}",
                                "images": [img_b64],
                            },
                        ],
                        "options": {"num_predict": think_tokens},
                        "stream": False,
                    },
                    timeout=think_budget_sec + 5.0,
                )
                if t_resp.status_code == 200:
                    think_text = t_resp.json().get("message", {}).get("content", "").strip()
            except Exception as exc:
                logger.debug("Thinking pre-pass skipped (%s)", exc)

        # Step 2: Final JSON extraction call
        payload = {
            "model": config.VISION_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt, "images": [img_b64]},
            ],
            "format": "json",
            "stream": False,
        }

        resp = httpx.post(url, json=payload, timeout=60.0)
        resp.raise_for_status()
        raw_text = resp.json().get("message", {}).get("content", "").strip()
        latency_ms = (time.time() - start_time) * 1000.0

    # Parse and validate JSON
    try:
        data = json.loads(raw_text)
        # Normalize objects
        for obj in data.get("objects", []):
            if isinstance(obj, dict) and "name" in obj:
                obj["name"] = obj["name"].strip().lower()
        desc = FrameDescription.model_validate(data)
    except Exception as exc:
        logger.warning("Failed parsing MiniCPM-V JSON response (%s); falling back to default", exc)
        desc = FrameDescription(
            scene=raw_text[:150] or "Video frame",
            objects=[],
            changed_from_previous=True,
        )

    return desc, think_text, latency_ms


def run_vision_pass(
    video_id: str,
    video_path: Path,
    progress_cb: Callable[[float, str], None] | None = None,
) -> list[dict]:
    """
    Main vision pass background job.
    Resumable (skips described frames) and safe.
    """
    if not config.VISION_VLM_ENABLED and not config.MOCK_VISION_LLM and not config.MOCK_LLM:
        logger.info("[%s] VLM pass disabled; keeping detector-derived context", video_id[:8])
        if progress_cb:
            progress_cb(100.0, "VLM pass disabled")
        return store.get_frame_descriptions(video_id)

    if config.MOCK_VISION_LLM or config.MOCK_LLM:
        logger.info("[%s] MOCK_VISION_LLM=1 – using canned frame descriptions", video_id[:8])
        if progress_cb:
            progress_cb(100.0, "Completed (Mock)")
        return _mock_vision_descriptions(video_id)

    logger.info("[%s] Starting vision pass with model=%s", video_id[:8], config.VISION_MODEL)
    if progress_cb:
        progress_cb(5.0, "Extracting sampled frames...")

    sampled = extract_sampled_frames(video_path, video_id)
    if not sampled:
        logger.warning("[%s] No frames extracted for vision pass", video_id[:8])
        if progress_cb:
            progress_cb(100.0, "No frames")
        return []

    existing_descs = {r["time_sec"]: r for r in store.get_frame_descriptions(video_id)}
    total_frames = len(sampled)
    prev_frame_path: Path | None = None
    prev_desc: FrameDescription | None = None

    for idx, (t_sec, frame_path) in enumerate(sampled):
        pct = 10.0 + (idx / total_frames) * 85.0
        if progress_cb:
            progress_cb(round(pct, 1), f"Frame {idx+1}/{total_frames} ({t_sec:.1f}s)")

        # Skip if already described
        if t_sec in existing_descs:
            prev_frame_path = frame_path
            prev_desc = FrameDescription.model_validate(existing_descs[t_sec]["data"])
            continue

        # Check deduplication against previous frame
        reused = False
        if prev_frame_path and prev_desc:
            diff_score = _compute_image_diff(frame_path, prev_frame_path)
            if diff_score < config.VISION_DEDUP_THRESHOLD:
                reused = True
                desc = prev_desc.model_copy()
                desc.changed_from_previous = False
                think_text = "Reused from previous frame (near duplicate)"
                latency_ms = 1.0

        if not reused:
            prev_summary = prev_desc.scene if prev_desc else ""
            desc, think_text, latency_ms = describe_single_frame(
                frame_path=frame_path,
                prev_summary=prev_summary,
                think_budget_sec=config.VISION_THINK_BUDGET_SEC,
            )

        store.save_frame_description(
            video_id=video_id,
            time_sec=t_sec,
            data=desc.model_dump(),
            think_text=think_text,
            latency_ms=latency_ms,
            reused=reused,
            model=config.VISION_MODEL,
        )

        prev_frame_path = frame_path
        prev_desc = desc

    # Unload vision model weights from memory
    unload_ollama_model(config.VISION_MODEL)

    if progress_cb:
        progress_cb(100.0, "Vision pass complete")

    return store.get_frame_descriptions(video_id)


def generate_video_context_pipeline(
    video_id: str,
    video_path: Path,
    progress_cb: Callable[[float, str], None] | None = None,
) -> list[dict]:
    """
    End-to-end frame-to-context pipeline:
      1. extract sampled frames from the video,
      2. send each frame image to the local vision LLM,
      3. persist frame descriptions,
      4. aggregate them into scene/entity video context.
    This ensures the LLM sees discrete frames instead of the whole video file.
    """
    from backend.app.video_context import build_video_context

    descriptions = run_vision_pass(video_id, video_path, progress_cb=progress_cb)
    build_video_context(video_id)
    return descriptions
