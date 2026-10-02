from typing import Literal
from pydantic import BaseModel


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
    anchor_source: Literal["spoken_timecode", "meeting_clock", "none"] = "none"
    is_global: bool = False                # applies to the whole piece, no single moment
    withdrawn: bool = False                # client later said "never mind"
    confidence: float = 0.5               # 0..1
    needs_review: bool = True
    status: Literal["pending", "approved", "rejected"] = "pending"
