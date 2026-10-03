"""
eval_edit_effects.py – Evaluation script measuring entity-interval hit rate, edit instruction accuracy, and vision pass latency.
"""
import json
import sys
import time
from pathlib import Path

# Ensure root directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import config, store

from backend.app.models import FeedbackItem, Video
from backend.app.vision_pass import _mock_vision_descriptions
from backend.app.video_context import build_video_context
from backend.app.edit_instructions import generate_edit_instructions

EVAL_DIR = Path(__file__).parent
GT_PATH = EVAL_DIR / "ground_truth.json"


def evaluate():
    config.MOCK_LLM = True
    config.MOCK_VISION_LLM = True

    if not GT_PATH.exists():
        print(f"Error: Ground truth file not found at {GT_PATH}")
        return


    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))
    video_id = f"eval-{gt['video_id']}"
    meeting_id = f"meet-{gt['video_id']}"

    print("=" * 65)
    print("Frameline Phase 3 Evaluation Harness")
    print(f"Dataset       : {gt['video_id']}")
    print(f"Sample Count  : {len(gt['sample_comments'])}")
    print("=" * 65)

    # 1. Setup video & vision context
    store.save_video(Video(video_id=video_id, filename="eval.mp4", path="eval.mp4"))
    start_v = time.time()
    _mock_vision_descriptions(video_id, duration_sec=60.0)
    build_video_context(video_id)
    v_time = time.time() - start_v

    # 2. Evaluate Entity Interval Hit Rate
    entities = store.get_entities(video_id)
    gt_entities = gt.get("entities", [])
    entity_hits = 0

    for gte in gt_entities:
        key = gte["key"]
        found = next((e for e in entities if e["key"] == key), None)
        if found:
            # Check overlap of first interval
            if found.get("intervals") and gte.get("intervals"):
                f_iv = found["intervals"][0]
                g_iv = gte["intervals"][0]
                # Overlap check
                if max(f_iv["start_sec"], g_iv["start_sec"]) <= min(f_iv["end_sec"], g_iv["end_sec"]) + 2.0:
                    entity_hits += 1

    entity_hit_rate = (entity_hits / len(gt_entities)) * 100.0 if gt_entities else 100.0

    # 3. Evaluate Edit Instruction Accuracy
    sample_items = []
    for sc in gt["sample_comments"]:
        item = FeedbackItem(
            id=f"eval-item-{sc['id']}",
            meeting_id=meeting_id,
            quote=sc["quote"],
            note=sc["note"],
            type="change",
            category="color" if "color" in sc["quote"] else "edit",
            priority="high",
            segment_start_sec=sc["expected_start_sec"],
            anchor_sec=sc["expected_start_sec"],
        )
        sample_items.append(item)

    start_e = time.time()
    instructions = generate_edit_instructions(meeting_id, sample_items, video_id=video_id)
    e_time = time.time() - start_e

    correct_effect = 0
    correct_target = 0
    correct_interval = 0

    inst_map = {inst["item_id"]: inst for inst in instructions}

    for sc in gt["sample_comments"]:
        item_id = f"eval-item-{sc['id']}"
        inst = inst_map.get(item_id)
        if not inst:
            continue

        if inst["effect"] == sc["expected_effect"]:
            correct_effect += 1
        if inst.get("target_entity") == sc["expected_target"]:
            correct_target += 1
        if abs(inst["start_sec"] - sc["expected_start_sec"]) <= 3.0:
            correct_interval += 1

    total_samples = len(gt["sample_comments"])
    effect_acc = (correct_effect / total_samples) * 100.0
    target_acc = (correct_target / total_samples) * 100.0
    interval_acc = (correct_interval / total_samples) * 100.0

    print("\n" + "=" * 65)
    print("Evaluation Results Summary")
    print("=" * 65)
    print(f"Entity-Interval Hit Rate  : {entity_hit_rate:.1f}% ({entity_hits}/{len(gt_entities)})")
    print(f"Effect Name Accuracy     : {effect_acc:.1f}% ({correct_effect}/{total_samples})")
    print(f"Target Entity Accuracy   : {target_acc:.1f}% ({correct_target}/{total_samples})")
    print(f"Time Interval Accuracy   : {interval_acc:.1f}% ({correct_interval}/{total_samples})")
    print(f"Vision Processing Time   : {v_time:.3f} s")
    print(f"Edit Generation Time     : {e_time:.3f} s")
    print("=" * 65)


if __name__ == "__main__":
    evaluate()
