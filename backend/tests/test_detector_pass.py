from __future__ import annotations

import numpy as np
import pytest

from backend.app import config, store
from backend.app.detector_pass import _dominant_color, build_entity_index
from backend.app.models import Video


def test_dominant_color_uses_box_center():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    frame[25:75, 25:75] = (0, 0, 255)

    assert _dominant_color(frame, [0, 0, 100, 100]) == "red"


def test_detector_entity_index_merges_track_intervals_and_keeps_track_metadata():
    detections = [
        {"time_sec": 10.0, "track_id": "track-7", "class_name": "car", "color": "red", "confidence": 0.8, "position": "left"},
        {"time_sec": 10.5, "track_id": "track-7", "class_name": "car", "color": "red", "confidence": 0.9, "position": "left"},
        {"time_sec": 11.25, "track_id": "track-7", "class_name": "car", "color": "red", "confidence": 1.0, "position": "center"},
        {"time_sec": 13.0, "track_id": "track-7", "class_name": "car", "color": "red", "confidence": 0.8, "position": "center"},
    ]

    entities = build_entity_index(detections, detect_fps=4)

    assert len(entities) == 1
    entity = entities[0]
    assert entity["key"] == "red car"
    assert entity["class"] == "car"
    assert entity["color"] == "red"
    assert entity["track_ids"] == ["track-7"]
    assert entity["intervals"] == [
        {"start_sec": 10.0, "end_sec": 11.5},
        {"start_sec": 13.0, "end_sec": 13.25},
    ]
    assert entity["typical_position"] in {"left", "center"}
    assert entity["support_count"] == 4
    assert entity["confidence"] == pytest.approx(0.875)


def test_entity_color_uses_track_dominant_color():
    detections = [
        {"time_sec": 1.0, "track_id": "track-1", "class_name": "car", "color": "red", "confidence": 0.9},
        {"time_sec": 1.25, "track_id": "track-1", "class_name": "car", "color": "green", "confidence": 0.8},
        {"time_sec": 1.5, "track_id": "track-1", "class_name": "car", "color": "red", "confidence": 0.9},
    ]

    entities = build_entity_index(detections, detect_fps=4)

    assert len(entities) == 1
    assert entities[0]["key"] == "red car"
    assert entities[0]["color"] == "red"


def test_track_intervals_do_not_merge_a_full_one_second_gap():
    detections = [
        {"time_sec": 0.0, "track_id": "track-1", "class_name": "car", "color": "red", "confidence": 0.9},
        {"time_sec": 1.25, "track_id": "track-1", "class_name": "car", "color": "red", "confidence": 0.9},
    ]

    entities = build_entity_index(detections, detect_fps=4)

    assert len(entities[0]["intervals"]) == 2


def test_detection_observations_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "detector.db"))
    store.init_db()
    video_id = "detector-store-test"
    store.save_video(Video(video_id=video_id, filename="test.mp4", path="test.mp4"))
    detections = [{
        "id": "det-1",
        "frame_index": 3,
        "time_sec": 0.75,
        "track_id": "track-1",
        "class_name": "car",
        "color": "red",
        "confidence": 0.91,
        "bbox": [1.0, 2.0, 30.0, 40.0],
        "mask": [[1.0, 2.0], [3.0, 4.0]],
        "position": "left",
    }]

    store.save_detections(video_id, detections)

    stored = store.get_detections(video_id)
    assert len(stored) == 1
    assert stored[0]["bbox"] == detections[0]["bbox"]
    assert stored[0]["mask"] == detections[0]["mask"]
    assert stored[0]["position"] == "left"


def test_video_context_uses_detector_entities_without_vlm(tmp_path, monkeypatch):
    from backend.app.video_context import build_video_context

    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "context.db"))
    monkeypatch.setattr(config, "DETECT_FPS", 4)
    store.init_db()
    video_id = "detector-context-test"
    store.save_video(Video(video_id=video_id, filename="test.mp4", path="test.mp4"))
    store.save_detections(video_id, [{
        "id": "det-2",
        "frame_index": 48,
        "time_sec": 12.0,
        "track_id": "track-red-car",
        "class_name": "car",
        "color": "red",
        "confidence": 0.95,
        "bbox": [20.0, 20.0, 80.0, 80.0],
        "mask": None,
        "position": "center",
    }])

    context = build_video_context(video_id)

    assert context["entity_keys"] == ["red car"]
    assert context["scene_segments"][0]["key_objects"] == ["red car"]
    entity = store.get_entities(video_id)[0]
    assert entity["source"] == "detector"
    assert entity["track_ids"] == ["track-red-car"]


def test_text_llm_call_uses_shared_inference_lock(monkeypatch):
    from backend.app import llm

    class TrackingLock:
        active = False

        def __enter__(self):
            self.active = True

        def __exit__(self, exc_type, exc, traceback):
            self.active = False

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "locked"}}

    lock = TrackingLock()

    def fake_post(*args, **kwargs):
        assert lock.active
        return FakeResponse()

    monkeypatch.setattr(llm, "LOCAL_INFERENCE_LOCK", lock)
    monkeypatch.setattr(llm.httpx, "post", fake_post)

    assert llm._call_ollama("prompt", "", json_mode=False) == "locked"
    assert not lock.active