"""
test_vision_endpoints.py – API integration tests for Phase 3 vision context & edit instruction endpoints.
"""
from fastapi.testclient import TestClient
import pytest
from backend.app.main import app
from backend.app.models import FeedbackItem, Transcript, Video
from backend.app import store

client = TestClient(app)


def test_vision_endpoints(monkeypatch):
    from backend.app import config
    from backend.app.vision_pass import _mock_vision_descriptions
    from backend.app.video_context import build_video_context

    monkeypatch.setattr(config, "MOCK_VISION_LLM", True)
    monkeypatch.setattr(config, "MOCK_VISION", True)

    video_id = "vid-api-test-001"
    meeting_id = "meet-api-test-001"

    # Setup DB state
    store.save_video(Video(video_id=video_id, filename="test.mp4", path="test.mp4"))
    store.save_transcript(Transcript(meeting_id=meeting_id, segments=[]))
    _mock_vision_descriptions(video_id, duration_sec=30.0)
    build_video_context(video_id)


    item = FeedbackItem(
        id="item-api-01",
        meeting_id=meeting_id,
        quote="make the color pop on the red car",
        note="Boost color saturation",
        type="change",
        category="color",
        status="pending",
        segment_start_sec=14.0,
        anchor_sec=14.0,
    )
    store.save_items(meeting_id, [item])

    # 1. Trigger vision pass endpoint
    resp1 = client.post(f"/api/videos/{video_id}/vision")
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "enqueued"
    assert "YOLO" in resp1.json()["message"]

    # 2. Get vision status endpoint
    resp2 = client.get(f"/api/videos/{video_id}/vision/status")
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "completed"

    # 3. Generate edit instructions endpoint
    resp3 = client.post(f"/api/meetings/{meeting_id}/edits/generate", json={"video_id": video_id})
    assert resp3.status_code == 200
    edits = resp3.json()
    assert len(edits) >= 1
    inst_id = edits[0]["id"]

    # 4. Get edit instructions list endpoint
    resp4 = client.get(f"/api/meetings/{meeting_id}/edits")
    assert resp4.status_code == 200
    assert len(resp4.json()) >= 1

    # 5. Patch edit instruction endpoint
    resp5 = client.patch(f"/api/edits/{inst_id}", json={"status": "approved", "start_sec": 12.5})
    assert resp5.status_code == 200
    assert resp5.json()["status"] == "approved"
    assert resp5.json()["start_sec"] == 12.5

    # 6. Render preview clip endpoint
    resp6 = client.post(f"/api/edits/{inst_id}/preview")
    assert resp6.status_code == 200
    assert "preview_path" in resp6.json()


def test_video_context_rebuilds_empty_stale_context_from_detections(monkeypatch):
    video_id = "vid-stale-context-test"
    store.save_video(Video(video_id=video_id, filename="test.mp4", path="test.mp4"))
    store.save_video_context(video_id, {
        "global_summary": "No video context available.",
        "entity_keys": [],
        "scene_segments": [],
    })
    store.save_detections(video_id, [{
        "id": "stale-context-detection",
        "frame_index": 48,
        "time_sec": 12.0,
        "track_id": "track-stale-car",
        "class_name": "car",
        "color": "red",
        "confidence": 0.9,
        "bbox": [10, 10, 80, 80],
        "mask": None,
        "position": "center",
    }])

    response = client.get(f"/api/videos/{video_id}/context")

    assert response.status_code == 200
    assert response.json()["entity_keys"] == ["red car"]
