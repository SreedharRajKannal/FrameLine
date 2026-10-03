"""
tests/test_video_index.py – Unit tests for Phase 2 video indexing.
Owned by Sreedhar.

All tests use MOCK_VISION=1 so no real models, ffmpeg, or GPU is needed.
"""
from __future__ import annotations

import os
import time

import pytest

# Force mock mode for all tests in this file
os.environ["MOCK_VISION"] = "1"
os.environ["VISION_ENABLED"] = "1"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fresh_db(tmp_path, monkeypatch):
    """Point store.py at a fresh temporary SQLite file and initialise schema."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DB_PATH", db_path)
    # Force config to reload DB_PATH
    import importlib
    from backend.app import config
    monkeypatch.setattr(config, "DB_PATH", db_path)
    from backend.app import store
    store.init_db()
    return db_path


# ── ID helpers ─────────────────────────────────────────────────────────────────

class TestIdHelpers:
    def test_generate_video_id_is_uuid(self):
        from backend.app.video_index import generate_video_id
        import uuid
        vid = generate_video_id()
        uuid.UUID(vid)  # raises if not valid UUID

    def test_shot_id_deterministic(self):
        from backend.app.video_index import _make_shot_id
        assert _make_shot_id("v1", 0) == _make_shot_id("v1", 0)
        assert _make_shot_id("v1", 0) != _make_shot_id("v1", 1)

    def test_frame_id_deterministic(self):
        from backend.app.video_index import _make_frame_id
        assert _make_frame_id("s1", 1.0) == _make_frame_id("s1", 1.0)
        assert _make_frame_id("s1", 1.0) != _make_frame_id("s1", 2.0)


# ── Fixed segments fallback ────────────────────────────────────────────────────

class TestFixedSegments:
    def test_basic(self):
        from backend.app.video_index import _fixed_segments
        segs = _fixed_segments(30.0, seg_len=10.0)
        assert len(segs) == 3
        assert segs[0]["start_sec"] == 0.0
        assert segs[0]["end_sec"] == 10.0
        assert segs[-1]["end_sec"] == pytest.approx(30.0)

    def test_short_video(self):
        from backend.app.video_index import _fixed_segments
        segs = _fixed_segments(5.0, seg_len=10.0)
        assert len(segs) == 1
        assert segs[0]["end_sec"] == pytest.approx(5.0)

    def test_zero_duration(self):
        from backend.app.video_index import _fixed_segments
        segs = _fixed_segments(0.0)
        assert len(segs) == 1

    def test_segments_contiguous(self):
        from backend.app.video_index import _fixed_segments
        segs = _fixed_segments(25.0, seg_len=10.0)
        for i in range(len(segs) - 1):
            assert segs[i]["end_sec"] == pytest.approx(segs[i + 1]["start_sec"])


# ── Cap shots ─────────────────────────────────────────────────────────────────

class TestCapShots:
    def test_under_limit_unchanged(self):
        from backend.app.video_index import _cap_shots
        shots = [{"start_sec": i * 10.0, "end_sec": (i + 1) * 10.0} for i in range(5)]
        result = _cap_shots(shots, 10)
        assert len(result) == 5

    def test_over_limit_capped(self):
        from backend.app.video_index import _cap_shots
        shots = [{"start_sec": i * 5.0, "end_sec": (i + 1) * 5.0} for i in range(100)]
        result = _cap_shots(shots, 60)
        assert len(result) <= 60


# ── Mock indexing pipeline ─────────────────────────────────────────────────────

class TestMockIndex:
    def test_mock_creates_shots(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app import config, store
        monkeypatch.setattr(config, "MOCK_VISION", True)
        monkeypatch.setattr(config, "VIDEO_DATA_DIR", str(tmp_path / "videos"))

        from backend.app.video_index import generate_video_id
        from backend.app.models import Video

        video_id = generate_video_id()
        v = Video(
            video_id=video_id, filename="demo.mp4",
            path=str(tmp_path / "demo.mp4"),
            created_at=time.time(), updated_at=time.time(),
        )
        store.save_video(v)

        from backend.app.video_index import index_video
        index_video(video_id, tmp_path / "demo.mp4")

        v_updated = store.get_video(video_id)
        assert v_updated is not None
        assert v_updated.index_status == "done"
        assert v_updated.index_pct == 100.0

        shots = store.get_shots(video_id)
        assert len(shots) >= 1
        for s in shots:
            assert s.video_id == video_id
            assert s.end_sec > s.start_sec
            assert s.caption is not None  # mock always provides caption

    def test_mock_shot_captions_present(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app import config, store
        monkeypatch.setattr(config, "MOCK_VISION", True)
        monkeypatch.setattr(config, "VIDEO_DATA_DIR", str(tmp_path / "videos"))

        from backend.app.video_index import generate_video_id, index_video
        from backend.app.models import Video
        import time

        video_id = generate_video_id()
        store.save_video(Video(video_id=video_id, filename="x.mp4", path="x.mp4",
                               created_at=time.time(), updated_at=time.time()))
        index_video(video_id, tmp_path / "x.mp4")

        shots = store.get_shots(video_id)
        captions = [s.caption for s in shots if s.caption]
        assert len(captions) == len(shots), "All mock shots must have captions"

    def test_mock_index_generates_frame_context(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app import config, store
        monkeypatch.setattr(config, "MOCK_VISION", True)
        monkeypatch.setattr(config, "MOCK_VISION_LLM", True)
        monkeypatch.setattr(config, "VIDEO_DATA_DIR", str(tmp_path / "videos"))

        from backend.app.models import Video
        from backend.app.video_index import generate_video_id, index_video
        import time

        video_id = generate_video_id()
        store.save_video(Video(video_id=video_id, filename="x.mp4", path="x.mp4",
                               created_at=time.time(), updated_at=time.time()))

        index_video(video_id, tmp_path / "x.mp4")

        assert store.get_frame_descriptions(video_id)
        assert store.get_video_context(video_id) is not None

    def test_linking_video_after_import_triggers_context_generation(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app import config, store
        monkeypatch.setattr(config, "MOCK_VISION", True)
        monkeypatch.setattr(config, "MOCK_VISION_LLM", True)
        monkeypatch.setattr(config, "VIDEO_DATA_DIR", str(tmp_path / "videos"))

        from backend.app.models import Transcript, Video
        from backend.app.routers.video import VideoLinkPayload, link_video_to_meeting
        from backend.app.video_index import generate_video_id
        import time

        meeting_id = "m-late-link"
        tx = Transcript(meeting_id=meeting_id, title="Demo", segments=[])
        store.save_transcript(tx)

        video_path = tmp_path / "x.mp4"
        video_path.write_bytes(b"fake video")
        video_id = generate_video_id()
        store.save_video(Video(video_id=video_id, filename="x.mp4", path=str(video_path),
                               created_at=time.time(), updated_at=time.time()))

        calls = []
        class TaskCollector:
            def add_task(self, fn, *args, **kwargs):
                calls.append((fn, args, kwargs))

        link_video_to_meeting(
            meeting_id,
            VideoLinkPayload(video_id=video_id),
            background_tasks=TaskCollector(),
        )

        assert store.get_meeting_video_id(meeting_id) == video_id
        assert len(calls) == 1


# ── DB store round-trip ────────────────────────────────────────────────────────

class TestStoreRoundTrip:
    def test_save_and_get_video(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app import store
        from backend.app.models import Video

        v = Video(
            video_id="test-v-001", filename="test.mp4", path="/tmp/test.mp4",
            fps=25.0, duration_sec=120.0, width=1920, height=1080,
            index_status="done", index_pct=100.0,
            created_at=1000.0, updated_at=1001.0,
        )
        store.save_video(v)
        got = store.get_video("test-v-001")
        assert got is not None
        assert got.filename == "test.mp4"
        assert got.fps == pytest.approx(25.0)
        assert got.index_status == "done"

    def test_update_video_status(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app import store
        from backend.app.models import Video

        v = Video(video_id="v-002", filename="v.mp4", path="v.mp4",
                  created_at=1.0, updated_at=1.0)
        store.save_video(v)
        store.update_video_status("v-002", "running", 42.5)
        got = store.get_video("v-002")
        assert got.index_status == "running"
        assert got.index_pct == pytest.approx(42.5)

    def test_list_videos(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app import store
        from backend.app.models import Video

        for i in range(3):
            store.save_video(Video(video_id=f"v-{i}", filename=f"v{i}.mp4",
                                   path=f"v{i}.mp4", created_at=float(i), updated_at=float(i)))
        vids = store.list_videos()
        assert len(vids) == 3

    def test_save_and_get_shots(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app import store
        from backend.app.models import Shot, Video

        store.save_video(Video(video_id="v-shots", filename="v.mp4", path="v.mp4",
                               created_at=1.0, updated_at=1.0))
        shots = [
            Shot(id=f"shot-{i:04d}", video_id="v-shots", shot_index=i,
                 start_sec=i * 10.0, end_sec=(i + 1) * 10.0, caption=f"Caption {i}")
            for i in range(5)
        ]
        store.save_shots(shots)
        got = store.get_shots("v-shots")
        assert len(got) == 5
        assert got[0].shot_index == 0
        assert got[4].shot_index == 4

    def test_get_shot_by_id(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app import store
        from backend.app.models import Shot, Video

        store.save_video(Video(video_id="v-x", filename="v.mp4", path="v.mp4",
                               created_at=1.0, updated_at=1.0))
        s = Shot(id="my-shot-id", video_id="v-x", shot_index=0,
                 start_sec=0.0, end_sec=10.0, caption="A scene")
        store.save_shots([s])
        got = store.get_shot("my-shot-id")
        assert got is not None
        assert got.caption == "A scene"

    def test_delete_shots(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app import store
        from backend.app.models import Shot, Video

        store.save_video(Video(video_id="v-del", filename="v.mp4", path="v.mp4",
                               created_at=1.0, updated_at=1.0))
        store.save_shots([Shot(id="del-shot", video_id="v-del", shot_index=0,
                               start_sec=0.0, end_sec=5.0)])
        store.delete_shots("v-del")
        assert store.get_shots("v-del") == []

    def test_save_frame_embedding(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app import store
        from backend.app.models import Shot, Video
        import numpy as np

        store.save_video(Video(video_id="v-emb", filename="v.mp4", path="v.mp4",
                               created_at=1.0, updated_at=1.0))
        store.save_shots([Shot(id="shot-emb", video_id="v-emb", shot_index=0,
                               start_sec=0.0, end_sec=5.0)])
        emb = np.ones(512, dtype=np.float32).tobytes()
        store.save_frame_embedding("frame-001", "shot-emb", 2.5, emb)
        frames = store.get_frame_embeddings("v-emb")
        assert len(frames) == 1
        assert frames[0]["shot_id"] == "shot-emb"
        assert frames[0]["time_sec"] == pytest.approx(2.5)
        assert len(frames[0]["embedding_bytes"]) == 512 * 4  # float32

    def test_link_video_to_meeting(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app import store
        from backend.app.models import Transcript, Video

        t = Transcript(meeting_id="m-link", segments=[])
        store.save_transcript(t)
        v = Video(video_id="v-link", filename="v.mp4", path="v.mp4",
                  created_at=1.0, updated_at=1.0)
        store.save_video(v)

        assert store.get_meeting_video_id("m-link") is None
        store.link_video_to_meeting("m-link", "v-link")
        assert store.get_meeting_video_id("m-link") == "v-link"

    def test_get_latest_indexed_video(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app import store
        from backend.app.models import Video

        assert store.get_latest_indexed_video() is None

        store.save_video(Video(video_id="v-old", filename="old.mp4", path="old.mp4",
                               index_status="done", created_at=1.0, updated_at=1.0))
        store.save_video(Video(video_id="v-new", filename="new.mp4", path="new.mp4",
                               index_status="done", created_at=2.0, updated_at=2.0))
        store.save_video(Video(video_id="v-pending", filename="p.mp4", path="p.mp4",
                               index_status="pending", created_at=3.0, updated_at=3.0))

        latest = store.get_latest_indexed_video()
        assert latest == "v-new"  # most recent done video


# ── Shot sheet ─────────────────────────────────────────────────────────────────

class TestShotSheet:
    def test_shot_sheet_format(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app import store
        from backend.app.models import Shot, Video
        from backend.app.video_index import get_shot_sheet

        store.save_video(Video(video_id="v-sheet", filename="v.mp4", path="v.mp4",
                               created_at=1.0, updated_at=1.0))
        store.save_shots([
            Shot(id="s0", video_id="v-sheet", shot_index=0,
                 start_sec=0.0, end_sec=10.0, caption="Opening logo"),
            Shot(id="s1", video_id="v-sheet", shot_index=1,
                 start_sec=10.0, end_sec=70.0, caption="Product close-up"),
        ])
        sheet = get_shot_sheet("v-sheet")
        assert "Shot 1" in sheet
        assert "Shot 2" in sheet
        assert "Opening logo" in sheet
        assert "0:00" in sheet

    def test_shot_sheet_empty(self, tmp_path, monkeypatch):
        _fresh_db(tmp_path, monkeypatch)
        from backend.app.video_index import get_shot_sheet
        result = get_shot_sheet("nonexistent-video")
        assert "no shots indexed" in result
