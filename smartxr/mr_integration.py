"""Module 3 (MR integration): C1 (tracking_raw) -> C2 (proxy_targets) converter.

This is the publisher-side **alignment** seam of the architecture baseline
(``docs/architecture_modules.md`` module 3 + seams C1/C2): module 1 emits raw 3D
tracking (``tracking_raw``, an 8-vertex bbox + derived landmark in the
``vst_right_camera`` frame); module 3 converts each detection's landmark into a
``head``/``world`` transform and assembles a canonical ``proxy_targets`` message
that module 2 (the Godot card) consumes. C1 carries 3D camera-frame geometry and
C2 carries head/world transforms -- this module is the only place the two meet.

Calibration ownership (baseline section 8 data need #2): module 3 owns the
camera->head conversion. v1 is **monocular**, so the default conversion is the
axis flip ``[x, -y, -z]`` (``Calibration.monocular()``); when a binocular
``right_eye_to_head`` 4x4 extrinsic becomes available it is held here
(``Calibration.with_right_eye_to_head()``) and applied instead, with no change to
C1, C2, or the consumer. The pinhole **intrinsics** (default FOV 70/43 deg) live
in module 1's projection (``smartxr.box_builder_2_5d``) because C1 is already 3D;
module 3 only applies the extrinsic. The actual point math is delegated to
``smartxr.geometry`` -- the single source of truth that is dual-locked against the
GDScript card by ``godot-android/fixtures/bbox_math_test_vectors.json``.

Coordinate frames / units follow baseline section 11: meters, right-handed,
quaternions ``[x, y, z, w]``; camera axes are ``+X right, +Y down, +Z forward``
and head axes are ``+X right, +Y up, -Z forward``.

Latency (baseline section 13): the C1->C2 + alignment stage budgets ~10-20 ms of
the 150 ms end-to-end. The conversion is pure arithmetic over a handful of points
per detection (one matrix/flip per target), so it stays well inside that slice;
modules 3 and 6 own the on-device end-to-end measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from smartxr.geometry import vst_camera_point_to_head
from smartxr.schema import (
    SCHEMA_VERSION,
    DEFAULT_CARD_ID,
    default_offset_rule,
)


# v1 monocular default FOV (informational; the projection that uses it lives in
# module 1 -- box_builder_2_5d -- because C1 is already 3D).
DEFAULT_HORIZONTAL_FOV_DEG = 70.0
DEFAULT_VERTICAL_FOV_DEG = 43.0

# C1 source_frame.coordinate_space values that are already in head/world space and
# therefore need no camera->head conversion (baseline section 11).
PASSTHROUGH_FRAMES = {"head", "world"}

# Explicit C1 track-lifecycle -> C2 target-state mapping. C1 states come from the
# track lifecycle (baseline "Track lifecycle and id"): tentative -> confirmed ->
# lost (pose predicted) -> deleted (removed). C2 states are tracked / predicted /
# stale / lost. ``smartxr.schema.canonical_state`` is NOT reused here because it
# maps C1 ``lost`` to ``tracked`` -- the C1 lifecycle needs this dedicated map.
C1_TO_C2_STATE: dict[str, str] = {
    "tentative": "tracked",  # newly seen, actively detected
    "confirmed": "tracked",  # stable across N frames
    "lost": "predicted",     # missed M frames, pose held/predicted
    "deleted": "lost",       # removed; consumer fades/detaches the card
}
DEFAULT_C2_STATE = "lost"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _valid_right_eye_to_head(value: Any) -> list[float] | None:
    """Return a 16-element float matrix, or ``None`` (default-flip fallback).

    Mirrors the publisher / GDScript behavior: a missing or short matrix falls
    back to the default ``[x, -y, -z]`` axis flip rather than erroring.
    """
    if not isinstance(value, list) or len(value) < 16:
        return None
    matrix: list[float] = []
    for item in value[:16]:
        if not _is_number(item):
            return None
        matrix.append(float(item))
    return matrix


@dataclass(frozen=True)
class Calibration:
    """The camera->head calibration module 3 owns.

    ``right_eye_to_head`` is a row-major 4x4 extrinsic (16 floats) applied to a
    camera-frame point; ``None`` selects the v1 monocular default axis flip.
    FOV fields are informational (intrinsics live in module 1's projection).
    """

    right_eye_to_head: list[float] | None = None
    horizontal_fov_deg: float = DEFAULT_HORIZONTAL_FOV_DEG
    vertical_fov_deg: float = DEFAULT_VERTICAL_FOV_DEG

    @classmethod
    def monocular(
        cls,
        horizontal_fov_deg: float = DEFAULT_HORIZONTAL_FOV_DEG,
        vertical_fov_deg: float = DEFAULT_VERTICAL_FOV_DEG,
    ) -> "Calibration":
        """v1 monocular calibration: default axis flip, default FOV."""
        return cls(None, horizontal_fov_deg, vertical_fov_deg)

    @classmethod
    def with_right_eye_to_head(
        cls,
        matrix: Any,
        horizontal_fov_deg: float = DEFAULT_HORIZONTAL_FOV_DEG,
        vertical_fov_deg: float = DEFAULT_VERTICAL_FOV_DEG,
    ) -> "Calibration":
        """Binocular calibration from a row-major 4x4 ``right_eye_to_head``.

        A missing/short/non-numeric matrix degrades to the monocular default
        flip (never errors), matching the geometry contract.
        """
        return cls(_valid_right_eye_to_head(matrix), horizontal_fov_deg, vertical_fov_deg)

    @property
    def uses_right_eye_to_head(self) -> bool:
        return _valid_right_eye_to_head(self.right_eye_to_head) is not None

    @property
    def label(self) -> str:
        return "right_eye_to_head" if self.uses_right_eye_to_head else "monocular_default_flip"


DEFAULT_CALIBRATION = Calibration.monocular()


def _make_target_id(source: str, raw_id: Any, index: int) -> str:
    """Stable C2 target id from the C1 track id, prefixed by source.

    Matches ``smartxr.publisher`` so the Godot consumer sees consistently-shaped
    ids regardless of which publisher path produced the message.
    """
    value = str(raw_id if raw_id not in (None, "") else f"target-{index}")
    if value.startswith(f"{source}-"):
        return value
    return f"{source}-{value}"


def _map_state(c1_state: Any) -> str:
    return C1_TO_C2_STATE.get(str(c1_state or "").strip().lower(), DEFAULT_C2_STATE)


def _landmark_point(detection: dict[str, Any]) -> list[float] | None:
    landmark = detection.get("landmark")
    if not isinstance(landmark, dict):
        return None
    point = landmark.get("point")
    if not isinstance(point, list) or len(point) != 3 or not all(_is_number(v) for v in point):
        return None
    return [float(point[0]), float(point[1]), float(point[2])]


def _convert_detection(
    detection: dict[str, Any],
    index: int,
    source: str,
    frame_timestamp_ms: float,
    calibration: Calibration,
    *,
    stale_after_ms: float | None,
    min_confidence: float,
    include_diagnostics: bool,
) -> dict[str, Any] | None:
    if not isinstance(detection, dict):
        return None

    point_cam = _landmark_point(detection)
    if point_cam is None:
        return None

    confidence = detection.get("confidence")
    confidence = float(confidence) if _is_number(confidence) else 1.0
    confidence = max(0.0, min(1.0, confidence))
    if confidence < min_confidence:
        return None

    source_frame = detection.get("source_frame")
    space = ""
    if isinstance(source_frame, dict):
        space = str(source_frame.get("coordinate_space", "")).strip().lower()

    if space in PASSTHROUGH_FRAMES:
        position = point_cam
        out_space = space
    else:
        position = vst_camera_point_to_head(point_cam, calibration.right_eye_to_head)
        out_space = "head"

    state = _map_state(detection.get("state"))

    detection_ts = detection.get("timestamp_ms")
    detection_ts = float(detection_ts) if _is_number(detection_ts) else frame_timestamp_ms
    # Stale-pose downgrade (baseline section 12): a held/lagging per-track
    # timestamp means the pose is older than the frame; a "tracked" target whose
    # pose is stale is reported as "stale" so the consumer can weight confidence.
    if (
        stale_after_ms is not None
        and state == "tracked"
        and (frame_timestamp_ms - detection_ts) > stale_after_ms
    ):
        state = "stale"

    target: dict[str, Any] = {
        "target_id": _make_target_id(source, detection.get("id"), index),
        "source": source,
        "coordinate_space": out_space,
        "transform_space": out_space,
        "state": state,
        "confidence": confidence,
        "timestamp_ms": detection_ts,
        "transform": {
            "position": position,
            "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
            "scale": [1.0, 1.0, 1.0],
        },
    }

    if include_diagnostics:
        # Alignment diagnostics for the L3 device smoke. No raw-source field
        # names (bbox/depth_m/image/...) so the C2 raw-field gate stays green.
        target["mr_alignment"] = {
            "camera_point_m": point_cam,
            "head_point_m": position,
            "pose_quality": str(detection.get("pose_quality", "unknown")),
            "calibration": calibration.label,
            "source_frame": space or "unknown",
        }
    return target


def convert_tracking_raw_message(
    message: dict[str, Any],
    *,
    calibration: Calibration = DEFAULT_CALIBRATION,
    card_id: str = DEFAULT_CARD_ID,
    sequence: int | None = None,
    stale_after_ms: float | None = None,
    min_confidence: float = 0.0,
    include_diagnostics: bool = False,
) -> dict[str, Any] | None:
    """Convert one C1 ``tracking_raw`` message into a canonical C2 message.

    Returns a validated-shape ``proxy_targets`` dict, or ``None`` when the C1
    frame yields no targets (empty detections == the valid "no people" state of
    baseline section 12; C2 requires non-empty targets/cards, so module 3 simply
    does not publish on an empty frame and the cards idle/hide).

    A single card is bound to the primary (first) target with the default offset
    rule; per-target multi-card lifecycle is module 2's job via the C3 contract.
    """
    if not isinstance(message, dict):
        return None

    source = str(message.get("source") or "tracking_raw")
    frame_timestamp_ms = message.get("timestamp_ms")
    frame_timestamp_ms = float(frame_timestamp_ms) if _is_number(frame_timestamp_ms) else 0.0
    out_sequence = int(sequence if sequence is not None else message.get("sequence", 0) or 0)

    detections = message.get("detections")
    if not isinstance(detections, list):
        detections = []

    targets: list[dict[str, Any]] = []
    for index, detection in enumerate(detections):
        target = _convert_detection(
            detection,
            index,
            source,
            frame_timestamp_ms,
            calibration,
            stale_after_ms=stale_after_ms,
            min_confidence=min_confidence,
            include_diagnostics=include_diagnostics,
        )
        if target is not None:
            targets.append(target)

    if not targets:
        return None

    return {
        "type": "proxy_targets",
        "schema_version": SCHEMA_VERSION,
        "sequence": out_sequence,
        "targets": targets,
        "cards": [
            {
                "card_id": card_id,
                "target_id": targets[0]["target_id"],
                "offset_rule": default_offset_rule(),
            }
        ],
    }


class TrackingRawToProxyTargetsConverter:
    """Stateful module-3 converter that holds the calibration and re-stamps a
    monotonically increasing C2 ``sequence`` across a stream of C1 frames.

    Use ``convert_tracking_raw_message`` directly for a one-shot conversion; use
    this class to wire a C1 producer (or replay) to the proxy_targets WS path so
    the card display is driven by real tracking output ("display wiring").
    """

    def __init__(
        self,
        calibration: Calibration = DEFAULT_CALIBRATION,
        *,
        card_id: str = DEFAULT_CARD_ID,
        stale_after_ms: float | None = None,
        min_confidence: float = 0.0,
        include_diagnostics: bool = False,
    ) -> None:
        self.calibration = calibration
        self.card_id = card_id
        self.stale_after_ms = stale_after_ms
        self.min_confidence = min_confidence
        self.include_diagnostics = include_diagnostics
        self._sequence = 0

    def convert(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Convert one C1 frame; returns C2 (sequence re-stamped) or ``None``."""
        result = convert_tracking_raw_message(
            message,
            calibration=self.calibration,
            card_id=self.card_id,
            sequence=self._sequence,
            stale_after_ms=self.stale_after_ms,
            min_confidence=self.min_confidence,
            include_diagnostics=self.include_diagnostics,
        )
        if result is not None:
            self._sequence += 1
        return result
