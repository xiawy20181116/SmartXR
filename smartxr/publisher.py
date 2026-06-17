"""proxy_targets message builders, source normalization, and replay.

Every publisher (fake, VST bbox replay, Antman live) produces the canonical
``proxy_targets`` message through this module, so the conversion to Godot
conventions has a single implementation.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from smartxr.frames import normalize_frame
from smartxr.geometry import (
    as_float,
    clamped_fov_deg,
    project_bbox_center_to_camera_point,
    vst_camera_point_to_head,
)
from smartxr.schema import SCHEMA_VERSION, canonical_state, default_offset_rule


DEFAULT_HORIZONTAL_FOV_DEG = 70.0
DEFAULT_VERTICAL_FOV_DEG = 43.0
DEFAULT_COORDINATE_SPACE = "vst_camera_right"
DEFAULT_TARGET_DEPTH_M = 5.0


def build_fake_proxy_targets_message(
    elapsed_s: float,
    target_id: str = "person-7",
    card_id: str = "CardAnchor",
    radius_m: float = 0.25,
    depth_m: float = 1.2,
    sequence: int = 0,
    mode: str = "moving",
) -> dict[str, Any]:
    """Synthetic world-space target used for Windows PCMR validation."""
    if mode == "static":
        x = 0.0
        y = 0.0
        z = -depth_m
    else:
        x = math.sin(elapsed_s) * radius_m
        y = math.sin(elapsed_s * 0.5) * 0.08
        z = -depth_m + math.cos(elapsed_s) * 0.08
    return {
        "type": "proxy_targets",
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence,
        "targets": [
            {
                "target_id": target_id,
                "source": "fake_vst",
                "coordinate_space": "world",
                "transform_space": "world",
                "state": "tracked",
                "confidence": 0.96,
                "timestamp_ms": int(time.time() * 1000),
                "transform": {
                    "position": [x, y, z],
                    "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                    "scale": [1.0, 1.0, 1.0],
                },
            }
        ],
        "cards": [
            {
                "card_id": card_id,
                "target_id": target_id,
                "offset_rule": default_offset_rule(),
            }
        ],
    }


def _target_id(source: str, raw_id: Any, index: int) -> str:
    value = str(raw_id or f"target-{index}")
    if value.startswith(f"{source}-"):
        return value
    return f"{source}-{value}"


def _fov_degrees(detection: dict[str, Any], root_image: dict[str, Any]) -> tuple[float, float]:
    camera = detection.get("camera", root_image.get("camera", {}))
    if not isinstance(camera, dict):
        camera = {}
    return (
        clamped_fov_deg(camera.get("horizontal_fov_deg"), DEFAULT_HORIZONTAL_FOV_DEG),
        clamped_fov_deg(camera.get("vertical_fov_deg"), DEFAULT_VERTICAL_FOV_DEG),
    )


def _principal_point(detection: dict[str, Any], root_image: dict[str, Any], image_w: float, image_h: float) -> tuple[float, float]:
    camera = detection.get("camera", root_image.get("camera", {}))
    if not isinstance(camera, dict):
        camera = {}
    return (
        as_float(camera.get("principal_point_x"), image_w * 0.5),
        as_float(camera.get("principal_point_y"), image_h * 0.5),
    )


def _right_eye_to_head_matrix(detection: dict[str, Any], root_image: dict[str, Any]) -> list[float] | None:
    camera = detection.get("camera", root_image.get("camera", {}))
    if not isinstance(camera, dict):
        return None
    value = camera.get("right_eye_to_head_matrix")
    if not isinstance(value, list) or len(value) < 16:
        return None
    matrix: list[float] = []
    for item in value[:16]:
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            return None
        matrix.append(float(item))
    return matrix


def _camera_coordinate_space(detection: dict[str, Any], root_image: dict[str, Any]) -> str:
    camera = detection.get("camera", root_image.get("camera", {}))
    if isinstance(camera, dict) and camera.get("coordinate_space"):
        return str(camera["coordinate_space"])
    return DEFAULT_COORDINATE_SPACE


def _camera_point_from_bbox(
    detection: dict[str, Any],
    root_image: dict[str, Any],
    default_depth_m: float,
) -> tuple[list[float], dict[str, float]]:
    bbox = detection.get("bbox", {})
    image = detection.get("image", root_image)
    depth_m = as_float(detection.get("depth_m"), default_depth_m)
    if not isinstance(bbox, dict) or not isinstance(image, dict):
        return [0.0, 0.0, depth_m], {
            "image_w": 1.0,
            "image_h": 1.0,
            "cx": 0.5,
            "cy": 0.5,
            "depth_m": depth_m,
            "horizontal_fov_deg": DEFAULT_HORIZONTAL_FOV_DEG,
            "vertical_fov_deg": DEFAULT_VERTICAL_FOV_DEG,
        }

    image_w = max(as_float(image.get("w"), 1.0), 1.0)
    image_h = max(as_float(image.get("h"), 1.0), 1.0)
    cx = as_float(bbox.get("cx"), image_w * 0.5)
    cy = as_float(bbox.get("cy"), image_h * 0.5)
    horizontal_fov_deg, vertical_fov_deg = _fov_degrees(detection, root_image)
    principal_point_x, principal_point_y = _principal_point(detection, root_image, image_w, image_h)
    point_vst = project_bbox_center_to_camera_point(
        cx,
        cy,
        image_w,
        image_h,
        horizontal_fov_deg,
        vertical_fov_deg,
        depth_m,
        principal_point_x,
        principal_point_y,
    )
    return point_vst, {
        "image_w": image_w,
        "image_h": image_h,
        "cx": cx,
        "cy": cy,
        "principal_point_x": principal_point_x,
        "principal_point_y": principal_point_y,
        "depth_m": depth_m,
        "horizontal_fov_deg": horizontal_fov_deg,
        "vertical_fov_deg": vertical_fov_deg,
    }


def _bbox_position(detection: dict[str, Any], root_image: dict[str, Any], default_depth_m: float) -> list[float]:
    point_vst, _diagnostics = _camera_point_from_bbox(detection, root_image, default_depth_m)
    return vst_camera_point_to_head(point_vst, _right_eye_to_head_matrix(detection, root_image))


def _source_coordinate_diagnostics(
    detection: dict[str, Any],
    root_image: dict[str, Any],
    default_depth_m: float,
    position: list[float],
) -> dict[str, Any]:
    point_vst, camera = _camera_point_from_bbox(detection, root_image, default_depth_m)
    right_eye_to_head = _right_eye_to_head_matrix(detection, root_image)
    return {
        "coordinate_space": _camera_coordinate_space(detection, root_image),
        "publisher_convention": "godot_head",
        "camera_axes": "+X right,+Y down,+Z forward",
        "head_axes": "+X right,+Y up,-Z forward",
        "anchor": "target_center",
        "depth_source": "provided_depth" if "depth_m" in detection else "default_depth",
        "uses_right_eye_to_head": right_eye_to_head is not None,
        "source_frame": {
            "w": camera["image_w"],
            "h": camera["image_h"],
            "center_x": camera["cx"],
            "center_y": camera["cy"],
            "principal_point_x": camera["principal_point_x"],
            "principal_point_y": camera["principal_point_y"],
            "anchor_depth": camera["depth_m"],
            "horizontal_fov_deg": camera["horizontal_fov_deg"],
            "vertical_fov_deg": camera["vertical_fov_deg"],
        },
        "camera_point_m": point_vst,
        "head_position_m": position,
    }


def _transform_from_detection(
    detection: dict[str, Any],
    root_image: dict[str, Any],
    default_depth_m: float,
) -> dict[str, list[float]]:
    transform = detection.get("transform")
    if isinstance(transform, dict):
        return {
            "position": list(transform.get("position", [0.0, 0.0, -default_depth_m])),
            "rotation_xyzw": list(transform.get("rotation_xyzw", [0.0, 0.0, 0.0, 1.0])),
            "scale": list(transform.get("scale", [1.0, 1.0, 1.0])),
        }
    position = detection.get("position")
    if isinstance(position, list) and len(position) >= 3:
        parsed_position = [float(position[0]), float(position[1]), float(position[2])]
    else:
        parsed_position = _bbox_position(detection, root_image, default_depth_m)
    return {
        "position": parsed_position,
        "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
        "scale": [1.0, 1.0, 1.0],
    }


def normalize_source_payload(
    source_payload: dict[str, Any],
    sequence: int | None = None,
    card_id: str = "CardAnchor",
    default_depth_m: float = DEFAULT_TARGET_DEPTH_M,
) -> dict[str, Any]:
    """Convert a VST/external source payload into a canonical proxy_targets
    message. Already-canonical payloads pass through (sequence re-stamped)."""
    if source_payload.get("type") == "proxy_targets":
        message = json.loads(json.dumps(source_payload))
        if sequence is not None:
            message["sequence"] = sequence
        return message

    source = str(source_payload.get("source", "vst"))
    output_sequence = int(sequence if sequence is not None else source_payload.get("sequence", 0))
    timestamp_ms = as_float(source_payload.get("timestamp_ms"), time.time() * 1000.0)
    root_image = source_payload.get("image", {})
    if not isinstance(root_image, dict):
        root_image = {}

    detections = source_payload.get("detections")
    if not isinstance(detections, list):
        detections = source_payload.get("targets")
    if not isinstance(detections, list):
        detections = [source_payload]

    targets: list[dict[str, Any]] = []
    for index, detection in enumerate(detections):
        if not isinstance(detection, dict):
            continue
        raw_id = detection.get("target_id", detection.get("id", detection.get("track_id")))
        target_id = _target_id(source, raw_id, index)
        target = {
            "target_id": target_id,
            "source": source,
            "coordinate_space": "head",
            "transform_space": "head",
            "state": canonical_state(detection.get("state", "tracked")),
            "confidence": as_float(detection.get("confidence"), 1.0),
            "timestamp_ms": as_float(detection.get("timestamp_ms"), timestamp_ms),
            "transform": _transform_from_detection(detection, root_image, default_depth_m),
        }
        if isinstance(detection.get("bbox"), dict):
            target["source_coordinate"] = _source_coordinate_diagnostics(
                detection,
                root_image,
                default_depth_m,
                target["transform"]["position"],
            )
        targets.append(target)

    cards = []
    if targets:
        cards.append(
            {
                "card_id": card_id,
                "target_id": targets[0]["target_id"],
                "offset_rule": default_offset_rule(),
            }
        )

    return {
        "type": "proxy_targets",
        "schema_version": SCHEMA_VERSION,
        "sequence": output_sequence,
        "targets": targets,
        "cards": cards,
    }


def load_source_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"source payload must be an object: {path}")
    return payload


def load_source_messages(
    path: Path,
    card_id: str = "CardAnchor",
    default_depth_m: float = DEFAULT_TARGET_DEPTH_M,
) -> list[dict[str, Any]]:
    """Load a source JSON/JSONL file into canonical replay messages."""
    if path.suffix.lower() != ".jsonl":
        return [normalize_source_payload(load_source_payload(path), card_id=card_id, default_depth_m=default_depth_m)]

    messages: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError(f"source JSONL line must be an object: {path}:{line_number}")
            normalized_frame = normalize_frame(payload, index=line_number, min_confidence=0.0)
            message = normalize_source_payload(normalized_frame, card_id=card_id, default_depth_m=default_depth_m)
            if message["targets"]:
                messages.append(message)
    if not messages:
        raise ValueError(f"source JSONL did not contain any target frames: {path}")
    return messages


def replay_message_at(source_messages: list[dict[str, Any]], sequence: int) -> dict[str, Any]:
    if not source_messages:
        raise ValueError("source_messages must not be empty")
    message = json.loads(json.dumps(source_messages[sequence % len(source_messages)]))
    message["sequence"] = sequence
    return message
