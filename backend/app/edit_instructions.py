"""
edit_instructions.py – Feedback-to-Edit-Effects engine (Qwen) with closed effect vocabulary,
ffmpeg filter compiler, and ambiguity resolution.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app import config, store
from backend.app.llm import call_llm_json
from backend.app.models import FeedbackItem
from backend.app.video_context import get_relevant_context

logger = logging.getLogger(__name__)

# Closed effect vocabulary
CLOSED_EFFECTS = {
    "color_pop",
    "saturation",
    "contrast",
    "brightness",
    "warm",
    "cool",
    "desaturate",
    "zoom_in",
    "zoom_out",
    "blur",
    "vignette",
    "speed",
    "fade_in",
    "fade_out",
    "volume",
    "mute",
}


class EditInstruction(BaseModel):
    id: str
    item_id: str
    meeting_id: str
    effect: str
    target_entity: str | None = None
    start_sec: float
    end_sec: float
    params: dict[str, float] = Field(default_factory=dict)
    confidence: float = 1.0
    reason: str | None = None
    ambiguous: bool = False
    candidate_intervals: list[dict[str, float]] = Field(default_factory=list)
    status: str = "pending"
    filter_string: str | None = None


def compile_ffmpeg_filter(effect: str, params: dict[str, float]) -> str:
    """
    Code-level compiler that produces safe, validated ffmpeg video/audio filter strings.
    Clamps parameters to safe boundaries.
    """
    effect_clean = effect.lower().strip()
    if effect_clean not in CLOSED_EFFECTS:
        raise ValueError(f"Unknown effect '{effect}'. Must be one of {sorted(CLOSED_EFFECTS)}")

    if effect_clean == "color_pop":
        sat = max(1.0, min(2.0, float(params.get("saturation", 1.4))))
        cont = max(1.0, min(2.0, float(params.get("contrast", 1.25))))
        return f"eq=saturation={sat:.2f}:contrast={cont:.2f}"

    elif effect_clean == "saturation":
        sat = max(0.0, min(3.0, float(params.get("factor", 1.5))))
        return f"eq=saturation={sat:.2f}"

    elif effect_clean == "contrast":
        cont = max(0.1, min(3.0, float(params.get("factor", 1.3))))
        return f"eq=contrast={cont:.2f}"

    elif effect_clean == "brightness":
        bright = max(-0.5, min(0.5, float(params.get("level", 0.15))))
        return f"eq=brightness={bright:.2f}"

    elif effect_clean == "warm":
        return "colorbalance=rs=0.15:gs=0.05:bs=-0.15"

    elif effect_clean == "cool":
        return "colorbalance=rs=-0.15:gs=0.0:bs=0.20"

    elif effect_clean == "desaturate":
        sat = max(0.0, min(0.5, float(params.get("factor", 0.2))))
        return f"eq=saturation={sat:.2f}"

    elif effect_clean == "zoom_in":
        zoom = max(1.0, min(1.8, float(params.get("factor", 1.2))))
        return f"zoompan=z='min(zoom+0.0015,{zoom:.2f})':d=125:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"

    elif effect_clean == "zoom_out":
        return "zoompan=z='max(1.0,zoom-0.0015)':d=125:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"

    elif effect_clean == "blur":
        rad = max(1, min(20, int(params.get("radius", 5))))
        return f"boxblur={rad}:1"

    elif effect_clean == "vignette":
        angle = max(0.1, min(0.8, float(params.get("angle", 0.4))))
        return f"vignette=angle={angle:.2f}"

    elif effect_clean == "speed":
        factor = max(0.25, min(4.0, float(params.get("factor", 1.5))))
        pts = 1.0 / factor
        return f"setpts={pts:.3f}*PTS"

    elif effect_clean == "fade_in":
        dur = max(0.1, min(5.0, float(params.get("duration", 1.0))))
        return f"fade=t=in:st=0:d={dur:.1f}"

    elif effect_clean == "fade_out":
        dur = max(0.1, min(5.0, float(params.get("duration", 1.0))))
        return f"fade=t=out:st=0:d={dur:.1f}"

    elif effect_clean == "volume":
        gain_db = max(-30.0, min(20.0, float(params.get("gain_db", 3.0))))
        return f"volume={gain_db:.1f}dB"

    elif effect_clean == "mute":
        return "volume=0"

    return ""


def _find_entity_intervals(target_entity: str, video_id: str) -> list[dict[str, float]]:
    """Look up target entity intervals from DB entity index."""
    entities = store.get_entities(video_id)
    target_clean = target_entity.strip().lower()
    exact = [ent for ent in entities if ent["key"].strip().lower() == target_clean]
    matches = exact or [
        ent for ent in entities
        if target_clean in ent["key"].lower() or target_clean in ent.get("name", "").lower()
    ]
    intervals = [interval for entity in matches for interval in entity.get("intervals", [])]
    unique_intervals = sorted({
        (interval["start_sec"], interval["end_sec"]) for interval in intervals
    })
    return [
        {"start_sec": start_sec, "end_sec": end_sec}
        for start_sec, end_sec in unique_intervals
    ]


def generate_edit_instructions(
    meeting_id: str,
    items: list[FeedbackItem],
    video_id: str = "",
) -> list[dict]:
    """
    Generate proposed edit instructions for items requesting video editing changes.
    - If NO video is linked: uses purely transcript quotes & spoken timecodes.
    - If video IS linked: combines transcript with MiniCPM-V video context & entity index.
    """
    if not video_id:
        m = store.get_meeting(meeting_id)
        if m and m.get("video_id"):
            video_id = m["video_id"]
        # Intentionally DO NOT fall back to unlinked videos; respect transcript-only mode!

    # Filter items that ask for visual/editing changes
    change_items = [
        item for item in items
        if item.type == "change" or item.category in ("color", "pacing", "edit", "text_graphics", "sound")
    ]

    if not change_items:
        return []

    results = []
    generation_errors = []

    for item in change_items:
        # Mock mode check
        if config.MOCK_LLM or config.MOCK_VISION_LLM:
            q_lower = item.quote.lower() + " " + item.note.lower()
            if "color" in q_lower or "red car" in q_lower or "pop" in q_lower:
                intervals = _find_entity_intervals("red car", video_id) if video_id else []
                start_sec = intervals[0]["start_sec"] if intervals else (item.anchor_sec or item.segment_start_sec or 12.0)
                end_sec = intervals[0]["end_sec"] if intervals else (start_sec + 6.0)
                ambiguous = len(intervals) > 1

                inst = EditInstruction(
                    id=f"edit-{item.id[:8]}-colorpop",
                    item_id=item.id,
                    meeting_id=meeting_id,
                    effect="color_pop",
                    target_entity="red car" if video_id else None,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    params={"saturation": 1.4, "contrast": 1.25},
                    confidence=0.92,
                    reason="Client asked to boost color saturation." + (" (anchored to red car)" if video_id else " (transcript anchored)"),
                    ambiguous=ambiguous,
                    candidate_intervals=intervals,
                    filter_string=compile_ffmpeg_filter("color_pop", {"saturation": 1.4, "contrast": 1.25}),
                )
                inst_dict = inst.model_dump()
                store.save_edit_instruction(inst_dict)
                results.append(inst_dict)
                continue

        # Real Qwen LLM path
        context_str = ""
        if video_id:
            context_str = get_relevant_context(
                query=item.quote + " " + item.note,
                hint_sec=item.anchor_sec or item.segment_start_sec,
                video_id=video_id,
            )
        else:
            context_str = "--- TRANSCRIPT-ONLY CONTEXT (No video linked) ---"

        prompt = (
            f"Client Quote: \"{item.quote}\"\n"
            f"Note: \"{item.note}\"\n"
            f"Category: {item.category}\n"
            f"Transcript Anchor Time: {item.anchor_sec or item.segment_start_sec}s\n\n"
            f"{context_str}\n\n"
            "Create one actionable edit instruction for this feedback. If the client requests an edit, "
            "set has_effect to true. Use the video context to choose the matching entity and its interval; "
            "do not replace an explicit transcript time with an unrelated interval. For global requests, "
            "use a null target_entity. Return only this JSON object with valid JSON values:\n"
            "{\n"
            '  "has_effect": true,\n'
            '  "effect": "speed",\n'
            '  "target_entity": "bottle",\n'
            '  "start_sec": 5.0,\n'
            '  "end_sec": 10.0,\n'
            '  "params": {"factor": 0.7},\n'
            '  "confidence": 0.85,\n'
            '  "reason": "Slow the bottle pickup as requested."\n'
            "}"
        )

        try:
            res_json = call_llm_json(prompt, system="You are a professional video editor creating precise ffmpeg effect specifications.")
            data = res_json[0] if isinstance(res_json, list) and res_json else res_json
            effect = data.get("effect") if isinstance(data, dict) else None
            has_effect = data.get("has_effect", effect in CLOSED_EFFECTS) if isinstance(data, dict) else False
            if isinstance(data, dict) and has_effect and effect in CLOSED_EFFECTS:
                target = data.get("target_entity")
                intervals = _find_entity_intervals(target, video_id) if (target and video_id) else []

                start_sec = data.get("start_sec", item.anchor_sec or item.segment_start_sec or 0.0)
                end_sec = data.get("end_sec", start_sec + 5.0)
                if intervals:
                    hint_sec = item.spoken_timecode_sec if item.spoken_timecode_sec is not None else item.anchor_sec
                    selected_interval = min(
                        intervals,
                        key=lambda interval: (
                            0.0 if hint_sec is not None and interval["start_sec"] <= hint_sec <= interval["end_sec"]
                            else abs((interval["start_sec"] + interval["end_sec"]) / 2.0 - (hint_sec or start_sec))
                        ),
                    )
                    if item.spoken_timecode_sec is not None:
                        start_sec = item.spoken_timecode_sec
                        end_sec = min(
                            selected_interval["end_sec"],
                            max(float(end_sec), start_sec + 1.0),
                        )
                    else:
                        start_sec = selected_interval["start_sec"]
                        end_sec = selected_interval["end_sec"]

                filter_str = compile_ffmpeg_filter(effect, data.get("params", {}))

                inst = EditInstruction(
                    id=f"edit-{item.id[:8]}-{effect}",
                    item_id=item.id,
                    meeting_id=meeting_id,
                    effect=effect,
                    target_entity=target,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    params=data.get("params", {}),
                    confidence=data.get("confidence", 0.85),
                    reason=data.get("reason", "Generated from feedback note."),
                    ambiguous=len(intervals) > 1,
                    candidate_intervals=intervals,
                    filter_string=filter_str,
                )
                inst_dict = inst.model_dump()
                store.save_edit_instruction(inst_dict)
                results.append(inst_dict)
        except Exception as exc:
            logger.warning("Failed generating edit instruction for item %s: %s", item.id, exc)
            generation_errors.append(f"{item.id}: {exc}")

    # 6GB VRAM Safety: Unload text model after edit generation batch
    from backend.app.vision_pass import unload_ollama_model
    unload_ollama_model(config.OLLAMA_MODEL)

    if generation_errors and not results:
        raise RuntimeError("Qwen failed to generate edit instructions: " + "; ".join(generation_errors))

    return results

