from typing import Literal
from pydantic import BaseModel, Field


class Segment(BaseModel):
    start_sec: float
    end_sec: float | None = None
    speaker: str | None = None
    text: str


class Transcript(BaseModel):
    meeting_id: str
    title: str | None = None
    segments: list[Segment]
    summary: str | None = None


class ProjectSettings(BaseModel):
    fps: float = 24.0
    start_timecode: str = "01:00:00:00"   # timeline start TC
    sync_offset_sec: float = 0.0          # video_time = meeting_time + offset
    lookback_sec: float = 3.0             # people describe what they saw a moment ago
    version_label: str = "v1"


# ── Vision models (Phase 2) ───────────────────────────────────────────────────

class CandidateShot(BaseModel):
    """One candidate grounding result returned alongside a FeedbackItem."""
    shot_id: str
    start_sec: float
    end_sec: float
    score: float
    thumb_url: str | None = None
    reason: str | None = None            # one-line LLM explanation


class Video(BaseModel):
    """A video file uploaded for indexing, decoupled from any single meeting."""
    video_id: str
    filename: str
    path: str                            # absolute path on disk
    fps: float | None = None
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    index_status: str = "pending"        # pending | running | done | failed | skipped
    index_pct: float = 0.0
    created_at: float | None = None
    updated_at: float | None = None


class Shot(BaseModel):
    """One detected shot within an indexed video."""
    id: str
    video_id: str
    shot_index: int
    start_sec: float
    end_sec: float
    keyframe_path: str | None = None     # absolute path to 320px-wide JPEG
    caption: str | None = None           # generated at index time


# ── Feedback item (extended for Phase 2) ─────────────────────────────────────

class FeedbackItem(BaseModel):
    id: str
    meeting_id: str
    quote: str                             # exact client words
    note: str                              # short actionable rewrite
    type: Literal["change", "question", "approval"]
    category: Literal["color", "sound", "pacing", "text_graphics", "edit", "other"]
    priority: Literal["high", "medium", "low"] = "medium"
    speaker: str | None = None
    segment_start_sec: float               # meeting-clock time of the quote
    spoken_timecode_sec: float | None = None
    anchor_sec: float | None = None        # video time in seconds (before start_timecode is added)
    anchor_source: Literal["spoken_timecode", "vision", "meeting_clock", "none"] = "none"
    is_global: bool = False                # applies to the whole piece, no single moment
    withdrawn: bool = False                # client later said "never mind"
    confidence: float = 0.5               # 0..1
    needs_review: bool = True
    status: Literal["pending", "approved", "rejected"] = "pending"
    # Phase 2 extensions — all optional so existing rows still deserialize
    visual_reference: str | None = None   # "logo reveal", "close-up of bottle"
    parent_id: str | None = None           # id of parent item when split from compound
    assignee_role: str | None = None       # from ProjectContext.roles
    shot_id: str | None = None             # best-matching shot from vision grounding
    candidates: list[CandidateShot] = Field(default_factory=list)  # top-3 candidates
