"""
test_video_context.py – Unit tests for Phase 2 video context builder and entity index.
"""
import pytest
from backend.app import config, store
from backend.app.models import Video
from backend.app.vision_pass import _mock_vision_descriptions
from backend.app.video_context import build_video_context, get_relevant_context


def test_build_video_context_and_entity_resolution():
    video_id = "test-video-ctx-999"
    # Ensure video exists
    store.save_video(Video(video_id=video_id, filename="test.mp4", path="test.mp4"))

    # Generate mock descriptions including 'red car' at 12-18s
    _mock_vision_descriptions(video_id, duration_sec=30.0)

    # Build context
    ctx = build_video_context(video_id)
    assert ctx is not None
    assert "global_summary" in ctx
    assert len(ctx["scene_segments"]) > 0

    # Retrieve entities
    entities = store.get_entities(video_id)
    assert len(entities) > 0

    red_car = next((e for e in entities if e["key"] == "red car"), None)
    assert red_car is not None, "Entity 'red car' missing from entity index"
    assert len(red_car["intervals"]) > 0, "No time intervals found for 'red car'"

    # Verify 'red car' interval covers 12s - 18s window
    interval = red_car["intervals"][0]
    assert interval["start_sec"] <= 12.0
    assert interval["end_sec"] >= 18.0

    # Test get_relevant_context query resolution
    rel_ctx = get_relevant_context("make the color pop when the red car comes", video_id=video_id)
    assert "red car" in rel_ctx
    assert "12.0" in rel_ctx or "18.0" in rel_ctx
