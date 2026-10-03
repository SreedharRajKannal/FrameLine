"""
eval_edit_effects.py – Evaluation script measuring entity-interval hit rate, edit instruction accuracy, and vision pass latency.
"""
import json
import os
import sys
import time
from pathlib import Path

# Ensure root directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import config, store

from backend.app.models import FeedbackItem, Video
from backend.app.detector_pass import build_entity_index, run_detector_pass
from backend.app.vision_pass import _mock_vision_descriptions
from backend.app.video_context import build_video_context, build_vlm_entity_index
from backend.app.edit_instructions import generate_edit_instructions

EVAL_DIR = Path(__file__).parent
GT_PATH = EVAL_DIR / "ground_truth.json"


def evaluate():
    os.environ["MOCK_LLM"] = "1"
    config.MOCK_LLM = True
    config.MOCK_VISION_LLM = True
    config.MOCK_VISION = True

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
    run_detector_pass(video_id, Path("eval.mp4"))
    build_video_context(video_id)
    v_time = time.time() - start_v

    # 2. Compare detector-only, VLM-only, and fused entity intervals.
    detector_entities = build_entity_index(store.get_detections(video_id), config.DETECT_FPS)
    vlm_entities = build_vlm_entity_index(store.get_frame_descriptions(video_id))
    entities = store.get_entities(video_id)
    gt_entities = gt.get("entities", [])

    def interval_hit_rate(predicted_entities):
        hits = 0
        for expected in gt_entities:
            expected_class = expected["key"].split()[-1]
            candidates = [
                entity for entity in predicted_entities
                if entity["key"] == expected["key"] or entity.get("class") == expected_class
            ]
            best_iou = 0.0
            for entity in candidates:
                for predicted in entity.get("intervals", []):
                    for target in expected.get("intervals", []):
                        intersection = max(0.0, min(predicted["end_sec"], target["end_sec"]) - max(predicted["start_sec"], target["start_sec"]))
                        union = max(predicted["end_sec"], target["end_sec"]) - min(predicted["start_sec"], target["start_sec"])
                        best_iou = max(best_iou, intersection / union if union > 0 else 0.0)
            if best_iou >= 0.5:
                hits += 1
        return hits, hits / len(gt_entities) * 100.0 if gt_entities else 100.0

    detector_hits, detector_hit_rate = interval_hit_rate(detector_entities)
    vlm_hits, vlm_hit_rate = interval_hit_rate(vlm_entities)
    entity_hits, entity_hit_rate = interval_hit_rate(entities)

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
    print(f"Detector Interval IoU>=0.5: {detector_hit_rate:.1f}% ({detector_hits}/{len(gt_entities)})")
    print(f"VLM-only Interval IoU>=0.5: {vlm_hit_rate:.1f}% ({vlm_hits}/{len(gt_entities)})")
    print(f"Fused Interval IoU>=0.5   : {entity_hit_rate:.1f}% ({entity_hits}/{len(gt_entities)})")
    print(f"Effect Name Accuracy     : {effect_acc:.1f}% ({correct_effect}/{total_samples})")
    print(f"Target Entity Accuracy   : {target_acc:.1f}% ({correct_target}/{total_samples})")
    print(f"Time Interval Accuracy   : {interval_acc:.1f}% ({correct_interval}/{total_samples})")
    print(f"Vision Processing Time   : {v_time:.3f} s")
    print(f"Edit Generation Time     : {e_time:.3f} s")
    print("=" * 65)


if __name__ == "__main__":
    evaluate()
