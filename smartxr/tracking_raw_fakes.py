"""Fake producer and fake consumer for the tracking_raw (C1) seam.

Both speak only the C1 schema (``smartxr.tracking_raw_schema``); neither
depends on the real module-1 detector or the real module-3 consumer. This is
the section-5 freeze requirement #3: a fake producer and a fake consumer exist
on the contract alone, so each side can be built and verified independently.

The producer synthesizes a moving 2.5D box around a nominal human anchor (the 8
vertices extruded around the projected anchor using nominal human dimensions,
exactly as described in the architecture's depth note). The consumer parses,
validates and tracks ids across a sequence so id-stability is observable
without the real producer.
"""

from __future__ import annotations

import math
from typing import Any

from smartxr.tracking_raw_schema import (
    MESSAGE_TYPE,
    SCHEMA_VERSION,
    validate_message,
)


# Nominal standing-human dimensions used to extrude the 2.5D box (meters).
NOMINAL_HUMAN_WIDTH_M = 0.5
NOMINAL_HUMAN_HEIGHT_M = 1.7
NOMINAL_HUMAN_DEPTH_M = 0.35


def _box_vertices(center: list[float], extent: list[float]) -> list[list[float]]:
    """8 axis-aligned box vertices from center + half-extent, in canonical order."""
    cx, cy, cz = center
    hx, hy, hz = extent
    return [
        [cx + sx * hx, cy + sy * hy, cz + sz * hz]
        for sx in (-1.0, 1.0)
        for sy in (-1.0, 1.0)
        for sz in (-1.0, 1.0)
    ]


def build_fake_tracking_raw_message(
    elapsed_s: float,
    track_id: str = "person-7",
    depth_m: float = 1.8,
    sequence: int = 0,
    state: str = "confirmed",
    pose_quality: str = "fixed_depth",
    coordinate_space: str = "vst_right_camera",
    timestamp_ms: float | None = None,
) -> dict[str, Any]:
    """Synthetic C1 frame: one moving human as an 8-vertex 2.5D box + landmark.

    ``elapsed_s`` animates the anchor so a sequence exercises a moving track;
    ``depth_m`` is the pluggable scalar depth (v1: fixed). The clock is passed in
    (``timestamp_ms``) so the builder stays deterministic and pure.
    """
    if timestamp_ms is None:
        timestamp_ms = elapsed_s * 1000.0

    anchor_x = math.sin(elapsed_s) * 0.25
    anchor_y = 0.0
    anchor_z = -depth_m + math.cos(elapsed_s) * 0.08

    half_extent = [
        NOMINAL_HUMAN_WIDTH_M * 0.5,
        NOMINAL_HUMAN_HEIGHT_M * 0.5,
        NOMINAL_HUMAN_DEPTH_M * 0.5,
    ]
    center = [anchor_x, anchor_y, anchor_z]
    vertices = _box_vertices(center, half_extent)

    # Default landmark rule: centroid of the 8 vertices (== box center here).
    landmark_point = [center[0], center[1], center[2]]

    return {
        "type": MESSAGE_TYPE,
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence,
        "source": "fake_tracking",
        "timestamp_ms": timestamp_ms,
        "detections": [
            {
                "id": track_id,
                "state": state,
                "age_frames": sequence,
                "confidence": 0.94,
                "timestamp_ms": timestamp_ms,
                "bbox_3d": {"vertices": vertices},
                "landmark": {"rule": "centroid", "point": landmark_point},
                "source_frame": {
                    "coordinate_space": coordinate_space,
                    "units": "meters",
                    "depth_source": "constant_depth",
                },
                "pose_quality": pose_quality,
            }
        ],
    }


class TrackingRawConsumer:
    """Fake C1 consumer: validates each message and tracks id lifecycle.

    Speaks only the schema. Records every seen track id and rejects malformed
    payloads at the boundary (section 12: malformed payload is rejected, logged
    and dropped -- never partially applied).
    """

    def __init__(self) -> None:
        self.frames_accepted = 0
        self.frames_rejected = 0
        self.seen_ids: set[str] = set()
        self.last_state_by_id: dict[str, str] = {}
        self.errors: list[str] = []

    def consume(self, message: Any) -> bool:
        """Validate and apply one message. Returns True if accepted."""
        errors = validate_message(message)
        if errors:
            self.frames_rejected += 1
            self.errors.extend(errors)
            return False
        self.frames_accepted += 1
        for detection in message["detections"]:
            track_id = detection["id"]
            self.seen_ids.add(track_id)
            self.last_state_by_id[track_id] = detection["state"]
        return True
