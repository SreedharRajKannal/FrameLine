"""
video_context.py – Video context builder, entity indexer, and context retrieval engine.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.app import config, store

logger = logging.getLogger(__name__)


def _normalize_entity_key(name: str) -> str:
    """Normalize object name to canonical key (lowercase, singular, clean)."""
    clean = name.strip().lower()
    # Simple singularization rules
    if clean.endswith("s") and not clean.endswith("ss") and len(clean) > 3:
        clean = clean[:-1]
    # Standardize common variants
    clean = re.sub(r"\b(sports\s+car|racing\s+car|automobile|vehicle)\b", "car", clean)
    clean = re.sub(r"\b(amber\s+bottle|cosmetic\s+bottle|serum\s+bottle)\b", "bottle", clean)
    return clean.strip()


def build_vlm_entity_index(descs: list[dict]) -> list[dict]:
    """Build the secondary VLM-only entity index for paired evaluation."""
    entity_map: dict[str, dict] = {}
    for row in descs:
        time_sec = row["time_sec"]
        for obj in row["data"].get("objects", []):
            raw_name = obj.get("name", "")
            if not raw_name:
                continue
            key = _normalize_entity_key(raw_name)
            entity = entity_map.setdefault(key, {
                "key": key,
                "name": raw_name,
                "color": obj.get("color"),
                "positions": set(),
                "support_times": [],
            })
            if obj.get("color") and not entity["color"]:
                entity["color"] = obj["color"]
            if obj.get("position"):
                entity["positions"].add(obj["position"])
            entity["support_times"].append(time_sec)

    entity_list = []
    for key, entity in entity_map.items():
        times = sorted(entity["support_times"])
        intervals = []
        if times:
            padding = min(config.VISION_FRAME_INTERVAL_SEC / 2, 0.5)
            start_sec = max(0.0, times[0] - padding)
            previous_sec = times[0]
            for time_sec in times[1:]:
                if time_sec - previous_sec < config.VISION_FRAME_INTERVAL_SEC + 1.0:
                    previous_sec = time_sec
                else:
                    intervals.append({
                        "start_sec": round(start_sec, 2),
                        "end_sec": round(previous_sec + padding, 2),
                    })
                    start_sec = max(0.0, time_sec - padding)
                    previous_sec = time_sec
            intervals.append({
                "start_sec": round(start_sec, 2),
                "end_sec": round(previous_sec + padding, 2),
            })
        entity_list.append({
            "key": key,
            "name": entity["name"],
            "class": key.split()[-1],
            "color": entity["color"],
            "track_ids": [],
            "intervals": intervals,
            "positions": sorted(entity["positions"]),
            "typical_position": next(iter(entity["positions"]), None),
            "support_times": times,
            "support_count": len(times),
            "confidence": None,
            "source": "vlm",
        })
    return entity_list


def _frame_context_lines(data: dict) -> list[str]:
    """Turn VLM fields into concise, useful timeline context."""
    lines = []
    scene = (data.get("scene") or "").strip()
    if scene:
        lines.append(scene)
    for label, field in (
        ("Action", "action"),
        ("Mood", "mood"),
        ("On-screen text", "text_on_screen"),
        ("Lighting", "lighting_and_palette"),
    ):
        value = data.get(field)
        if value and str(value).strip():
            lines.append(f"{label}: {str(value).strip()}")
    return lines


def build_video_context(video_id: str) -> dict:
    """
    Build scene segments, canonical entity index, and global summary from frame descriptions.
    Persists results to DB (video_context and entities tables).
    """
    descs = store.get_frame_descriptions(video_id)
    detections = store.get_detections(video_id)
    shots = store.get_shots(video_id)
    video = store.get_video(video_id)
    duration_sec = video.duration_sec if video else None

    if not descs and not detections:
        logger.warning("[%s] Cannot build video context: no vision or detector observations found", video_id[:8])
        empty_ctx = {
            "global_summary": "No video context available.",
            "entity_keys": [],
            "scene_segments": [],
        }
        store.save_video_context(video_id, empty_ctx)
        return empty_ctx

    # 1. Build Scene Segments
    scene_segments = []
    curr_segment = None

    for r in descs:
        t_sec = r["time_sec"]
        data = r["data"]
        context_lines = _frame_context_lines(data) or ["Video frame"]
        objs = [o["name"] for o in data.get("objects", []) if "name" in o]

        if curr_segment is None:
            curr_segment = {
                "start_sec": t_sec,
                "end_sec": t_sec,
                "summary": " | ".join(context_lines),
                "context_lines": context_lines,
                "key_objects": objs,
            }
        else:
            # Check if same scene or within close window
            same_scene = (
                not data.get("changed_from_previous", False)
                and (t_sec - curr_segment["end_sec"]) <= config.VISION_FRAME_INTERVAL_SEC + 0.1
            )
            if same_scene and (t_sec - curr_segment["start_sec"]) <= 12.0:
                curr_segment["end_sec"] = t_sec
                for line in context_lines:
                    if line not in curr_segment["context_lines"]:
                        curr_segment["context_lines"].append(line)
                curr_segment["summary"] = " | ".join(curr_segment["context_lines"])
                curr_segment["key_objects"] = list(set(curr_segment["key_objects"] + objs))
            else:
                scene_segments.append(curr_segment)
                curr_segment = {
                    "start_sec": t_sec,
                    "end_sec": t_sec,
                    "summary": " | ".join(context_lines),
                    "context_lines": context_lines,
                    "key_objects": objs,
                }

    if curr_segment:
        scene_segments.append(curr_segment)

    if not scene_segments:
        from backend.app.detector_pass import build_entity_index
        detector_entities = build_entity_index(detections, config.DETECT_FPS)
        for shot in shots:
            shot_entities = [
                entity["key"] for entity in detector_entities
                if any(
                    interval["start_sec"] < shot.end_sec and interval["end_sec"] > shot.start_sec
                    for interval in entity["intervals"]
                )
            ]
            scene_segments.append({
                "start_sec": shot.start_sec,
                "end_sec": shot.end_sec,
                "summary": shot.caption or f"Shot {shot.shot_index + 1}",
                "key_objects": shot_entities,
            })
        if not scene_segments and detections:
            end_sec = max(item["time_sec"] for item in detections) + 1.0 / max(config.DETECT_FPS, 0.1)
            scene_segments.append({
                "start_sec": 0.0,
                "end_sec": end_sec,
                "summary": "Video scene with detected objects",
                "key_objects": [entity["key"] for entity in detector_entities],
            })

    # Align segment end times nicely
    if descs:
        for i in range(len(scene_segments) - 1):
            scene_segments[i]["end_sec"] = scene_segments[i + 1]["start_sec"]
        if scene_segments:
            scene_segments[-1]["end_sec"] += config.VISION_FRAME_INTERVAL_SEC
    if duration_sec is not None:
        for segment in scene_segments:
            segment["end_sec"] = min(segment["end_sec"], duration_sec)

    # 2. Build VLM entities as fallback/secondary objects.
    entity_list = build_vlm_entity_index(descs)

    if detections:
        from backend.app.detector_pass import build_entity_index
        detector_entity_list = build_entity_index(detections, config.DETECT_FPS)
        detector_keys = {entity["key"] for entity in detector_entity_list}
        entity_list = detector_entity_list + [
            entity for entity in entity_list if entity["key"] not in detector_keys
        ]

    # 3. Build Global Summary
    subject_names = ", ".join(entity["key"] for entity in entity_list[:8]) or "no recognized entities"
    global_summary = (
        f"Video contains {len(scene_segments)} scene segments and {len(entity_list)} indexed entities: "
        f"{subject_names}. See the timeline for per-scene descriptions."
    )

    context_data = {
        "global_summary": global_summary,
        "entity_keys": [e["key"] for e in entity_list],
        "scene_segments": scene_segments,
        "built_at": store._time.time(),
    }

    # Save to store
    store.save_video_context(video_id, context_data)
    store.save_entities(video_id, entity_list)

    logger.info("[%s] Built video context: %d scenes, %d entities", video_id[:8], len(scene_segments), len(entity_list))
    return context_data


def get_relevant_context(
    query: str,
    hint_sec: float | None = None,
    token_budget: int = 1200,
    video_id: str = "",
) -> str:
    """
    Retrieve global summary + top relevant scene segments and entity intervals
    matching the query (with time hint bonus), formatted for prompt context.
    """
    if not video_id:
        videos = store.list_videos()
        if not videos:
            return "No video context available."
        video_id = videos[0].video_id

    ctx = store.get_video_context(video_id)
    if not ctx:
        # Build if frame descriptions exist
        ctx = build_video_context(video_id)

    entities = store.get_entities(video_id)
    q_lower = query.lower()

    # Find relevant entities
    matched_entities = []
    for ent in entities:
        key = ent["key"].lower()
        name = ent.get("name", "").lower()
        if key in q_lower or name in q_lower or any(word in q_lower for word in key.split()):
            matched_entities.append(ent)

    # Score scene segments
    scored_segments = []
    for seg in ctx.get("scene_segments", []):
        score = 0.0
        text = (seg["summary"] + " " + " ".join(seg.get("key_objects", []))).lower()
        
        # Word overlap score
        for word in q_lower.split():
            if len(word) > 2 and word in text:
                score += 1.0

        # Time hint proximity bonus
        if hint_sec is not None:
            mid_t = (seg["start_sec"] + seg["end_sec"]) / 2.0
            diff = abs(mid_t - hint_sec)
            if diff <= 30.0:
                score += max(0.0, 2.0 * (1.0 - diff / 30.0))

        scored_segments.append((score, seg))

    scored_segments.sort(key=lambda x: x[0], reverse=True)
    top_segments = [s[1] for s in scored_segments[:3]]

    # Format compact context string
    lines = [
        "--- VIDEO CONTEXT ---",
        f"Summary: {ctx.get('global_summary', 'N/A')}",
        "Entities Index:",
    ]

    for ent in entities:
        intervals_str = ", ".join([f"{i['start_sec']:.1f}-{i['end_sec']:.1f}s" for i in ent.get("intervals", [])])
        lines.append(f" - {ent['key']} ({ent.get('color', 'N/A')}): {intervals_str}")

    lines.append("Relevant Timeline Slices:")
    for seg in top_segments:
        objs_str = ", ".join(seg.get("key_objects", []))
        lines.append(f" - [{seg['start_sec']:.1f}s - {seg['end_sec']:.1f}s]: {seg['summary']} (Objects: {objs_str})")

    lines.append("--- END CONTEXT ---")
    return "\n".join(lines)
