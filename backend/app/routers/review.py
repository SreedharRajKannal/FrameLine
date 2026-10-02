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
    """Return transcript, items, and settings for a meeting."""
    transcript = store.get_transcript(meeting_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    items = store.get_items(meeting_id)
    settings = store.get_settings(meeting_id)
    return {
        "transcript": transcript.model_dump(),
        "items": [i.model_dump() for i in items],
        "settings": settings.model_dump(),
    }


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

    items = store.get_items(meeting_id)
    if not items:
        raise HTTPException(status_code=404, detail="Meeting not found or has no items")
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
