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


def build_video_context(video_id: str) -> dict:
    """
    Build scene segments, canonical entity index, and global summary from frame descriptions.
    Persists results to DB (video_context and entities tables).
    """
    descs = store.get_frame_descriptions(video_id)
    shots = store.get_shots(video_id)

    if not descs:
        logger.warning("[%s] Cannot build video context: no frame descriptions found", video_id[:8])
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
        scene_desc = data.get("scene", "Video frame")
        objs = [o["name"] for o in data.get("objects", []) if "name" in o]

        if curr_segment is None:
            curr_segment = {
                "start_sec": t_sec,
                "end_sec": t_sec,
                "summary": scene_desc,
                "key_objects": objs,
            }
        else:
            # Check if same scene or within close window
            same_scene = (
                not data.get("changed_from_previous", False)
                or (t_sec - curr_segment["end_sec"]) <= config.VISION_FRAME_INTERVAL_SEC + 0.1
            )
            if same_scene and (t_sec - curr_segment["start_sec"]) <= 12.0:
                curr_segment["end_sec"] = t_sec
                curr_segment["key_objects"] = list(set(curr_segment["key_objects"] + objs))
            else:
                scene_segments.append(curr_segment)
                curr_segment = {
                    "start_sec": t_sec,
                    "end_sec": t_sec,
                    "summary": scene_desc,
                    "key_objects": objs,
                }

    if curr_segment:
        scene_segments.append(curr_segment)

    # Align segment end times nicely
    for i in range(len(scene_segments) - 1):
        scene_segments[i]["end_sec"] = scene_segments[i + 1]["start_sec"]
    if scene_segments:
        scene_segments[-1]["end_sec"] += config.VISION_FRAME_INTERVAL_SEC

    # 2. Build Entity Index
    entity_map: dict[str, dict] = {}

    for r in descs:
        t_sec = r["time_sec"]
        data = r["data"]
        objs = data.get("objects", [])

        for o in objs:
            raw_name = o.get("name", "")
            if not raw_name:
                continue

            key = _normalize_entity_key(raw_name)
            color = o.get("color")
            pos = o.get("position")

            if key not in entity_map:
                entity_map[key] = {
                    "key": key,
                    "name": raw_name,
                    "color": color,
                    "raw_intervals": [],
                    "positions": set(),
                    "support_times": [],
                }

            ent = entity_map[key]
            if color and not ent["color"]:
                ent["color"] = color
            if pos:
                ent["positions"].add(pos)
            ent["support_times"].append(t_sec)

    # Process intervals per entity
    entity_list = []
    for key, ent in entity_map.items():
        times = sorted(ent["support_times"])
        intervals = []
        if times:
            start_t = times[0]
            prev_t = times[0]
            padding = config.VISION_FRAME_INTERVAL_SEC

            for t in times[1:]:
                if t - prev_t <= padding + 1.0:
                    prev_t = t
                else:
                    intervals.append({"start_sec": round(start_t, 2), "end_sec": round(prev_t + padding, 2)})
                    start_t = t
                    prev_t = t
            intervals.append({"start_sec": round(start_t, 2), "end_sec": round(prev_t + padding, 2)})

        ent_record = {
            "key": key,
            "name": ent["name"],
            "color": ent["color"],
            "intervals": intervals,
            "positions": list(ent["positions"]),
            "support_times": times,
        }
        entity_list.append(ent_record)

    # 3. Build Global Summary
    distinct_scenes = [s["summary"] for s in scene_segments[:6]]
    global_summary = (
        f"Video timeline consists of {len(scene_segments)} scene segments featuring key subjects: "
        + ", ".join([e["key"] for e in entity_list[:8]])
        + ". Key scenes include: " + "; ".join(distinct_scenes) + "."
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
