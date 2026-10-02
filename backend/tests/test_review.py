"""
test_review.py – Integration tests for the review router (Sreedhar).
Uses FastAPI TestClient + MOCK data; no real DB, no real LLM.
"""
import json
import os
import tempfile
import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DB_PATH"] = _tmp_db.name
os.environ["MOCK_LLM"] = "1"
_tmp_db.close()

from fastapi.testclient import TestClient  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app import store  # noqa: E402
from backend.app.models import FeedbackItem, Transcript  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    store.init_db()
    yield


def _seed_meeting(mid="mtg-test"):
    t = Transcript(meeting_id=mid, title="Demo Meeting", segments=[])
    store.save_transcript(t)
    items = [
        FeedbackItem(
            id=f"{mid}-item-1",
            meeting_id=mid,
            quote="Too warm",
            note="Cool down",
            type="change",
            category="color",
            segment_start_sec=10.0,
            confidence=0.9,
        )
    ]
    store.save_items(mid, items)
    return mid


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Meetings
# ---------------------------------------------------------------------------

def test_list_meetings_empty():
    r = client.get("/api/meetings")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_meeting_not_found():
    r = client.get("/api/meetings/no-such-id")
    assert r.status_code == 404


def test_get_meeting_returns_transcript_items_settings():
    mid = _seed_meeting()
    r = client.get(f"/api/meetings/{mid}")
    assert r.status_code == 200
    data = r.json()
    assert "transcript" in data
    assert "items" in data
    assert "settings" in data
    assert data["transcript"]["meeting_id"] == mid
    assert len(data["items"]) == 1


# ---------------------------------------------------------------------------
# Items PATCH
# ---------------------------------------------------------------------------

def test_patch_item_updates_status():
    mid = _seed_meeting("patch-mtg")
    item_id = f"{mid}-item-1"
    r = client.patch(f"/api/items/{item_id}", json={"status": "approved"})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


def test_patch_item_not_found():
    r = client.patch("/api/items/ghost-id", json={"status": "approved"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Settings PUT
# ---------------------------------------------------------------------------

def test_put_settings():
    mid = _seed_meeting("settings-mtg")
    r = client.put(
        f"/api/meetings/{mid}/settings",
        json={"fps": 25.0, "start_timecode": "00:00:00:00", "sync_offset_sec": -1.5,
              "lookback_sec": 3.0, "version_label": "v2"},
    )
    assert r.status_code == 200
    assert r.json()["fps"] == 25.0


def test_put_settings_meeting_not_found():
    r = client.put(
        "/api/meetings/ghost/settings",
        json={"fps": 24.0, "start_timecode": "01:00:00:00",
              "sync_offset_sec": 0.0, "lookback_sec": 3.0, "version_label": "v1"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Reanchor / Reprocess – 503 because stubs raise NotImplementedError
# ---------------------------------------------------------------------------

def test_reanchor_success():
    mid = _seed_meeting("reanchor-mtg")
    r = client.post(f"/api/meetings/{mid}/reanchor")
    # Anchoring is now implemented, so this should return 200
    assert r.status_code == 200
    assert r.json() == {"reanchored": 1}


def test_reprocess_meeting_not_found():
    r = client.post("/api/meetings/no-such/reprocess")
    assert r.status_code == 404
