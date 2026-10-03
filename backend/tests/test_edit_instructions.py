"""
test_edit_instructions.py – Golden unit tests for Phase 3 edit instructions and filter compiler.
"""
import pytest
from backend.app import config, store
from backend.app.models import FeedbackItem, Video
from backend.app.vision_pass import _mock_vision_descriptions
from backend.app.video_context import build_video_context
from backend.app.edit_instructions import (
    CLOSED_EFFECTS,
    compile_ffmpeg_filter,
    generate_edit_instructions,
)


def test_ffmpeg_filter_compiler():
    # Color pop
    f1 = compile_ffmpeg_filter("color_pop", {"saturation": 1.5, "contrast": 1.3})
    assert "eq=saturation=1.50:contrast=1.30" in f1

    # Saturation
    f2 = compile_ffmpeg_filter("saturation", {"factor": 1.8})
    assert "eq=saturation=1.80" in f2

    # Zoom in
    f3 = compile_ffmpeg_filter("zoom_in", {"factor": 1.25})
    assert "zoompan" in f3

    # Unknown effect rejected
    with pytest.raises(ValueError):
        compile_ffmpeg_filter("invalid_magic_effect", {})


def test_worked_example_color_pop_red_car(monkeypatch):
    monkeypatch.setattr(config, "MOCK_VISION_LLM", True)
    meeting_id = "meet-worked-example-101"
    video_id = "video-worked-example-101"

    # Save transcript meeting & video & mock descriptions (includes 'red car' at 12-18s)
    from backend.app.models import Transcript
    store.save_transcript(Transcript(meeting_id=meeting_id, segments=[]))
    store.save_video(Video(video_id=video_id, filename="car_review.mp4", path="car_review.mp4"))
    _mock_vision_descriptions(video_id, duration_sec=60.0)
    build_video_context(video_id)



    # Feedback item for worked example
    item = FeedbackItem(
        id="item-worked-car-01",
        meeting_id=meeting_id,
        quote="make the color pop when the red car comes",
        note="Boost saturation and contrast for red car scene",
        type="change",
        category="color",
        priority="high",
        segment_start_sec=14.0,
        anchor_sec=14.0,
    )

    instructions = generate_edit_instructions(meeting_id=meeting_id, items=[item], video_id=video_id)
    assert len(instructions) == 1, "Expected exactly 1 edit instruction"

    inst = instructions[0]
    assert inst["effect"] == "color_pop"
    assert inst["target_entity"] == "red car"
    assert inst["start_sec"] == 12.0
    assert 18.0 <= inst["end_sec"] <= 20.0

    assert inst["confidence"] >= 0.8
    assert "eq=saturation=" in inst["filter_string"]
    assert "contrast=" in inst["filter_string"]
