"""Canonical tracking_raw (C1) message model and validation.

This module is the code form of ``docs/tracking_raw_payload_contract.md`` and
the C1 seam in ``docs/architecture_modules.md`` (section 4 + the Landmark and
Track-lifecycle detail notes). It is the raw 3D tracking output of module 1
(human tracking); module 3 consumes it and converts it to ``proxy_targets``
(C2). C1 carries 3D geometry only -- the 2D pixel domain (image, pixel bbox,
raw scalar depth) stays inside module 1 and must never cross this boundary.

Conventions follow ``architecture_modules.md`` section 11: meters, radians,
quaternions ``[x, y, z, w]``, right-handed; ``source_frame.coordinate_space``
names the frame.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1

MESSAGE_TYPE = "tracking_raw"

# Track lifecycle states (architecture_modules.md section "Track lifecycle and id").
ALLOWED_STATES = {"tentative", "confirmed", "lost", "deleted"}

# Pose fidelity grades (section 8 / data need #1). v1 emits fixed_depth.
ALLOWED_POSE_QUALITY = {"fixed_depth", "mono_metric", "stereo"}

# 2D / image-domain fields that belong INSIDE module 1 and must not leak into
# C1. C1 is normalized 3D geometry; pixel boxes, images, masks and raw scalar
# depth are detection internals, superseded here by bbox_3d + pose_quality +
# source_frame.depth_source.
RAW_SOURCE_FIELDS = {"bbox", "boxes", "image", "pixels", "mask", "depth_m"}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_number_array(value: Any, length: int, path: str, errors: list[str]) -> None:
    if not isinstance(value, list) or len(value) != length:
        errors.append(f"{path} must be an array of {length} numbers")
        return
    for index, item in enumerate(value):
        if not _is_number(item):
            errors.append(f"{path}[{index}] must be a number")


def _scan_raw_source_fields(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in RAW_SOURCE_FIELDS:
                errors.append(f"raw source field not allowed at {child_path}")
            _scan_raw_source_fields(child, child_path, errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_raw_source_fields(child, f"{path}[{index}]", errors)


def _validate_bbox_3d(bbox: Any, path: str, errors: list[str]) -> None:
    if not isinstance(bbox, dict):
        errors.append(f"{path} must be an object")
        return
    has_vertices = "vertices" in bbox
    has_obb = any(key in bbox for key in ("center", "extent", "rotation_xyzw"))
    if has_vertices and has_obb:
        errors.append(
            f"{path} must use exactly one form: 'vertices' OR 'center'+'extent'+'rotation_xyzw'"
        )
        return
    if has_vertices:
        vertices = bbox.get("vertices")
        if not isinstance(vertices, list) or len(vertices) != 8:
            errors.append(f"{path}.vertices must be an array of 8 vertices")
        else:
            for index, vertex in enumerate(vertices):
                _validate_number_array(vertex, 3, f"{path}.vertices[{index}]", errors)
    elif has_obb:
        _validate_number_array(bbox.get("center"), 3, f"{path}.center", errors)
        _validate_number_array(bbox.get("extent"), 3, f"{path}.extent", errors)
        _validate_number_array(bbox.get("rotation_xyzw"), 4, f"{path}.rotation_xyzw", errors)
    else:
        errors.append(
            f"{path} must provide either 'vertices' (8) or 'center'+'extent'+'rotation_xyzw'"
        )


def _validate_landmark(landmark: Any, path: str, errors: list[str]) -> None:
    if not isinstance(landmark, dict):
        errors.append(f"{path} must be an object")
        return
    if not isinstance(landmark.get("rule"), str) or not landmark.get("rule"):
        errors.append(f"{path}.rule must be a non-empty string")
    _validate_number_array(landmark.get("point"), 3, f"{path}.point", errors)


def _validate_source_frame(source_frame: Any, path: str, errors: list[str]) -> None:
    if not isinstance(source_frame, dict):
        errors.append(f"{path} must be an object")
        return
    for key in ("coordinate_space", "units", "depth_source"):
        if not isinstance(source_frame.get(key), str) or not source_frame.get(key):
            errors.append(f"{path}.{key} must be a non-empty string")


def _validate_detection(detection: Any, index: int, errors: list[str]) -> None:
    path = f"$.detections[{index}]"
    if not isinstance(detection, dict):
        errors.append(f"{path} must be an object")
        return

    track_id = detection.get("id")
    if not isinstance(track_id, str) or not track_id:
        errors.append(f"{path}.id must be a non-empty string")
    if detection.get("state") not in ALLOWED_STATES:
        errors.append(f"{path}.state must be one of {sorted(ALLOWED_STATES)}")
    if not _is_int(detection.get("age_frames")) or detection.get("age_frames") < 0:
        errors.append(f"{path}.age_frames must be a non-negative integer")
    confidence = detection.get("confidence")
    if not _is_number(confidence) or confidence < 0.0 or confidence > 1.0:
        errors.append(f"{path}.confidence must be a number in [0, 1]")
    if not _is_number(detection.get("timestamp_ms")):
        errors.append(f"{path}.timestamp_ms must be a number")
    if detection.get("pose_quality") not in ALLOWED_POSE_QUALITY:
        errors.append(f"{path}.pose_quality must be one of {sorted(ALLOWED_POSE_QUALITY)}")

    _validate_bbox_3d(detection.get("bbox_3d"), f"{path}.bbox_3d", errors)
    _validate_landmark(detection.get("landmark"), f"{path}.landmark", errors)
    _validate_source_frame(detection.get("source_frame"), f"{path}.source_frame", errors)


def validate_message(message: Any) -> list[str]:
    """Validate a canonical tracking_raw (C1) message. Returns a list of errors."""
    errors: list[str] = []
    if not isinstance(message, dict):
        return ["$ must be an object"]

    _scan_raw_source_fields(message, "$", errors)

    if message.get("type") != MESSAGE_TYPE:
        errors.append(f"$.type must be {MESSAGE_TYPE}")
    if message.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"$.schema_version must be {SCHEMA_VERSION}")
    if not _is_int(message.get("sequence")):
        errors.append("$.sequence must be an integer")
    if not isinstance(message.get("source"), str) or not message.get("source"):
        errors.append("$.source must be a non-empty string")
    if not _is_number(message.get("timestamp_ms")):
        errors.append("$.timestamp_ms must be a number")

    detections = message.get("detections")
    # An empty detection list is a valid state (no people in view; section 12).
    if not isinstance(detections, list):
        errors.append("$.detections must be an array")
    else:
        for index, detection in enumerate(detections):
            _validate_detection(detection, index, errors)

    return errors


def load_message(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
