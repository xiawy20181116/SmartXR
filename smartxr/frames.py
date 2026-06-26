"""Tracker frame normalization.

Normalizes heterogeneous tracker/capture frames (HumanTrackor records, raw
detection dumps, replay JSONL lines) into the intermediate *source payload*
shape that ``smartxr.publisher.normalize_source_payload`` consumes.
"""

from __future__ import annotations

from typing import Any

from smartxr.geometry import as_float


def as_int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return fallback


def _image_from_frame(frame: dict[str, Any]) -> dict[str, Any]:
    image = frame.get("image")
    if isinstance(image, dict):
        width = as_int(image.get("w", image.get("width")), 0)
        height = as_int(image.get("h", image.get("height")), 0)
    else:
        width = as_int(frame.get("image_width", frame.get("width")), 0)
        height = as_int(frame.get("image_height", frame.get("height")), 0)
    result: dict[str, int] = {}
    if width > 0:
        result["w"] = width
    if height > 0:
        result["h"] = height
    camera = frame.get("camera")
    if isinstance(camera, dict):
        result["camera"] = dict(camera)
    return result


def _frame_sequence(frame: dict[str, Any], index: int) -> int:
    return as_int(frame.get("sequence", frame.get("frame_id", frame.get("frame_index"))), index)


def _target_source_items(frame: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("detections", "targets", "people"):
        value = frame.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _bbox_from_value(value: Any) -> dict[str, float]:
    if isinstance(value, dict):
        if all(key in value for key in ("cx", "cy", "w", "h")):
            return {
                "cx": as_float(value.get("cx"), 0.0),
                "cy": as_float(value.get("cy"), 0.0),
                "w": as_float(value.get("w"), 0.0),
                "h": as_float(value.get("h"), 0.0),
            }
        if all(key in value for key in ("x1", "y1", "x2", "y2")):
            x1 = as_float(value.get("x1"), 0.0)
            y1 = as_float(value.get("y1"), 0.0)
            x2 = as_float(value.get("x2"), x1)
            y2 = as_float(value.get("y2"), y1)
            return {"cx": (x1 + x2) * 0.5, "cy": (y1 + y2) * 0.5, "w": x2 - x1, "h": y2 - y1}
    if isinstance(value, list) and len(value) >= 4:
        x1 = as_float(value[0], 0.0)
        y1 = as_float(value[1], 0.0)
        x2 = as_float(value[2], x1)
        y2 = as_float(value[3], y1)
        return {"cx": (x1 + x2) * 0.5, "cy": (y1 + y2) * 0.5, "w": x2 - x1, "h": y2 - y1}
    return {}


def _detection_id(item: dict[str, Any], index: int) -> str:
    raw_id = item.get("id", item.get("target_id", item.get("track_id")))
    if raw_id is None or raw_id == "":
        raw_id = index
    value = str(raw_id)
    if value.startswith("person-"):
        return value
    return f"person-{value}"


def normalize_frame(frame: dict[str, Any], index: int, min_confidence: float) -> dict[str, Any]:
    """Normalize one tracker frame into a source payload with detections."""
    sequence = _frame_sequence(frame, index)
    image = _image_from_frame(frame)
    timestamp_ms = frame.get("timestamp_ms", frame.get("ts_ms"))
    normalized: dict[str, Any] = {
        "source": str(frame.get("source", "vst")),
        "sequence": sequence,
        "detections": [],
        "pose_quality": str(frame.get("pose_quality", "projected_2d")),
    }
    if timestamp_ms is not None:
        normalized["timestamp_ms"] = as_float(timestamp_ms, 0.0)
    if image:
        normalized["image"] = image

    detections: list[dict[str, Any]] = []
    for item_index, item in enumerate(_target_source_items(frame)):
        confidence = as_float(item.get("confidence", item.get("score")), 1.0)
        if confidence < min_confidence:
            continue
        detection: dict[str, Any] = {
            "id": _detection_id(item, item_index),
            "state": str(item.get("state", item.get("tracking_status", "tracked"))),
            "confidence": confidence,
        }
        bbox = _bbox_from_value(item.get("bbox", item.get("box")))
        if bbox:
            detection["bbox"] = bbox
        if "depth_m" in item:
            detection["depth_m"] = as_float(item.get("depth_m"), 1.2)
        if "depth_source" in item:
            detection["depth_source"] = item["depth_source"]
        if "depth_confidence" in item:
            detection["depth_confidence"] = item["depth_confidence"]
        if "position" in item:
            detection["position"] = item["position"]
        if "transform" in item:
            detection["transform"] = item["transform"]
        detections.append(detection)

    normalized["detections"] = detections
    return normalized
