"""
tests/test_sivapriyan.py – Tests owned by Sivapriyan.

Covers:
  1. parse_spoken_time() – table-driven parser tests
  2. anchor_items()      – correct algorithm behaviour
  3. extract_feedback()  – MOCK_LLM=1 smoke test
  4. eval test           – extraction on review_call_1 vs expected_items
                           (MOCK_LLM=1; reports recall and precision)
  5. redact()            – basic PII detection
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure MOCK_LLM=1 for all tests (no Ollama required)
os.environ.setdefault("MOCK_LLM", "1")

from backend.app.anchoring import anchor_items, parse_spoken_time  # noqa: E402
from backend.app.extraction import extract_feedback  # noqa: E402
from backend.app.models import FeedbackItem, ProjectSettings, Segment, Transcript  # noqa: E402
from backend.app.redaction import redact, restore  # noqa: E402

# ── Paths ─────────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLES = _REPO_ROOT / "samples"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. parse_spoken_time – table tests
# ═══════════════════════════════════════════════════════════════════════════════

PARSER_CASES: list[tuple[str, float | None]] = [
    # Digital timecodes
    ("at 1:24 in the clip", 84.0),
    ("the bit at 0:30 looks off", 30.0),
    ("01:42:10 is the problem frame", 6130.0),
    ("00:00:45", 45.0),
    # "at N seconds"
    ("at 30 seconds", 30.0),
    ("at 90 seconds the music drops", 90.0),
    # "N minute[s] in"
    ("one minute in", 60.0),
    ("two minutes in is where it goes wrong", 120.0),
    # "around the N minute mark"
    ("around the 2 minute mark", 120.0),
    ("at the 1 minute mark", 60.0),
    # compound word-numbers
    ("two minutes forty", 160.0),
    ("one minute fifteen", 75.0),
    ("three minutes and twenty seconds", 200.0),
    # No match
    ("overall the video is too warm", None),
    ("somewhere in the middle", None),
    ("", None),
]


@pytest.mark.parametrize("text,expected", PARSER_CASES)
def test_parse_spoken_time(text: str, expected: float | None) -> None:
    result = parse_spoken_time(text)
    assert result == expected, f"parse_spoken_time({text!r}) = {result}, want {expected}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. anchor_items
# ═══════════════════════════════════════════════════════════════════════════════

def _make_item(**kwargs) -> FeedbackItem:
    defaults = dict(
        id="test-id",
        meeting_id="m1",
        quote="test quote",
        note="test note",
        type="change",
        category="other",
        segment_start_sec=100.0,
        confidence=0.9,
    )
    defaults.update(kwargs)
    return FeedbackItem(**defaults)


DEFAULT_SETTINGS = ProjectSettings(sync_offset_sec=0.0, lookback_sec=3.0)


def test_anchor_spoken_timecode():
    """spoken_timecode_sec takes priority."""
    item = _make_item(spoken_timecode_sec=84.0)
    [anchored] = anchor_items([item], DEFAULT_SETTINGS)
    assert anchored.anchor_sec == 84.0
    assert anchored.anchor_source == "spoken_timecode"
    assert not anchored.needs_review  # high confidence + spoken timecode


def test_anchor_global_item():
    """Global items get anchor_sec=None, anchor_source='none'."""
    item = _make_item(is_global=True, spoken_timecode_sec=None)
    [anchored] = anchor_items([item], DEFAULT_SETTINGS)
    assert anchored.anchor_sec is None
    assert anchored.anchor_source == "none"
    assert anchored.needs_review  # global always needs review


def test_anchor_meeting_clock():
    """Falls back to meeting clock with sync_offset and lookback."""
    item = _make_item(segment_start_sec=100.0, spoken_timecode_sec=None)
    settings = ProjectSettings(sync_offset_sec=5.0, lookback_sec=3.0)
    [anchored] = anchor_items([item], settings)
    # 100 + 5 - 3 = 102
    assert anchored.anchor_sec == pytest.approx(102.0)
    assert anchored.anchor_source == "meeting_clock"
    assert anchored.needs_review  # meeting_clock -> needs_review=True


def test_anchor_clamps_to_zero():
    """anchor_sec must never go negative."""
    item = _make_item(segment_start_sec=1.0, spoken_timecode_sec=None)
    settings = ProjectSettings(sync_offset_sec=0.0, lookback_sec=10.0)
    [anchored] = anchor_items([item], settings)
    assert anchored.anchor_sec == 0.0


def test_anchor_does_not_mutate_input():
    """anchor_items returns a new list; originals are unchanged."""
    item = _make_item(anchor_sec=None, anchor_source="none")
    anchor_items([item], DEFAULT_SETTINGS)
    assert item.anchor_sec is None  # original untouched


def test_anchor_needs_review_low_confidence():
    """Low confidence triggers needs_review even on spoken timecode."""
    item = _make_item(spoken_timecode_sec=30.0, confidence=0.5)
    [anchored] = anchor_items([item], DEFAULT_SETTINGS)
    assert anchored.needs_review


# ═══════════════════════════════════════════════════════════════════════════════
# 3. extract_feedback – MOCK_LLM=1 smoke test
# ═══════════════════════════════════════════════════════════════════════════════

def test_extract_feedback_mock():
    """MOCK_LLM=1 must return FeedbackItem objects without calling Ollama."""
    t = Transcript(
        meeting_id="review-call-001",
        segments=[Segment(start_sec=0.0, speaker="Rahul", text="This is a test.")],
    )
    with patch.dict(os.environ, {"MOCK_LLM": "1"}):
        items = extract_feedback(t)
    assert isinstance(items, list)
    assert len(items) > 0
    for it in items:
        assert isinstance(it, FeedbackItem)
        assert it.type in ("change", "question", "approval")
        assert it.category in ("color", "sound", "pacing", "text_graphics", "edit", "other")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Eval test: extraction on review_call_1 vs expected_items
# ═══════════════════════════════════════════════════════════════════════════════

def _load_review_call() -> Transcript:
    path = _SAMPLES / "review_call_1.json"
    if not path.exists():
        pytest.skip("samples/review_call_1.json not found")
    data = json.loads(path.read_text(encoding="utf-8"))
    return Transcript.model_validate(data)


def _load_expected() -> list[FeedbackItem]:
    path = _SAMPLES / "expected_items.json"
    if not path.exists():
        pytest.skip("samples/expected_items.json not found")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [FeedbackItem.model_validate(d) for d in data]


def _quote_key(quote: str) -> str:
    """Normalised key for loose matching."""
    return quote.strip().lower()[:50]


def test_extraction_eval_recall_precision():
    """
    Run extraction on review_call_1.json and report recall + precision
    against expected_items.json.

    Target: recall >= 0.70 (see Context.md section 7).
    With MOCK_LLM=1 we get 100% recall/precision (same file).
    With real LLM these numbers may differ.
    """
    transcript = _load_review_call()
    expected = _load_expected()

    with patch.dict(os.environ, {"MOCK_LLM": "1"}):
        predicted = extract_feedback(transcript)

    expected_keys = {_quote_key(e.quote) for e in expected}
    predicted_keys = {_quote_key(p.quote) for p in predicted}

    tp = len(expected_keys & predicted_keys)
    fp = len(predicted_keys - expected_keys)
    fn = len(expected_keys - predicted_keys)

    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0

    print(f"\n── Extraction eval (MOCK_LLM=1) ──")
    print(f"  Expected items : {len(expected)}")
    print(f"  Predicted items: {len(predicted)}")
    print(f"  TP={tp}  FP={fp}  FN={fn}")
    print(f"  Recall   : {recall:.0%}")
    print(f"  Precision: {precision:.0%}")

    # With MOCK_LLM=1 both must be 1.0; with real LLM recall target is 0.70
    TARGET_RECALL = 1.0 if os.getenv("MOCK_LLM", "0") == "1" else 0.70
    assert recall >= TARGET_RECALL, (
        f"Recall {recall:.0%} is below target {TARGET_RECALL:.0%}. "
        f"Missed items: {expected_keys - predicted_keys}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. redact() – basic PII detection
# ═══════════════════════════════════════════════════════════════════════════════

def test_redact_email():
    text = "Contact me at rahul.kapoor@glowskin.in for details."
    result = redact(text)
    assert "rahul.kapoor@glowskin.in" not in result.text
    assert "[Email 1]" in result.text
    assert result.mapping["[Email 1]"] == "rahul.kapoor@glowskin.in"


def test_redact_phone():
    text = "Call me at +91-98765-43210 anytime."
    result = redact(text)
    assert "+91-98765-43210" not in result.text
    assert any("Phone" in k for k in result.mapping)


def test_redact_money():
    text = "The budget is $15,000 for this project."
    result = redact(text)
    assert "$15,000" not in result.text
    assert any("Amount" in k for k in result.mapping)


def test_redact_money_spoken():
    text = "We paid fifteen thousand dollars for the shoot."
    result = redact(text)
    assert "fifteen thousand dollars" not in result.text.lower()
    assert any("Amount" in k for k in result.mapping)


def test_redact_consistent_placeholders():
    """Same value always gets the same placeholder."""
    text = "Email: foo@bar.com. Again: foo@bar.com."
    result = redact(text)
    assert result.text.count("[Email 1]") == 2
    assert len([k for k in result.mapping if "Email" in k]) == 1


def test_restore_reverses_redaction():
    text = "Send to rahul.kapoor@glowskin.in immediately."
    result = redact(text)
    restored = restore(result.text, result.mapping)
    assert restored == text
