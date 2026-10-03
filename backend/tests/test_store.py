"""
test_store.py – Unit tests for store.py (Sreedhar).
Uses an in-memory / temp SQLite path so tests don't pollute the real DB.
"""
import json
import os
import tempfile
import pytest

# Point to a temp DB before importing anything that uses config
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DB_PATH"] = _tmp_db.name
_tmp_db.close()

from backend.app import store  # noqa: E402
from backend.app.models import FeedbackItem, ProjectSettings, Transcript  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Re-initialise the DB and clear tables before every test."""
    store.init_db()
    with store._get_conn() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in ["edit_instructions", "items", "settings", "meetings", "frame_descriptions", "video_context", "entities", "detections", "frames", "shots", "videos"]:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("PRAGMA foreign_keys = ON")
    yield





# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------

def _make_transcript(mid="mtg-001") -> Transcript:
    return Transcript(
        meeting_id=mid,
        title="Test Meeting",
        segments=[],
        summary="Summary text",
    )


def test_save_and_get_transcript():
    t = _make_transcript()
    store.save_transcript(t)
    got = store.get_transcript("mtg-001")
    assert got is not None
    assert got.meeting_id == "mtg-001"
    assert got.title == "Test Meeting"


def test_get_transcript_missing_returns_none():
    assert store.get_transcript("does-not-exist") is None


def test_save_transcript_upserts():
    t = _make_transcript()
    store.save_transcript(t)
    t2 = t.model_copy(update={"title": "Updated"})
    store.save_transcript(t2)
    got = store.get_transcript("mtg-001")
    assert got.title == "Updated"


def test_list_meetings():
    store.save_transcript(_make_transcript("a"))
    store.save_transcript(_make_transcript("b"))
    rows = store.list_meetings()
    ids = [r["meeting_id"] for r in rows]
    assert "a" in ids and "b" in ids


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

def _make_item(item_id="item-1", meeting_id="mtg-001") -> FeedbackItem:
    return FeedbackItem(
        id=item_id,
        meeting_id=meeting_id,
        quote="The colour is too warm",
        note="Cool the grade",
        type="change",
        category="color",
        segment_start_sec=10.0,
    )


def test_save_and_get_items():
    store.save_transcript(_make_transcript())
    items = [_make_item("i1"), _make_item("i2")]
    store.save_items("mtg-001", items)
    got = store.get_items("mtg-001")
    assert len(got) == 2
    assert got[0].id == "i1"


def test_save_items_replaces():
    store.save_transcript(_make_transcript())
    store.save_items("mtg-001", [_make_item("old")])
    store.save_items("mtg-001", [_make_item("new1"), _make_item("new2")])
    got = store.get_items("mtg-001")
    assert len(got) == 2
    assert got[0].id == "new1"


def test_update_item_partial_patch():
    store.save_transcript(_make_transcript())
    store.save_items("mtg-001", [_make_item()])
    updated = store.update_item("item-1", {"status": "approved", "note": "New note"})
    assert updated is not None
    assert updated.status == "approved"
    assert updated.note == "New note"
    # Other fields unchanged
    assert updated.type == "change"


def test_update_item_not_found_returns_none():
    assert store.update_item("nonexistent", {"status": "approved"}) is None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def test_get_settings_returns_defaults_when_absent():
    store.save_transcript(_make_transcript())
    s = store.get_settings("mtg-001")
    assert s.fps == 24.0
    assert s.start_timecode == "01:00:00:00"


def test_save_and_get_settings():
    store.save_transcript(_make_transcript())
    s = ProjectSettings(fps=25.0, start_timecode="00:00:00:00", sync_offset_sec=-2.5)
    store.save_settings("mtg-001", s)
    got = store.get_settings("mtg-001")
    assert got.fps == 25.0
    assert got.sync_offset_sec == -2.5


def test_save_settings_upserts():
    store.save_transcript(_make_transcript())
    store.save_settings("mtg-001", ProjectSettings(fps=24.0))
    store.save_settings("mtg-001", ProjectSettings(fps=30.0))
    got = store.get_settings("mtg-001")
    assert got.fps == 30.0
