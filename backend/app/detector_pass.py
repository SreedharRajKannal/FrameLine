"""YOLO object tracking and detector-first entity indexing."""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from backend.app import config, store
from backend.app.model_lock import LOCAL_INFERENCE_LOCK

logger = logging.getLogger(__name__)
DETECTOR_LOCK = LOCAL_INFERENCE_LOCK


def _dominant_color(frame: Any, bbox: list[float]) -> str:
    """Estimate a named color from the central half of a detection box."""
    import cv2
    import numpy as np

    height, width = frame.shape[:2]
    left, top, right, bottom = bbox
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    half_width = max(1, int((right - left) * 0.25))
    half_height = max(1, int((bottom - top) * 0.25))
    x0 = max(0, int(center_x) - half_width)
    x1 = min(width, int(center_x) + half_width)
    y0 = max(0, int(center_y) - half_height)
    y1 = min(height, int(center_y) + half_height)
    if x1 <= x0 or y1 <= y0:
        return "unknown"

    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0].reshape(-1)
    saturation = hsv[:, :, 1].reshape(-1)
    value = hsv[:, :, 2].reshape(-1)
    chromatic = saturation >= 55

    if float(chromatic.mean()) < 0.15:
        brightness = float(np.median(value))
        if brightness < 55:
            return "black"
        if brightness > 205:
            return "white"
        return "gray"

    histogram, edges = np.histogram(hue[chromatic], bins=18, range=(0, 180))
    dominant_bin = int(histogram.argmax())
    hue_center = float((edges[dominant_bin] + edges[dominant_bin + 1]) / 2)
    if hue_center < 8 or hue_center >= 174:
        return "red"
    if hue_center < 20:
        return "orange"
    if hue_center < 34:
        return "yellow"
    if hue_center < 80:
        return "green"
    if hue_center < 100:
        return "cyan"
    if hue_center < 132:
        return "blue"
    if hue_center < 158:
        return "purple"
    return "pink"


def _position(bbox: list[float], frame_shape: tuple[int, ...]) -> str:
    frame_width = frame_shape[1]
    center_x = (bbox[0] + bbox[2]) / 2
    ratio = center_x / max(1, frame_width)
    if ratio < 1 / 3:
        return "left"
    if ratio > 2 / 3:
        return "right"
    return "center"


def _merge_times(times: list[float], sample_period: float, gap_sec: float = 1.0) -> list[dict[str, float]]:
    """Merge detection times into intervals, joining gaps shorter than gap_sec."""
    if not times:
        return []
    sorted_times = sorted(set(times))
    intervals = []
    start = previous = sorted_times[0]
    for current in sorted_times[1:]:
        if current - previous - sample_period < gap_sec:
            previous = current
            continue
        intervals.append({"start_sec": round(start, 2), "end_sec": round(previous + sample_period, 2)})
        start = previous = current
    intervals.append({"start_sec": round(start, 2), "end_sec": round(previous + sample_period, 2)})
    return intervals


def _merge_intervals(intervals: list[dict[str, float]], gap_sec: float = 1.0) -> list[dict[str, float]]:
    """Merge track intervals whose gap is at most gap_sec."""
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda interval: interval["start_sec"])
    merged = [dict(ordered[0])]
    for interval in ordered[1:]:
        current = merged[-1]
        if interval["start_sec"] < current["end_sec"] + gap_sec:
            current["end_sec"] = max(current["end_sec"], interval["end_sec"])
        else:
            merged.append(dict(interval))
    return [{key: round(value, 2) for key, value in interval.items()} for interval in merged]


def build_entity_index(detections: list[dict], detect_fps: float) -> list[dict]:
    """Aggregate tracked detections into canonical class/color entities."""
    from backend.app.video_context import _normalize_entity_key

    sample_period = 1.0 / max(detect_fps, 0.1)
    tracks: dict[str, list[dict]] = defaultdict(list)
    for detection in detections:
        tracks[detection["track_id"]].append(detection)

    groups: dict[str, list[tuple[str, str, str, dict]]] = defaultdict(list)
    for track_id, observations in tracks.items():
        detected_class = Counter(item["class_name"].strip().lower() for item in observations).most_common(1)[0][0]
        class_name = _normalize_entity_key(detected_class)
        color_counts = Counter(item.get("color") or "unknown" for item in observations)
        color = next((name for name, _ in color_counts.most_common() if name != "unknown"), "unknown")
        key = class_name if color == "unknown" else f"{color} {class_name}"
        groups[key].extend((track_id, class_name, color, item) for item in observations)

    entities = []
    for key, track_observations in sorted(groups.items()):
        observations = [item for _, _, _, item in track_observations]
        times_by_track: dict[str, list[float]] = defaultdict(list)
        for track_id, _, _, observation in track_observations:
            times_by_track[track_id].append(observation["time_sec"])
        track_intervals = [
            interval
            for times in times_by_track.values()
            for interval in _merge_times(times, sample_period)
        ]
        intervals = _merge_intervals(track_intervals)
        positions = Counter(item["position"] for item in observations if item.get("position"))
        class_name = Counter(name for _, name, _, _ in track_observations).most_common(1)[0][0]
        color = Counter(name for _, _, name, _ in track_observations).most_common(1)[0][0]
        confidence = sum(float(item["confidence"]) for item in observations) / len(observations)
        track_ids = sorted({track_id for track_id, _, _, _ in track_observations})
        entities.append({
            "key": key,
            "name": key,
            "class": class_name,
            "color": color,
            "track_ids": track_ids,
            "intervals": intervals,
            "typical_position": positions.most_common(1)[0][0] if positions else None,
            "positions": sorted(positions),
            "support_count": len(observations),
            "support_times": sorted(item["time_sec"] for item in observations),
            "confidence": round(confidence, 4),
            "source": "detector",
        })
    return entities


def _glossary_prompts() -> list[str]:
    if not config.DETECTOR_GLOSSARY_PATH:
        return []
    path = Path(config.DETECTOR_GLOSSARY_PATH)
    if not path.is_file():
        logger.warning("Detector glossary not found: %s", path)
        return []
    try:
        content = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            loaded = json.loads(content)
            values = loaded.get("entities", loaded) if isinstance(loaded, dict) else loaded
            return [str(value).strip() for value in values if str(value).strip()]
        return [line.strip() for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Could not read detector glossary %s: %s", path, exc)
        return []


def _mock_detections(video_id: str, detect_fps: float) -> list[dict]:
    """Deterministic detector fixture for tests and MOCK_VISION mode."""
    records = []
    frame_index = 0
    t_sec = 0.0
    while t_sec < 60.0:
        objects = (
            ("car", "red", "mock-car-1", 12 <= t_sec <= 18),
            ("car", "red", "mock-car-2", 40 <= t_sec <= 43),
            ("bottle", "amber", "mock-bottle-1", 20 <= t_sec <= 35),
        )
        for class_name, color, track_id, active in objects:
            if active:
                records.append({
                    "id": f"{video_id}:{frame_index}:{track_id}",
                    "frame_index": frame_index,
                    "time_sec": round(t_sec, 3),
                    "track_id": track_id,
                    "class_name": class_name,
                    "color": color,
                    "confidence": 0.9,
                    "bbox": [100.0, 100.0, 300.0, 300.0],
                    "mask": None,
                    "position": "center",
                })
        frame_index += 1
        t_sec = frame_index / max(detect_fps, 0.1)
    return records


def run_detector_pass(
    video_id: str,
    video_path: Path,
    progress_cb: Any = None,
) -> list[dict]:
    """Run Ultralytics YOLO with ByteTrack and persist sampled observations."""
    if not config.DETECTOR_ENABLED:
        store.save_detections(video_id, [])
        return []
    if config.MOCK_VISION:
        detections = _mock_detections(video_id, config.DETECT_FPS)
        store.save_detections(video_id, detections)
        return detections

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("YOLO detection requires ultralytics; install backend requirements") from exc

    from backend.app.video_index import probe_video

    metadata = probe_video(video_path)
    source_fps = max(float(metadata.get("fps") or 0), 0.1)
    duration_sec = float(metadata.get("duration_sec") or 0)
    sample_fps = max(float(config.DETECT_FPS), 0.1)
    frame_stride = max(1, round(source_fps / sample_fps))
    actual_sample_fps = source_fps / frame_stride

    with DETECTOR_LOCK:
        model = YOLO(config.DETECTOR_MODEL)
        prompts = _glossary_prompts()
        if prompts and callable(getattr(model, "set_classes", None)):
            model.set_classes(prompts)

        observations = []
        for frame_index, result in enumerate(model.track(
            source=str(video_path),
            stream=True,
            persist=True,
            tracker="bytetrack.yaml",
            vid_stride=frame_stride,
            verbose=False,
        )):
            boxes = result.boxes
            if boxes is None or len(boxes) == 0:
                continue
            frame = result.orig_img
            coordinates = boxes.xyxy.cpu().tolist()
            class_ids = boxes.cls.int().cpu().tolist()
            confidences = boxes.conf.cpu().tolist()
            track_values = boxes.id.int().cpu().tolist() if boxes.id is not None else []
            names = result.names
            if config.DETECT_SEGMENTATION and result.masks is None:
                raise RuntimeError("DETECT_SEGMENTATION=1 requires a YOLO segmentation model")
            masks = result.masks.xy if config.DETECT_SEGMENTATION and result.masks is not None else None
            time_sec = round(min(frame_index / actual_sample_fps, duration_sec), 3)

            for detection_index, bbox in enumerate(coordinates):
                class_name = str(names[class_ids[detection_index]]).strip().lower()
                track_id = (
                    str(track_values[detection_index])
                    if detection_index < len(track_values)
                    else f"untracked-{frame_index}-{detection_index}"
                )
                mask = None
                if masks is not None and detection_index < len(masks):
                    mask = [[round(float(point[0]), 1), round(float(point[1]), 1)] for point in masks[detection_index]]
                observations.append({
                    "id": f"{video_id}:{frame_index}:{track_id}:{detection_index}",
                    "frame_index": frame_index,
                    "time_sec": time_sec,
                    "track_id": track_id,
                    "class_name": class_name,
                    "color": _dominant_color(frame, bbox),
                    "confidence": float(confidences[detection_index]),
                    "bbox": [round(float(value), 1) for value in bbox],
                    "mask": mask,
                    "position": _position(bbox, frame.shape),
                })

            if progress_cb and duration_sec > 0:
                percent = min(95.0, frame_index / max(duration_sec * actual_sample_fps, 1) * 95.0)
                progress_cb(percent, f"Detecting objects at {time_sec:.1f}s")

        store.save_detections(video_id, observations)
        store.save_entities(video_id, build_entity_index(observations, actual_sample_fps))
        logger.info("[%s] YOLO/ByteTrack indexed %d detections", video_id[:8], len(observations))
        return observations