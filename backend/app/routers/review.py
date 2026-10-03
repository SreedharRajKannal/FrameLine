"""
routers/review.py – Sreedhar's review API endpoints.
Owned by Sreedhar.

Endpoints:
  GET  /api/health
  GET  /api/meetings
  GET  /api/meetings/{id}
  PATCH /api/items/{id}
  PUT  /api/meetings/{id}/settings
  POST /api/meetings/{id}/reanchor
  POST /api/meetings/{id}/reprocess
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app import store
from backend.app.models import FeedbackItem, ProjectSettings

router = APIRouter(tags=["review"])

class TitleUpdate(BaseModel):
    title: str


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health")
def health() -> dict:
    """Simple health check – confirms the API is reachable."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Meetings
# ---------------------------------------------------------------------------

@router.get("/meetings")
def list_meetings() -> list[dict]:
    """Return a list of all meetings (meeting_id, title, summary)."""
    return store.list_meetings()


@router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: str) -> dict:
    """Return transcript, items, settings, and video info for a meeting."""
    transcript = store.get_transcript(meeting_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    items = store.get_items(meeting_id)
    settings = store.get_settings(meeting_id)
    meeting = store.get_meeting(meeting_id)
    video_id = store.get_meeting_video_id(meeting_id)
    video = store.get_video(video_id).model_dump() if video_id else None
    return {
        "transcript": transcript.model_dump(),
        "items": [i.model_dump() for i in items],
        "settings": settings.model_dump(),
        "status": meeting["status"] if meeting else "completed",
        "video_id": video_id,
        "video": video,
    }


@router.delete("/meetings/{meeting_id}")
def delete_meeting(meeting_id: str) -> dict:
    """Delete a meeting and all its data."""
    if store.get_transcript(meeting_id) is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    store.delete_meeting(meeting_id)
    return {"status": "ok"}


@router.put("/meetings/{meeting_id}/title")
def update_meeting_title_endpoint(meeting_id: str, payload: TitleUpdate) -> dict:
    """Update a meeting's title."""
    transcript = store.get_transcript(meeting_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    import json
    import sqlite3
    from backend.app import config
    
    # We also update the title in the raw_json of the transcript
    raw_dict = json.loads(transcript.model_dump_json())
    raw_dict["title"] = payload.title
    
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute(
            "UPDATE meetings SET title = ?, raw_json = ? WHERE meeting_id = ?", 
            (payload.title, json.dumps(raw_dict), meeting_id)
        )
        conn.commit()
    
    return {"status": "ok", "title": payload.title}


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

@router.patch("/items/{item_id}")
def patch_item(item_id: str, patch: dict) -> FeedbackItem:
    """Apply a partial update to a FeedbackItem. Returns the updated item."""
    updated = store.update_item(item_id, patch)
    if updated is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return updated


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.put("/meetings/{meeting_id}/settings")
def put_settings(meeting_id: str, settings: ProjectSettings) -> ProjectSettings:
    """Save (upsert) project settings for a meeting."""
    if store.get_transcript(meeting_id) is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    store.save_settings(meeting_id, settings)
    return settings


# ---------------------------------------------------------------------------
# Reanchor
# ---------------------------------------------------------------------------

@router.post("/meetings/{meeting_id}/reanchor")
def reanchor(meeting_id: str) -> dict:
    """
    Re-run anchoring with the current saved settings.
    Calls anchoring.anchor_items (pure function) then persists updated items.
    Returns a count of items updated.
    """
    try:
        from backend.app import anchoring
    except ImportError:
        raise HTTPException(status_code=503, detail="anchoring module not yet available")

    transcript = store.get_transcript(meeting_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    items = store.get_items(meeting_id)
    if not items:
        return {"reanchored": 0}

    settings = store.get_settings(meeting_id)

    try:
        anchored = anchoring.anchor_items(items, settings)
    except NotImplementedError:
        raise HTTPException(status_code=503, detail="anchoring.anchor_items is not yet implemented")

    store.save_items(meeting_id, anchored)
    return {"reanchored": len(anchored)}


# ---------------------------------------------------------------------------
# Reprocess
# ---------------------------------------------------------------------------

@router.post("/meetings/{meeting_id}/reprocess")
def reprocess(meeting_id: str) -> dict:
    """
    Re-run the full pipeline (extract + anchor) on the stored transcript.
    Calls pipeline.process_transcript then persists the new items.
    Returns a count of items produced.
    """
    try:
        from backend.app import pipeline
    except ImportError:
        raise HTTPException(status_code=503, detail="pipeline module not yet available")

    transcript = store.get_transcript(meeting_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    settings = store.get_settings(meeting_id)

    try:
        items = pipeline.process_transcript(transcript, settings)
    except NotImplementedError:
        raise HTTPException(status_code=503, detail="pipeline.process_transcript is not yet implemented")

    store.save_items(meeting_id, items)
    return {"processed": len(items)}
