"""
test_vision_pass.py – Unit tests for Phase 1 vision pass.
"""
import os
import pytest
from pathlib import Path
from backend.app import config, store
from backend.app.vision_pass import run_vision_pass, _mock_vision_descriptions


def test_mock_vision_descriptions():
    video_id = "test-video-mock-123"
    results = _mock_vision_descriptions(video_id, duration_sec=30.0)
    assert len(results) > 0

    # Verify store retrieval
    stored = store.get_frame_descriptions(video_id)
    assert len(stored) == len(results)

    # Verify the worked example entity 'red car' exists around 12-18s
    red_car_found = False
    for item in stored:
        t = item["time_sec"]
        if 12.0 <= t <= 18.0:
            objects = item["data"].get("objects", [])
            names = [o["name"] for o in objects]
            if "red car" in names:
                red_car_found = True
                break
    assert red_car_found, "Red car object missing from 12-18s window in mock vision descriptions"


def test_run_vision_pass_mock_mode(monkeypatch):
    monkeypatch.setattr(config, "MOCK_VISION_LLM", True)
    video_id = "test-video-pass-456"
    fake_path = Path("fake_video.mp4")

    progress_log = []
    def cb(pct, msg):
        progress_log.append((pct, msg))

    res = run_vision_pass(video_id, fake_path, progress_cb=cb)
    assert len(res) > 0
    assert len(progress_log) > 0
    assert progress_log[-1][0] == 100.0
