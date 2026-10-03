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


def test_qwen_edit_generation_uses_context_and_keeps_explicit_time(monkeypatch):
    from backend.app import config, edit_instructions, vision_pass

    meeting_id = "meet-qwen-context-flow"
    video_id = "video-qwen-context-flow"
    store.save_video(Video(video_id=video_id, filename="review.mp4", path="review.mp4"))
    store.save_transcript(Transcript(meeting_id=meeting_id, segments=[]))
    store.link_video_to_meeting(meeting_id, video_id)
    store.save_entities(video_id, [{
        "key": "amber bottle",
        "name": "amber bottle",
        "color": "amber",
        "intervals": [{"start_sec": 0.0, "end_sec": 10.0}],
    }])
    store.save_items(meeting_id, [FeedbackItem(
        id="qwen-item-zoom-five",
        meeting_id=meeting_id,
        quote="Also add a zoom-in effect at five-second mark.",
        note="Zoom in on the bottle at five seconds.",
        type="change",
        category="edit",
        segment_start_sec=0.0,
        spoken_timecode_sec=5.0,
        anchor_sec=5.0,
    )])
    monkeypatch.setattr(config, "MOCK_LLM", False)
    monkeypatch.setattr(config, "MOCK_VISION_LLM", False)
    monkeypatch.setattr(edit_instructions, "get_relevant_context", lambda **kwargs: "MOCK_VIDEO_CONTEXT: bottle pickup")
    monkeypatch.setattr(vision_pass, "unload_ollama_model", lambda model_name: None)

    def fake_qwen(prompt, system=""):
        assert "MOCK_VIDEO_CONTEXT: bottle pickup" in prompt
        return {
            "effect": "zoom_in",
            "target_entity": "bottle",
            "start_sec": 0.0,
            "end_sec": 10.0,
            "params": {"factor": 1.2},
            "confidence": 0.9,
            "reason": "Zoom in on the bottle at the requested time.",
        }

    monkeypatch.setattr(edit_instructions, "call_llm_json", fake_qwen)

    response = client.post(
        f"/api/meetings/{meeting_id}/edits/generate",
        json={"video_id": video_id},
    )

    assert response.status_code == 200
    generated = response.json()
    assert len(generated) == 1
    assert generated[0]["effect"] == "zoom_in"
    assert generated[0]["start_sec"] == 5.0
    assert generated[0]["end_sec"] == 10.0
    assert generated[0]["target_entity"] == "bottle"

    patch_response = client.patch(
        f"/api/edits/{generated[0]['id']}",
        json={"status": "approved", "start_sec": 7.0, "end_sec": 10.0},
    )
    assert patch_response.status_code == 200
    updated_meeting = client.get(f"/api/meetings/{meeting_id}").json()
    updated_item = updated_meeting["items"][0]
    assert updated_item["status"] == "approved"
    assert updated_item["needs_review"] is False
    assert updated_item["anchor_sec"] == 7.0

    interval_response = client.patch(
        f"/api/edits/{generated[0]['id']}",
        json={"start_sec": 6.5, "end_sec": 9.0},
    )
    assert interval_response.status_code == 200
    assert interval_response.json()["start_sec"] == 6.5
    assert interval_response.json()["end_sec"] == 9.0
    refreshed_item = client.get(f"/api/meetings/{meeting_id}").json()["items"][0]
    assert refreshed_item["anchor_sec"] == 6.5


def test_global_edit_instruction_is_persisted_at_video_start(monkeypatch):
    from backend.app import config, edit_instructions, vision_pass

    meeting_id = "meet-global-edit-start"
    video_id = "video-global-edit-start"
    store.save_video(Video(
        video_id=video_id,
        filename="review.mp4",
        path="review.mp4",
        duration_sec=42.0,
    ))
    store.save_transcript(Transcript(meeting_id=meeting_id, segments=[]))
    store.link_video_to_meeting(meeting_id, video_id)
    store.save_items(meeting_id, [FeedbackItem(
        id="global-contrast-item",
        meeting_id=meeting_id,
        quote="Increase the contrast of the overall video.",
        note="Increase contrast throughout the video.",
        type="change",
        category="color",
        segment_start_sec=14.0,
        is_global=True,
    )])
    monkeypatch.setattr(config, "MOCK_LLM", False)
    monkeypatch.setattr(config, "MOCK_VISION_LLM", False)
    monkeypatch.setattr(edit_instructions, "get_relevant_context", lambda **kwargs: "Video context")
    monkeypatch.setattr(vision_pass, "unload_ollama_model", lambda model_name: None)
    monkeypatch.setattr(edit_instructions, "call_llm_json", lambda *args, **kwargs: {
        "effect": "contrast",
        "target_entity": "background",
        "start_sec": 14.0,
        "end_sec": 20.0,
        "params": {"factor": 1.2},
        "confidence": 0.9,
        "reason": "Increase contrast globally.",
    })

    response = client.post(
        f"/api/meetings/{meeting_id}/edits/generate",
        json={"video_id": video_id},
    )

    assert response.status_code == 200
    instruction = response.json()[0]
    assert instruction["is_global"] is True
    assert instruction["target_entity"] is None
    assert instruction["start_sec"] == 0.0
    assert instruction["end_sec"] == 42.0
    assert store.get_edit_instructions(meeting_id)[0]["is_global"] is True


def test_qwen_empty_result_is_returned_as_visible_api_error(monkeypatch):
    from backend.app.routers import vision

    meeting_id = "meet-qwen-empty-result"
    store.save_transcript(Transcript(meeting_id=meeting_id, segments=[]))
    store.save_items(meeting_id, [FeedbackItem(
        id="qwen-empty-item",
        meeting_id=meeting_id,
        quote="Increase the contrast of the overall video.",
        note="Increase contrast across the video.",
        type="change",
        category="color",
        segment_start_sec=14.0,
    )])
    monkeypatch.setattr(vision, "generate_edit_instructions", lambda **kwargs: [])

    response = client.post(f"/api/meetings/{meeting_id}/edits/generate", json={})

    assert response.status_code == 502
    assert "Qwen returned no edit instructions" in response.json()["detail"]


def test_edit_instruction_inherits_existing_item_approval(monkeypatch):
    from backend.app import config, edit_instructions, vision_pass

    meeting_id = "meet-inherit-edit-approval"
    video_id = "video-inherit-edit-approval"
    store.save_transcript(Transcript(meeting_id=meeting_id, segments=[]))
    store.save_video(Video(video_id=video_id, filename="review.mp4", path="review.mp4", duration_sec=20.0))
    store.link_video_to_meeting(meeting_id, video_id)
    store.save_items(meeting_id, [FeedbackItem(
        id="already-approved-feedback",
        meeting_id=meeting_id,
        quote="Slow the bottle pickup.",
        note="Slow the bottle pickup.",
        type="change",
        category="pacing",
        segment_start_sec=4.0,
        status="approved",
        needs_review=False,
    )])
    monkeypatch.setattr(config, "MOCK_LLM", False)
    monkeypatch.setattr(config, "MOCK_VISION_LLM", False)
    monkeypatch.setattr(edit_instructions, "get_relevant_context", lambda **kwargs: "Bottle is picked up at 4s.")
    monkeypatch.setattr(vision_pass, "unload_ollama_model", lambda model_name: None)
    monkeypatch.setattr(edit_instructions, "call_llm_json", lambda *args, **kwargs: {
        "effect": "speed",
        "target_entity": "bottle",
        "start_sec": 4.0,
        "end_sec": 8.0,
        "params": {"factor": 0.7},
        "confidence": 0.9,
        "reason": "Slow the bottle pickup.",
    })

    response = client.post(
        f"/api/meetings/{meeting_id}/edits/generate",
        json={"video_id": video_id},
    )

    assert response.status_code == 200
    assert response.json()[0]["status"] == "approved"
