"""
test_preview_export.py – Unit tests for Phase 4 preview renderer and EDL marker export.
"""
from pathlib import Path
import pytest
from backend.app.models import FeedbackItem, ProjectSettings
from backend.app.preview_renderer import render_preview_clip
from backend.app.exporters.edl import build_edl


def test_preview_renderer_clip():
    fake_video = Path("non_existent_demo.mp4")
    inst = {
        "id": "test-preview-101",
        "effect": "color_pop",
        "start_sec": 12.0,
        "end_sec": 18.0,
        "filter_string": "eq=saturation=1.4:contrast=1.25",
    }
    preview_path = render_preview_clip(fake_video, inst)
    assert preview_path is not None
    assert "preview_test-preview-101.mp4" in preview_path


def test_edl_export_with_effect_markers():
    settings = ProjectSettings(fps=24.0, start_timecode="01:00:00:00")
    item = FeedbackItem(
        id="item-edl-101",
        meeting_id="meet-edl-101",
        quote="make the color pop",
        note="Boost saturation on red car",
        type="change",
        category="color",
        status="approved",
        segment_start_sec=14.0,
        anchor_sec=14.0,
    )

    edit_inst = [
        {
            "id": "edit-101",
            "item_id": "item-edl-101",
            "meeting_id": "meet-edl-101",
            "effect": "color_pop",
            "target_entity": "red car",
            "start_sec": 12.0,
            "end_sec": 18.0,
            "status": "approved",
        }
    ]

    edl = build_edl([item], settings, "Test Project", edit_instructions=edit_inst)
    assert "TITLE: Test Project - v1" in edl
    assert "[COLOR POP] red car 0:12-0:18" in edl
    assert "|C:ResolveColorRed" in edl
