"""
vision.py – FastAPI router for vision pass, video context, entity index, and edit instructions.
"""
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from pydantic import BaseModel

from backend.app import config, store
from backend.app.detector_pass import run_detector_pass
from backend.app.edit_instructions import generate_edit_instructions
from backend.app.models import FeedbackItem
from backend.app.preview_renderer import render_preview_clip
from backend.app.video_context import build_video_context
from backend.app.vision_pass import run_vision_pass

router = APIRouter(tags=["vision_context"])


# Progress memory store for background vision jobs
_VISION_JOB_PROGRESS: dict[str, dict[str, Any]] = {}


def _update_job_progress(video_id: str, pct: float, msg: str) -> None:
    _VISION_JOB_PROGRESS[video_id] = {
        "status": "running" if pct < 100.0 else "completed",
        "progress_pct": pct,
        "message": msg,
    }


def _auto_regenerate_linked_meeting_edits(video_id: str) -> None:
    """Find any meetings linked to video_id and update edit instructions with video context."""
    meetings = store.list_meetings()
    for m in meetings:
        mid = m["meeting_id"]
        linked_vid = store.get_meeting_video_id(mid)
        if linked_vid == video_id:
            items_raw = store.get_items(mid)
            if items_raw:
                items = [FeedbackItem.model_validate(it) for it in items_raw]
                generate_edit_instructions(mid, items, video_id=video_id)


def _run_vision_bg_job(video_id: str, video_path: Path) -> None:
    try:
        _update_job_progress(video_id, 5.0, "Starting YOLO object detection")
        run_detector_pass(video_id, video_path, progress_cb=lambda pct, msg: _update_job_progress(video_id, pct, msg))
        if config.VISION_VLM_ENABLED:
            run_vision_pass(
                video_id=video_id,
                video_path=video_path,
                progress_cb=lambda pct, msg: _update_job_progress(video_id, pct, msg),
            )
        build_video_context(video_id)

        # Re-run edit instructions for linked meetings using rich video context
        _auto_regenerate_linked_meeting_edits(video_id)

        _VISION_JOB_PROGRESS[video_id] = {
            "status": "completed",
            "progress_pct": 100.0,
            "message": "YOLO entities, frame context & edit instructions complete",
        }
    except Exception as exc:
        _VISION_JOB_PROGRESS[video_id] = {
            "status": "failed",
            "progress_pct": 0.0,
            "message": f"Vision pass failed: {exc}",
        }



@router.post("/videos/{video_id}/vision")
def trigger_vision_pass(video_id: str, bg_tasks: BackgroundTasks):
    """Trigger a detector-first context refresh for an uploaded video."""
    video = store.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    video_path = Path(video.path)
    _VISION_JOB_PROGRESS[video_id] = {
        "status": "pending",
        "progress_pct": 0.0,
        "message": "Enqueued vision pass",
    }
    bg_tasks.add_task(_run_vision_bg_job, video_id, video_path)
    return {
        "video_id": video_id,
        "status": "enqueued",
        "message": "YOLO detection and frame context generation started",
    }



@router.get("/videos/{video_id}/vision/status")
def get_vision_status(video_id: str):
    """Get detector-first context job status and sampled frame counts."""
    progress = _VISION_JOB_PROGRESS.get(video_id)
    descs = store.get_frame_descriptions(video_id)
    detections = store.get_detections(video_id)
    if not progress:
        video = store.get_video(video_id)
        status_str = "completed" if video and video.index_status == "done" else (
            "running" if video and video.index_status == "running" else "not_started"
        )
        progress = {
            "status": status_str,
            "progress_pct": video.index_pct if video else 0.0,
            "message": f"Indexed {len(detections)} detections" if detections else (
                "YOLO indexing in progress" if status_str == "running" else "No detector results yet"
            ),
        }
    progress["frame_count"] = len(descs)
    progress["detection_count"] = len(detections)
    return progress


@router.get("/videos/{video_id}/context")
def get_video_context_endpoint(video_id: str):
    """Get aggregated video context (global summary, scene timeline, entity keys)."""
    ctx = store.get_video_context(video_id)
    detections = store.get_detections(video_id)
    if not ctx or (ctx.get("global_summary") == "No video context available." and detections):
        descs = store.get_frame_descriptions(video_id)
        if descs or detections:
            ctx = build_video_context(video_id)
        else:
            raise HTTPException(status_code=404, detail="No video context available for this video")
    if ctx.get("global_summary") == "No video context available." and not detections:
        raise HTTPException(status_code=409, detail="No YOLO detections found; run YOLO indexing for this video")
    return ctx


@router.get("/videos/{video_id}/entities")
def get_entities_endpoint(video_id: str):
    """List entity index for a video."""
    return store.get_entities(video_id)


@router.get("/videos/{video_id}/entities/search")
def search_entities_endpoint(video_id: str, q: str = Query(..., description="Entity search query")):
    """Search entity index by keyword."""
    entities = store.get_entities(video_id)
    q_lower = q.lower().strip()
    results = [
        ent for ent in entities
        if q_lower in ent["key"].lower() or q_lower in ent.get("name", "").lower()
    ]
    return results


class GenerateEditsRequest(BaseModel):
    video_id: str | None = None


@router.post("/meetings/{meeting_id}/edits/generate")
def generate_edits_endpoint(meeting_id: str, req: GenerateEditsRequest | None = None):
    """Generate edit instructions for a meeting using video context & Qwen."""
    items_raw = store.get_items(meeting_id)
    if not items_raw:
        raise HTTPException(status_code=404, detail="Meeting items not found")

    items = [FeedbackItem.model_validate(item) for item in items_raw]
    v_id = req.video_id if req and req.video_id else ""
    try:
        edits = generate_edit_instructions(meeting_id=meeting_id, items=items, video_id=v_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Edit generation failed: {exc}") from exc
    actionable = [
        item for item in items
        if item.type == "change" or item.category in ("color", "pacing", "edit", "text_graphics", "sound")
    ]
    if actionable and not edits:
        raise HTTPException(
            status_code=502,
            detail="Qwen returned no edit instructions for actionable feedback. Check model availability and server logs.",
        )
    return edits


@router.get("/meetings/{meeting_id}/edits")
def get_edits_endpoint(meeting_id: str):
    """List edit instructions for a meeting."""
    return store.get_edit_instructions(meeting_id)


class EditPatchRequest(BaseModel):
    status: str | None = None
    start_sec: float | None = None
    end_sec: float | None = None
    params: dict[str, float] | None = None


@router.patch("/edits/{instruction_id}")
def patch_edit_instruction(instruction_id: str, patch: EditPatchRequest):
    """Patch edit instruction status, parameters, or time window."""
    updated = store.update_edit_instruction(instruction_id, patch.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Edit instruction not found")
    return updated


@router.post("/edits/{instruction_id}/preview")
def render_edit_preview(instruction_id: str):
    """Render a side-by-side 480p preview video clip for an edit instruction."""
    inst = store.get_edit_instruction(instruction_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Edit instruction not found")

    video_path = Path("fake_video.mp4")
    meeting = store.get_meeting(inst["meeting_id"])
    if meeting and meeting.get("video_id"):
        video = store.get_video(meeting["video_id"])
        if video:
            video_path = Path(video.path)

    preview_rel_path = render_preview_clip(video_path, inst)
    store.update_edit_instruction(instruction_id, {"preview_path": preview_rel_path})
    return {"preview_path": preview_rel_path, "instruction_id": instruction_id}

