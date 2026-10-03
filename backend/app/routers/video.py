"""
routers/video.py – Video upload, indexing status, shot listing, and streaming.
Owned by Sreedhar.

Endpoints:
  POST /api/videos                        – upload a video file; start background index
  GET  /api/videos                        – list all uploaded videos
  GET  /api/videos/{video_id}/status      – index progress and shot count
  POST /api/videos/{video_id}/reindex     – drop shots and rerun indexing
  GET  /api/videos/{video_id}/shots       – shot list with thumb URLs
  GET  /api/videos/{video_id}/thumb/{sid} – serve JPEG thumbnail (Content-Type: image/jpeg)
  GET  /api/videos/{video_id}/stream      – serve video with HTTP range-request support
  PUT  /api/meetings/{meeting_id}/video   – link a video_id to a meeting (or unlink with null)
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.app import config, store
from backend.app.models import Video
from backend.app.video_index import generate_video_id, get_video_dir, index_video

router = APIRouter(tags=["video"])


# ── Video upload ───────────────────────────────────────────────────────────────

@router.post("/videos")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    Upload a video file and begin background indexing.
    Returns immediately with video_id; poll /api/videos/{video_id}/status for progress.
    """
    video_id = generate_video_id()
    video_dir = get_video_dir(video_id)

    filename = file.filename or "video.mp4"
    suffix = Path(filename).suffix.lower() or ".mp4"
    video_path = video_dir / f"video{suffix}"

    # Write file to disk (streaming read in chunks to avoid OOM on large files)
    with open(video_path, "wb") as out:
        while True:
            chunk = await file.read(1 << 20)  # 1 MB chunks
            if not chunk:
                break
            out.write(chunk)

    v = Video(
        video_id=video_id,
        filename=filename,
        path=str(video_path.resolve()),
        index_status="pending",
        index_pct=0.0,
        created_at=time.time(),
        updated_at=time.time(),
    )
    store.save_video(v)

    if config.VISION_ENABLED:
        background_tasks.add_task(index_video, video_id, video_path.resolve())
    else:
        store.update_video_status(video_id, "skipped", 0.0)

    return {"video_id": video_id, "filename": filename, "status": "pending"}


# ── Video list ─────────────────────────────────────────────────────────────────

@router.get("/videos")
def list_videos_endpoint():
    """Return all uploaded videos with their index status."""
    return [v.model_dump() for v in store.list_videos()]


# ── Index status ───────────────────────────────────────────────────────────────

@router.get("/videos/{video_id}/status")
def video_status(video_id: str):
    """Return indexing status, progress percentage, and shot count."""
    v = store.get_video(video_id)
    if not v:
        raise HTTPException(404, "Video not found")
    shots = store.get_shots(video_id)
    return {
        "video_id": video_id,
        "filename": v.filename,
        "status": v.index_status,
        "pct": v.index_pct,
        "shot_count": len(shots),
        "fps": v.fps,
        "duration_sec": v.duration_sec,
        "width": v.width,
        "height": v.height,
    }


# ── Re-index ───────────────────────────────────────────────────────────────────

@router.post("/videos/{video_id}/reindex")
def reindex_video(video_id: str, background_tasks: BackgroundTasks):
    """Drop existing shots and re-run the full indexing pipeline."""
    v = store.get_video(video_id)
    if not v:
        raise HTTPException(404, "Video not found")
    store.delete_shots(video_id)
    store.update_video_status(video_id, "pending", 0.0)
    if config.VISION_ENABLED:
        background_tasks.add_task(index_video, video_id, Path(v.path))
    return {"status": "reindexing", "video_id": video_id}


# ── Shot list ──────────────────────────────────────────────────────────────────

@router.get("/videos/{video_id}/shots")
def list_shots(video_id: str, request: Request):
    """Return the detected shot list with thumbnail URLs."""
    v = store.get_video(video_id)
    if not v:
        raise HTTPException(404, "Video not found")
    shots = store.get_shots(video_id)
    base_url = str(request.base_url).rstrip("/")
    result = []
    for s in shots:
        thumb_url = None
        if s.keyframe_path and Path(s.keyframe_path).exists():
            thumb_url = f"{base_url}/api/videos/{video_id}/thumb/{s.id}"
        result.append({
            "shot_id": s.id,
            "shot_index": s.shot_index,
            "start_sec": s.start_sec,
            "end_sec": s.end_sec,
            "caption": s.caption,
            "thumb_url": thumb_url,
        })
    return result


# ── Thumbnail serve ────────────────────────────────────────────────────────────

@router.get("/videos/{video_id}/thumb/{shot_id}")
def get_thumbnail(video_id: str, shot_id: str):
    """Serve the 320px JPEG thumbnail for a shot."""
    shot = store.get_shot(shot_id)
    if not shot or shot.video_id != video_id:
        raise HTTPException(404, "Shot not found")
    if not shot.keyframe_path:
        raise HTTPException(404, "No thumbnail for this shot")
    path = Path(shot.keyframe_path)
    if not path.exists():
        raise HTTPException(404, "Thumbnail file missing")
    return FileResponse(str(path), media_type="image/jpeg")


# ── Video streaming (HTTP Range requests) ─────────────────────────────────────

_MEDIA_TYPES: dict[str, str] = {
    ".mp4":  "video/mp4",
    ".mov":  "video/quicktime",
    ".webm": "video/webm",
    ".avi":  "video/x-msvideo",
    ".mkv":  "video/x-matroska",
    ".m4v":  "video/mp4",
}


@router.get("/videos/{video_id}/stream")
def stream_video(video_id: str, request: Request):
    """
    Stream video with HTTP Range support so browsers can seek.

    A GET with no Range header streams the whole file.
    A GET with Range: bytes=N-M returns HTTP 206 with the slice.
    The browser's <video> element issues Range requests automatically.
    """
    v = store.get_video(video_id)
    if not v:
        raise HTTPException(404, "Video not found")
    video_path = Path(v.path)
    if not video_path.exists():
        raise HTTPException(404, "Video file not found on disk")

    file_size = video_path.stat().st_size
    suffix = video_path.suffix.lower()
    media_type = _MEDIA_TYPES.get(suffix, "video/mp4")

    range_header = request.headers.get("Range")

    if not range_header:
        # Full-file response with Accept-Ranges header so the browser knows it can seek
        def _iter_full():
            with open(video_path, "rb") as fh:
                while True:
                    chunk = fh.read(1 << 16)  # 64 KB
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(
            _iter_full(),
            status_code=200,
            media_type=media_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )

    # Parse Range: bytes=start-end
    try:
        range_val = range_header.strip()
        if not range_val.startswith("bytes="):
            raise ValueError("unsupported range unit")
        range_val = range_val[len("bytes="):]
        parts = range_val.split("-", 1)
        start = int(parts[0]) if parts[0].strip() else 0
        end = int(parts[1]) if len(parts) > 1 and parts[1].strip() else file_size - 1
    except (ValueError, IndexError) as exc:
        raise HTTPException(400, f"Invalid Range header: {exc}")

    end = min(end, file_size - 1)
    if start > end or start < 0 or start >= file_size:
        raise HTTPException(
            416,
            "Range Not Satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    length = end - start + 1

    def _iter_range():
        with open(video_path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(1 << 16, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        _iter_range(),
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        },
    )


# ── Meeting ↔ Video link ───────────────────────────────────────────────────────

class VideoLinkPayload(BaseModel):
    video_id: str | None = None   # null = unlink


@router.put("/meetings/{meeting_id}/video")
def link_video_to_meeting(
    meeting_id: str,
    payload: VideoLinkPayload,
    background_tasks: BackgroundTasks,
):
    """
    Link (or unlink) a video_id to a meeting.
    On webhook arrival the pipeline auto-links the latest indexed video;
    this endpoint lets the UI override or correct that link.
    """
    if not store.get_transcript(meeting_id):
        raise HTTPException(404, "Meeting not found")
    if payload.video_id is not None:
        v = store.get_video(payload.video_id)
        if not v:
            raise HTTPException(404, "Video not found")

    store.link_video_to_meeting(meeting_id, payload.video_id)  # type: ignore[arg-type]

    if payload.video_id:
        video = store.get_video(payload.video_id)
        if video and video.index_status == "done" and Path(video.path).exists():
            detections = store.get_detections(payload.video_id)
            context = store.get_video_context(payload.video_id)
            if detections and (not context or context.get("global_summary") == "No video context available."):
                from backend.app.video_context import build_video_context
                background_tasks.add_task(build_video_context, payload.video_id)
            elif not detections:
                background_tasks.add_task(_run_detector_context, payload.video_id, Path(video.path))

    return {"status": "ok", "meeting_id": meeting_id, "video_id": payload.video_id}


def _run_detector_context(video_id: str, video_path: Path) -> None:
    """Backfill detector data for videos indexed before the YOLO-first pipeline."""
    from backend.app.detector_pass import run_detector_pass
    from backend.app.video_context import build_video_context

    store.update_video_status(video_id, "running", 0.0)
    try:
        run_detector_pass(video_id, video_path)
        build_video_context(video_id)
        store.update_video_status(video_id, "done", 100.0)
    except Exception:
        store.update_video_status(video_id, "failed", 0.0)
        raise
