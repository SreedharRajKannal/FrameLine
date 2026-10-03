"""
Tests for Karthik's modules:
  - Timecode round trips
  - EDL golden file
  - Signature accept/reject
  - Duplicate event ignored
  - Transcript parser cases

Owned by Karthik.
"""
import hashlib
import hmac as hmac_mod
import json
import time

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Timecode round-trip tests
# ---------------------------------------------------------------------------

class TestTimecode:
    """Test timecode conversions."""

    def test_seconds_to_timecode_zero(self):
        from backend.app.exporters.timecode import seconds_to_timecode
        # 0 seconds at start TC 01:00:00:00, 24fps => 01:00:00:00
        assert seconds_to_timecode(0.0, 24.0, "01:00:00:00") == "01:00:00:00"

    def test_seconds_to_timecode_one_second(self):
        from backend.app.exporters.timecode import seconds_to_timecode
        # 1 second at start TC 01:00:00:00, 24fps => 01:00:01:00
        assert seconds_to_timecode(1.0, 24.0, "01:00:00:00") == "01:00:01:00"

    def test_seconds_to_timecode_fractional(self):
        from backend.app.exporters.timecode import seconds_to_timecode
        # 1.5 seconds at 24fps = 36 frames from start
        # 01:00:00:00 + 36 frames = 01:00:01:12
        assert seconds_to_timecode(1.5, 24.0, "01:00:00:00") == "01:00:01:12"

    def test_seconds_to_timecode_large(self):
        from backend.app.exporters.timecode import seconds_to_timecode
        # 3661 seconds = 1h 1m 1s => 01:00:00:00 + 01:01:01:00 = 02:01:01:00
        assert seconds_to_timecode(3661.0, 24.0, "01:00:00:00") == "02:01:01:00"

    def test_seconds_to_timecode_30fps(self):
        from backend.app.exporters.timecode import seconds_to_timecode
        # 0.5 seconds at 30fps = 15 frames => 01:00:00:15
        assert seconds_to_timecode(0.5, 30.0, "01:00:00:00") == "01:00:00:15"

    def test_round_trip_24fps(self):
        from backend.app.exporters.timecode import seconds_to_timecode, timecode_to_seconds
        for sec in [0.0, 1.0, 10.0, 60.0, 120.5, 3661.0]:
            tc = seconds_to_timecode(sec, 24.0, "01:00:00:00")
            back = timecode_to_seconds(tc, 24.0, "01:00:00:00")
            # Due to frame quantization, the round trip should be close
            assert abs(back - sec) < (1.0 / 24.0), f"Round trip failed for {sec}: {tc} -> {back}"

    def test_round_trip_25fps(self):
        from backend.app.exporters.timecode import seconds_to_timecode, timecode_to_seconds
        for sec in [0.0, 1.0, 30.0, 120.0]:
            tc = seconds_to_timecode(sec, 25.0, "00:00:00:00")
            back = timecode_to_seconds(tc, 25.0, "00:00:00:00")
            assert abs(back - sec) < (1.0 / 25.0)

    def test_round_trip_30fps(self):
        from backend.app.exporters.timecode import seconds_to_timecode, timecode_to_seconds
        for sec in [0.0, 0.5, 1.0, 59.0, 3600.0]:
            tc = seconds_to_timecode(sec, 30.0, "01:00:00:00")
            back = timecode_to_seconds(tc, 30.0, "01:00:00:00")
            assert abs(back - sec) < (1.0 / 30.0)

    def test_zero_start_timecode(self):
        from backend.app.exporters.timecode import seconds_to_timecode
        assert seconds_to_timecode(0.0, 24.0, "00:00:00:00") == "00:00:00:00"
        assert seconds_to_timecode(1.0, 24.0, "00:00:00:00") == "00:00:01:00"

    def test_frames_seconds_round_trip(self):
        from backend.app.exporters.timecode import seconds_to_frames, frames_to_seconds
        for fps in [24.0, 25.0, 30.0]:
            for sec in [0.0, 1.0, 10.5, 100.0]:
                frames = seconds_to_frames(sec, fps)
                back = frames_to_seconds(frames, fps)
                assert abs(back - sec) < (1.0 / fps)


# ---------------------------------------------------------------------------
# EDL golden file test
# ---------------------------------------------------------------------------

class TestEDL:
    """Test EDL export."""

    def test_build_edl_basic(self):
        from backend.app.exporters.edl import build_edl
        from backend.app.models import FeedbackItem, ProjectSettings

        settings = ProjectSettings(fps=24.0, start_timecode="01:00:00:00", version_label="v1")
        items = [
            FeedbackItem(
                id="item-1", meeting_id="m1",
                quote="Too warm", note="Cool down color grade",
                type="change", category="color", priority="high",
                speaker="Client", segment_start_sec=120.0,
                anchor_sec=10.0, anchor_source="meeting_clock",
                status="approved", withdrawn=False, confidence=0.9,
            ),
            FeedbackItem(
                id="item-2", meeting_id="m1",
                quote="Music too loud", note="Lower music bed",
                type="change", category="sound", priority="high",
                speaker="Client", segment_start_sec=300.0,
                is_global=True, anchor_source="none",
                status="approved", withdrawn=False, confidence=0.95,
            ),
            FeedbackItem(
                id="item-3", meeting_id="m1",
                quote="Looks great", note="Approved",
                type="approval", category="pacing", priority="low",
                speaker="Client", segment_start_sec=500.0,
                anchor_sec=490.0, anchor_source="meeting_clock",
                status="approved", withdrawn=False, confidence=0.99,
            ),
        ]

        edl = build_edl(items, settings, "Test Project")
        lines = edl.strip().split("\n")

        # Check header
        assert lines[0] == "TITLE: Test Project - v1"
        assert lines[1] == "FCM: NON-DROP FRAME"

        # Check that we have 3 events (each is event_line + comment_line + blank)
        event_lines = [l for l in lines if l.startswith("0")]
        assert len(event_lines) == 3

        # Check colors in comment lines
        comment_lines = [l for l in lines if l.startswith("|C:")]
        assert "ResolveColorRed" in comment_lines[0]    # global change = Red
        assert "ResolveColorRed" in comment_lines[1]   # timed change = Red
        assert "ResolveColorGreen" in comment_lines[2]  # approval = Green

        # Check global item has [GLOBAL] in marker name
        assert "[GLOBAL]" in comment_lines[0]

    def test_global_marker_is_first_in_edl(self):
        from backend.app.exporters.edl import build_edl
        from backend.app.models import FeedbackItem, ProjectSettings

        global_item = FeedbackItem(
            id="global-first",
            meeting_id="global-order",
            quote="Increase the overall contrast.",
            note="Increase contrast throughout the video.",
            type="change",
            category="color",
            segment_start_sec=12.0,
            is_global=True,
            status="approved",
        )
        timed_item = FeedbackItem(
            id="timed-second",
            meeting_id="global-order",
            quote="Zoom in at five seconds.",
            note="Zoom at five seconds.",
            type="change",
            category="edit",
            segment_start_sec=0.0,
            anchor_sec=5.0,
            status="approved",
        )

        edl = build_edl([timed_item, global_item], ProjectSettings(), "Test")
        comments = [line for line in edl.splitlines() if line.startswith("|C:")]

        assert "[GLOBAL]" in comments[0]
        assert "[GLOBAL]" not in comments[1]
        assert "|D:1" in comments[0]

    def test_build_edl_filters_non_approved(self):
        from backend.app.exporters.edl import build_edl
        from backend.app.models import FeedbackItem, ProjectSettings

        settings = ProjectSettings()
        items = [
            FeedbackItem(
                id="item-1", meeting_id="m1",
                quote="q", note="n", type="change", category="color",
                speaker="Client", segment_start_sec=10.0,
                status="pending", withdrawn=False, confidence=0.5,
            ),
            FeedbackItem(
                id="item-2", meeting_id="m1",
                quote="q", note="n", type="change", category="color",
                speaker="Client", segment_start_sec=10.0,
                status="approved", withdrawn=True, confidence=0.5,
            ),
        ]

        edl = build_edl(items, settings, "Test")
        # No event lines should be present (both are filtered out)
        event_lines = [l for l in edl.strip().split("\n") if l.startswith("0")]
        assert len(event_lines) == 0

    def test_build_edl_question_blue(self):
        from backend.app.exporters.edl import build_edl
        from backend.app.models import FeedbackItem, ProjectSettings

        settings = ProjectSettings()
        items = [
            FeedbackItem(
                id="item-1", meeting_id="m1",
                quote="q", note="n", type="question", category="other",
                speaker="Client", segment_start_sec=10.0,
                anchor_sec=5.0, anchor_source="meeting_clock",
                status="approved", withdrawn=False, confidence=0.9,
            ),
        ]

        edl = build_edl(items, settings, "Test")
        assert "ResolveColorBlue" in edl


# ---------------------------------------------------------------------------
# Webhook signature tests
# ---------------------------------------------------------------------------

class TestWebhookSignature:
    """Test HMAC signature verification."""

    def _make_signed_request(self, secret, body_dict, meeting_id="mock-meeting-001"):
        """Helper to create a signed webhook request payload."""
        body = json.dumps(body_dict, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        mac = hmac_mod.new(
            secret.encode(),
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        signature = f"sha256={mac}"
        return body, timestamp, signature

    def test_valid_signature_accepted(self):
        from backend.app.routers.ingest import _verify_signature

        secret = "test-secret-123"
        body = b'{"event_id":"e1","event":"summary.completed"}'
        timestamp = str(int(time.time()))
        mac = hmac_mod.new(
            secret.encode(),
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        sig = f"sha256={mac}"

        assert _verify_signature(secret, timestamp, body, sig) is True

    def test_invalid_signature_rejected(self):
        from backend.app.routers.ingest import _verify_signature

        assert _verify_signature("secret", "123", b"body", "sha256=invalid") is False

    def test_wrong_secret_rejected(self):
        from backend.app.routers.ingest import _verify_signature

        secret = "correct-secret"
        body = b'{"test": true}'
        timestamp = str(int(time.time()))
        mac = hmac_mod.new(
            secret.encode(),
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        sig = f"sha256={mac}"

        # Verify with wrong secret
        assert _verify_signature("wrong-secret", timestamp, body, sig) is False

    def test_empty_secret_rejected(self):
        from backend.app.routers.ingest import _verify_signature
        assert _verify_signature("", "123", b"body", "sha256=abc") is False

    def test_empty_timestamp_rejected(self):
        from backend.app.routers.ingest import _verify_signature
        assert _verify_signature("secret", "", b"body", "sha256=abc") is False


# ---------------------------------------------------------------------------
# Duplicate event test
# ---------------------------------------------------------------------------

class TestDuplicateEvent:
    """Test event dedup in the ingest router."""

    def test_dedup_marks_and_detects(self):
        from backend.app.routers.ingest import _is_duplicate, _mark_processed

        test_id = f"test-dedup-{time.time()}"
        assert _is_duplicate(test_id) is False
        _mark_processed(test_id)
        assert _is_duplicate(test_id) is True


# ---------------------------------------------------------------------------
# Transcript parser tests
# ---------------------------------------------------------------------------

class TestTranscriptParser:
    """Test parse_uploaded_transcript with various formats."""

    def test_json_our_format(self):
        from backend.app.ingest import parse_uploaded_transcript

        data = {
            "meeting_id": "test-001",
            "title": "Test Meeting",
            "segments": [
                {"start_sec": 10.0, "end_sec": 20.0, "speaker": "Client", "text": "Hello"},
                {"start_sec": 25.0, "speaker": "Host", "text": "Hi there"},
            ]
        }
        content = json.dumps(data).encode()
        t = parse_uploaded_transcript("test.json", content)

        assert t.meeting_id == "test-001"
        assert t.title == "Test Meeting"
        assert len(t.segments) == 2
        assert t.segments[0].start_sec == 10.0
        assert t.segments[0].speaker == "Client"

    def test_json_meetily_export_format(self):
        from backend.app.ingest import parse_uploaded_transcript

        data = {
            "meeting": {"id": "meetily-001", "title": "Exported Meeting"},
            "transcript": {
                "segments": [
                    {"start": 5.0, "end": 10.0, "speaker": "Alice", "text": "Testing"},
                ]
            },
            "summary": "A test summary",
        }
        content = json.dumps(data).encode()
        t = parse_uploaded_transcript("export.json", content)

        assert t.meeting_id == "meetily-001"
        assert t.title == "Exported Meeting"
        assert len(t.segments) == 1
        assert t.segments[0].start_sec == 5.0
        assert t.summary == "A test summary"

    def test_text_bracketed_timestamp(self):
        from backend.app.ingest import parse_uploaded_transcript

        text = (
            "[00:01:24] Speaker A: This is the first line\n"
            "[00:02:30] Speaker B: And this is the second\n"
        )
        t = parse_uploaded_transcript("notes.txt", text.encode())

        assert len(t.segments) == 2
        assert t.segments[0].start_sec == 84.0  # 1*60 + 24
        assert t.segments[0].speaker == "Speaker A"
        assert t.segments[0].text == "This is the first line"
        assert t.segments[1].start_sec == 150.0  # 2*60 + 30

    def test_multiline_timestamp_speaker_transcript(self):
        from backend.app.ingest import parse_uploaded_transcript

        text = (
            "[00:00]\n\nSpeaker 1\n"
            "Slow the video when the bottle is being picked up. Also add a zoom-in effect at five-second mark.\n\n"
            "[00:12]\n\nSpeaker 1\nAnd also\n\n"
            "[00:14]\n\nSpeaker 1\nIncrease the contrast of the overall video.\n\n"
            "[00:14]\n\nHost\nin\n"
        )

        transcript = parse_uploaded_transcript("review.txt", text.encode())

        assert [(s.start_sec, s.speaker) for s in transcript.segments] == [
            (0.0, "Speaker 1"),
            (12.0, "Speaker 1"),
            (14.0, "Speaker 1"),
            (14.0, "Host"),
        ]
        assert "five-second mark" in transcript.segments[0].text
        from backend.app.anchoring import parse_spoken_time
        assert parse_spoken_time(transcript.segments[0].text) == 5.0

    def test_text_plain_timestamp(self):
        from backend.app.ingest import parse_uploaded_transcript

        text = "00:01:24 Speaker: text here\n"
        t = parse_uploaded_transcript("notes.txt", text.encode())

        assert len(t.segments) == 1
        assert t.segments[0].start_sec == 84.0
        assert t.segments[0].speaker == "Speaker"
        assert t.segments[0].text == "text here"

    def test_text_no_speaker(self):
        from backend.app.ingest import parse_uploaded_transcript

        # When there's no speaker label, just timestamp and text
        # This tests lines like "00:01:24 some text without speaker colon"
        text = "[00:00:10] Hello world\n"
        t = parse_uploaded_transcript("notes.txt", text.encode())

        assert len(t.segments) == 1
        assert t.segments[0].start_sec == 10.0

    def test_empty_file(self):
        from backend.app.ingest import parse_uploaded_transcript

        t = parse_uploaded_transcript("empty.txt", b"")
        assert len(t.segments) == 0

    def test_markdown_with_timestamps(self):
        from backend.app.ingest import parse_uploaded_transcript

        text = (
            "# Client Review Call\n"
            "\n"
            "[00:01:00] Client: The colors are off\n"
            "[00:02:00] Editor: I'll fix that\n"
        )
        t = parse_uploaded_transcript("review.md", text.encode())

        assert t.title == "Client Review Call"
        assert len(t.segments) == 2

    def test_json_invalid_raises(self):
        from backend.app.ingest import parse_uploaded_transcript

        with pytest.raises((ValueError, json.JSONDecodeError)):
            parse_uploaded_transcript("bad.json", b"not json")


# ---------------------------------------------------------------------------
# CSV export tests
# ---------------------------------------------------------------------------

class TestCSVExport:
    """Test CSV export."""

    def test_build_csv_basic(self):
        from backend.app.exporters.csv_export import build_csv
        from backend.app.models import FeedbackItem, ProjectSettings

        settings = ProjectSettings(fps=24.0, start_timecode="01:00:00:00", version_label="v2")
        items = [
            FeedbackItem(
                id="item-1", meeting_id="m1",
                quote="Too warm", note="Cool down",
                type="change", category="color", priority="high",
                speaker="Client", segment_start_sec=120.0,
                anchor_sec=10.0, anchor_source="meeting_clock",
                status="approved", withdrawn=False, confidence=0.9,
            ),
        ]

        csv_str = build_csv(items, settings)
        lines = csv_str.strip().split("\n")

        # Header + 1 data row
        assert len(lines) == 2
        assert "id,timecode,type,category,priority,note,quote,speaker,confidence,status,version" in lines[0]
        assert "v2" in lines[1]
        assert "item-1" in lines[1]
