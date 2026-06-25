"""Stereo VST depth utilities for YAN-119.

This module owns the dependency-free core for the controlled-stereo lane:
device #28 POV Scene calibration, uniform recorded-resolution scaling,
rectified-pair depth, known-distance validation, and the hot-swappable record
fields required before raw physical frames become available.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1

FRAME_PROVENANCE_POV = "pov_virtual_eye"
FRAME_PROVENANCE_RAW = "raw_physical"

CALIBRATION_KIND_POV = "pov_virtual"
CALIBRATION_KIND_RAW = "physical_raw"

DEPTH_SOURCE_POV_STEREO = "pov_stereo_triangulation"
DEPTH_SOURCE_KNOWN_DISTANCE_GT = "known_distance_gt"
DEPTH_SOURCE_RAW_STEREO = "raw_stereo_triangulation"
DEPTH_SOURCE_HEADSET = "headset_depth"

POSE_QUALITY_STEREO = "stereo"

PAIR_ID_SCHEME = "pair-{frame_id:06d}"
FRAME_ID_SOURCE = "shared_vst_shm_frame_id"

ANCHOR_KIND_BBOX_CENTER = "bbox_center"
ANCHOR_KIND_BBOX_TOP_CENTER = "bbox_top_center"


@dataclass(frozen=True)
class StereoGateConfig:
    min_confidence: float | None = None
    min_depth_m: float | None = None
    max_depth_m: float | None = None
    min_box_ratio: float | None = None
    max_box_ratio: float | None = None
    max_vertical_error_px: float | None = None
    gate_box_height_ratio: bool = True

    def __post_init__(self) -> None:
        if self.min_confidence is not None:
            min_confidence = float(self.min_confidence)
            if not 0.0 <= min_confidence <= 1.0:
                raise ValueError(f"min_confidence must be in [0, 1], got {min_confidence}")
        if self.min_depth_m is not None:
            _require_positive(self.min_depth_m, "min_depth_m")
        if self.max_depth_m is not None:
            _require_positive(self.max_depth_m, "max_depth_m")
        if (
            self.min_depth_m is not None
            and self.max_depth_m is not None
            and float(self.max_depth_m) < float(self.min_depth_m)
        ):
            raise ValueError("max_depth_m must be >= min_depth_m")
        if self.min_box_ratio is not None:
            _require_positive(self.min_box_ratio, "min_box_ratio")
        if self.max_box_ratio is not None:
            _require_positive(self.max_box_ratio, "max_box_ratio")
        if (
            self.min_box_ratio is not None
            and self.max_box_ratio is not None
            and float(self.max_box_ratio) < float(self.min_box_ratio)
        ):
            raise ValueError("max_box_ratio must be >= min_box_ratio")
        if self.max_vertical_error_px is not None and float(self.max_vertical_error_px) < 0.0:
            raise ValueError("max_vertical_error_px must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.min_confidence is not None:
            data["confidence_min"] = float(self.min_confidence)
        if self.min_depth_m is not None or self.max_depth_m is not None:
            data["depth_range_m"] = [
                None if self.min_depth_m is None else float(self.min_depth_m),
                None if self.max_depth_m is None else float(self.max_depth_m),
            ]
        if self.min_box_ratio is not None or self.max_box_ratio is not None:
            data["box_ratio_range"] = [
                None if self.min_box_ratio is None else float(self.min_box_ratio),
                None if self.max_box_ratio is None else float(self.max_box_ratio),
            ]
            data["box_height_ratio_gate"] = bool(self.gate_box_height_ratio)
        if self.max_vertical_error_px is not None:
            data["vertical_error_max_px"] = float(self.max_vertical_error_px)
        return data


def _require_positive(value: float, name: str) -> float:
    value = float(value)
    if value <= 0.0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


def format_pair_id(frame_id: int) -> str:
    """Stable session-local pair id derived from the shared VST frame id."""
    if frame_id < 0:
        raise ValueError(f"frame_id must be non-negative, got {frame_id}")
    return f"pair-{int(frame_id):06d}"


@dataclass(frozen=True)
class PinholeIntrinsics:
    eye: str
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    camera_model: str = "pinhole"
    distortion_model: str = "no_distortion"
    dist_coeff: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    t_bc: tuple[tuple[float, float, float, float], ...] | None = None

    @property
    def horizontal_fov_deg(self) -> float:
        return math.degrees(2.0 * math.atan(self.width / (2.0 * self.fx)))

    @property
    def vertical_fov_deg(self) -> float:
        return math.degrees(2.0 * math.atan(self.height / (2.0 * self.fy)))

    def scaled_to(self, width: int, height: int) -> "PinholeIntrinsics":
        width = int(width)
        height = int(height)
        if width <= 0 or height <= 0:
            raise ValueError(f"recorded resolution must be positive, got {width}x{height}")
        x_scale = width / self.width
        y_scale = height / self.height
        return PinholeIntrinsics(
            eye=self.eye,
            width=width,
            height=height,
            fx=self.fx * x_scale,
            fy=self.fy * y_scale,
            cx=self.cx * x_scale,
            cy=self.cy * y_scale,
            camera_model=self.camera_model,
            distortion_model=self.distortion_model,
            dist_coeff=self.dist_coeff,
            t_bc=self.t_bc,
        )

    def unproject(self, x_px: float, y_px: float, depth_m: float) -> list[float]:
        depth_m = _require_positive(depth_m, "depth_m")
        return [
            (float(x_px) - self.cx) * depth_m / self.fx,
            (float(y_px) - self.cy) * depth_m / self.fy,
            depth_m,
        ]

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "eye": self.eye,
            "camera_model": self.camera_model,
            "distortion_model": self.distortion_model,
            "fx": self.fx,
            "fy": self.fy,
            "cx": self.cx,
            "cy": self.cy,
            "width": self.width,
            "height": self.height,
            "distCoeff": list(self.dist_coeff),
            "horizontal_fov_deg": self.horizontal_fov_deg,
            "vertical_fov_deg": self.vertical_fov_deg,
        }
        if self.t_bc is not None:
            data["T_bc"] = [list(row) for row in self.t_bc]
        return data


@dataclass(frozen=True)
class StereoCalibration:
    device_id: str
    calibration_id: str
    left: PinholeIntrinsics
    right: PinholeIntrinsics
    baseline_m: float
    frame_provenance: str = FRAME_PROVENANCE_POV
    calibration_kind: str = CALIBRATION_KIND_POV
    left_to_right_rotation: tuple[tuple[float, float, float], ...] = (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    left_to_right_translation_m: tuple[float, float, float] = (0.0639, 0.0, 0.0)

    def __post_init__(self) -> None:
        _require_positive(self.baseline_m, "baseline_m")

    def scaled_to(
        self,
        recorded_width: int,
        recorded_height: int,
        *,
        uniform_tolerance: float = 0.002,
    ) -> "StereoCalibration":
        x_scale = int(recorded_width) / self.left.width
        y_scale = int(recorded_height) / self.left.height
        scale = (x_scale + y_scale) * 0.5
        if scale <= 0.0:
            raise ValueError(
                f"recorded resolution must be positive, got "
                f"{recorded_width}x{recorded_height}"
            )
        rel_delta = abs(x_scale - y_scale) / scale
        if rel_delta > uniform_tolerance:
            raise ValueError(
                "recorded resolution is not a uniform downscale of Scene "
                f"{self.left.width}x{self.left.height}: "
                f"{recorded_width}x{recorded_height}"
            )
        return StereoCalibration(
            device_id=self.device_id,
            calibration_id=self.calibration_id,
            left=self.left.scaled_to(recorded_width, recorded_height),
            right=self.right.scaled_to(recorded_width, recorded_height),
            baseline_m=self.baseline_m,
            frame_provenance=self.frame_provenance,
            calibration_kind=self.calibration_kind,
            left_to_right_rotation=self.left_to_right_rotation,
            left_to_right_translation_m=(
                self.baseline_m,
                0.0,
                0.0,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.calibration_id,
            "kind": self.calibration_kind,
            "reserved_kinds": [CALIBRATION_KIND_RAW],
            "baseline_m": self.baseline_m,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
            "left_to_right_extrinsic": {
                "rotation": [list(row) for row in self.left_to_right_rotation],
                "translation_m": list(self.left_to_right_translation_m),
            },
        }


@dataclass(frozen=True)
class StereoDetectionPair:
    pair_id: str
    frame_id: int
    person_id: str
    left_bbox_xyxy: tuple[float, float, float, float]
    right_bbox_xyxy: tuple[float, float, float, float]
    confidence: float

    def __post_init__(self) -> None:
        if not self.pair_id:
            raise ValueError("pair_id must be non-empty")
        if not self.person_id:
            raise ValueError("person_id must be non-empty")
        if self.frame_id < 0:
            raise ValueError(f"frame_id must be non-negative, got {self.frame_id}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")

    @property
    def left_center_px(self) -> tuple[float, float]:
        return _bbox_center(self.left_bbox_xyxy)

    @property
    def right_center_px(self) -> tuple[float, float]:
        return _bbox_center(self.right_bbox_xyxy)

    @property
    def left_top_center_px(self) -> tuple[float, float]:
        return _bbox_top_center(self.left_bbox_xyxy)

    @property
    def right_top_center_px(self) -> tuple[float, float]:
        return _bbox_top_center(self.right_bbox_xyxy)


class StereoDepthSource:
    """C1 producer DepthSource backed by stereo depth records keyed by track id."""

    def __init__(self, records_by_person_id: Mapping[str, Mapping[str, Any]]) -> None:
        self.records_by_person_id = dict(records_by_person_id)

    def depth_for(self, track) -> tuple[float, str, str]:
        record = self.records_by_person_id[track.track_id]
        depth_m = _require_positive(float(record["depth_m"]), "record.depth_m")
        depth_source = str(record["depth_source"])
        pose_quality = str(record.get("pose_quality", POSE_QUALITY_STEREO))
        if not depth_source:
            raise ValueError("record.depth_source must be non-empty")
        if pose_quality != POSE_QUALITY_STEREO:
            raise ValueError(f"stereo record pose_quality must be stereo, got {pose_quality!r}")
        return (depth_m, depth_source, pose_quality)


def _bbox_center(bbox_xyxy: Sequence[float]) -> tuple[float, float]:
    if len(bbox_xyxy) != 4:
        raise ValueError("bbox must contain four xyxy values")
    x1, y1, x2, y2 = (float(v) for v in bbox_xyxy)
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"invalid xyxy bbox {tuple(bbox_xyxy)!r}")
    return ((x1 + x2) * 0.5, (y1 + y2) * 0.5)


def _bbox_top_center(bbox_xyxy: Sequence[float]) -> tuple[float, float]:
    if len(bbox_xyxy) != 4:
        raise ValueError("bbox must contain four xyxy values")
    x1, y1, x2, y2 = (float(v) for v in bbox_xyxy)
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"invalid xyxy bbox {tuple(bbox_xyxy)!r}")
    return ((x1 + x2) * 0.5, y1)


def _bbox_size(bbox_xyxy: Sequence[float]) -> tuple[float, float]:
    if len(bbox_xyxy) != 4:
        raise ValueError("bbox must contain four xyxy values")
    x1, y1, x2, y2 = (float(v) for v in bbox_xyxy)
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"invalid xyxy bbox {tuple(bbox_xyxy)!r}")
    return (x2 - x1, y2 - y1)


def _detection_pair_anchor_px(
    pair: StereoDetectionPair,
    anchor_kind: str,
) -> tuple[tuple[float, float], tuple[float, float]]:
    if anchor_kind == ANCHOR_KIND_BBOX_CENTER:
        return (pair.left_center_px, pair.right_center_px)
    if anchor_kind == ANCHOR_KIND_BBOX_TOP_CENTER:
        return (pair.left_top_center_px, pair.right_top_center_px)
    raise ValueError(
        f"anchor_kind must be {ANCHOR_KIND_BBOX_CENTER!r} or "
        f"{ANCHOR_KIND_BBOX_TOP_CENTER!r}, got {anchor_kind!r}"
    )


def _base_stereo_record(
    pair: StereoDetectionPair,
    calibration: StereoCalibration,
    *,
    anchor_kind: str,
    left_anchor_px: tuple[float, float],
    right_anchor_px: tuple[float, float],
    disparity_px: float,
    vertical_error_px: float,
    box_width_ratio: float,
    box_height_ratio: float,
    gate_config: StereoGateConfig | None,
    stereo_ok: bool,
    rejection_reason: str | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "pair_id": pair.pair_id,
        "frame_id": pair.frame_id,
        "frame_provenance": calibration.frame_provenance,
        "person_id": pair.person_id,
        "bbox": {
            "left_xyxy": list(pair.left_bbox_xyxy),
            "right_xyxy": list(pair.right_bbox_xyxy),
        },
        "confidence": float(pair.confidence),
        "anchor_kind": anchor_kind,
        "left_anchor_px": [left_anchor_px[0], left_anchor_px[1]],
        "right_anchor_px": [right_anchor_px[0], right_anchor_px[1]],
        "disparity_px": disparity_px,
        "vertical_error_px": vertical_error_px,
        "box_width_ratio": box_width_ratio,
        "box_height_ratio": box_height_ratio,
        "depth_source": DEPTH_SOURCE_POV_STEREO,
        "is_ground_truth": False,
        "pose_quality": POSE_QUALITY_STEREO,
        "calibration_ref": calibration.calibration_id,
    }
    if gate_config is not None:
        record["stereo_ok"] = stereo_ok
        record["rejection_reason"] = rejection_reason
        record["gates"] = gate_config.to_dict()
    return record


def _reject_stereo_record(
    pair: StereoDetectionPair,
    calibration: StereoCalibration,
    *,
    anchor_kind: str,
    left_anchor_px: tuple[float, float],
    right_anchor_px: tuple[float, float],
    disparity_px: float,
    vertical_error_px: float,
    box_width_ratio: float,
    box_height_ratio: float,
    gate_config: StereoGateConfig,
    rejection_reason: str,
) -> dict[str, Any]:
    return _base_stereo_record(
        pair,
        calibration,
        anchor_kind=anchor_kind,
        left_anchor_px=left_anchor_px,
        right_anchor_px=right_anchor_px,
        disparity_px=disparity_px,
        vertical_error_px=vertical_error_px,
        box_width_ratio=box_width_ratio,
        box_height_ratio=box_height_ratio,
        gate_config=gate_config,
        stereo_ok=False,
        rejection_reason=rejection_reason,
    )


def depth_from_disparity(disparity_px: float, calibration: StereoCalibration) -> float:
    disparity_px = float(disparity_px)
    if disparity_px <= 0.0:
        raise ValueError(f"disparity_px must be positive, got {disparity_px}")
    return calibration.left.fx * calibration.baseline_m / disparity_px


def validate_known_distance(
    measured_depth_m: float,
    known_distance_m: float,
    *,
    tolerance_m: float | None = None,
) -> dict[str, Any]:
    measured_depth_m = _require_positive(measured_depth_m, "measured_depth_m")
    known_distance_m = _require_positive(known_distance_m, "known_distance_m")
    depth_error_m = measured_depth_m - known_distance_m
    validation: dict[str, Any] = {
        "known_distance_m": known_distance_m,
        "measured_depth_m": measured_depth_m,
        "depth_error_m": depth_error_m,
        "abs_depth_error_m": abs(depth_error_m),
    }
    if tolerance_m is not None:
        tolerance_m = _require_positive(tolerance_m, "tolerance_m")
        validation["tolerance_m"] = tolerance_m
        validation["within_tolerance"] = abs(depth_error_m) <= tolerance_m
    return validation


def triangulate_detection_pair(
    pair: StereoDetectionPair,
    calibration: StereoCalibration,
    *,
    anchor_kind: str = ANCHOR_KIND_BBOX_CENTER,
    gate_config: StereoGateConfig | None = None,
    known_distance_m: float | None = None,
    tolerance_m: float | None = None,
) -> dict[str, Any]:
    left_anchor_px, right_anchor_px = _detection_pair_anchor_px(pair, anchor_kind)
    left_x, left_y = left_anchor_px
    right_x, right_y = right_anchor_px
    disparity_px = left_x - right_x
    vertical_error_px = left_y - right_y
    left_width, left_height = _bbox_size(pair.left_bbox_xyxy)
    right_width, right_height = _bbox_size(pair.right_bbox_xyxy)
    box_width_ratio = left_width / right_width
    box_height_ratio = left_height / right_height

    if gate_config is not None:
        if (
            gate_config.min_confidence is not None
            and float(pair.confidence) < float(gate_config.min_confidence)
        ):
            return _reject_stereo_record(
                pair,
                calibration,
                anchor_kind=anchor_kind,
                left_anchor_px=left_anchor_px,
                right_anchor_px=right_anchor_px,
                disparity_px=disparity_px,
                vertical_error_px=vertical_error_px,
                box_width_ratio=box_width_ratio,
                box_height_ratio=box_height_ratio,
                gate_config=gate_config,
                rejection_reason="low_confidence",
            )
        if (
            gate_config.min_box_ratio is not None
            and box_width_ratio < float(gate_config.min_box_ratio)
        ) or (
            gate_config.max_box_ratio is not None
            and box_width_ratio > float(gate_config.max_box_ratio)
        ):
            return _reject_stereo_record(
                pair,
                calibration,
                anchor_kind=anchor_kind,
                left_anchor_px=left_anchor_px,
                right_anchor_px=right_anchor_px,
                disparity_px=disparity_px,
                vertical_error_px=vertical_error_px,
                box_width_ratio=box_width_ratio,
                box_height_ratio=box_height_ratio,
                gate_config=gate_config,
                rejection_reason="box_width_ratio_out_of_range",
            )
        if gate_config.gate_box_height_ratio and (
            (
                gate_config.min_box_ratio is not None
                and box_height_ratio < float(gate_config.min_box_ratio)
            ) or (
                gate_config.max_box_ratio is not None
                and box_height_ratio > float(gate_config.max_box_ratio)
            )
        ):
            return _reject_stereo_record(
                pair,
                calibration,
                anchor_kind=anchor_kind,
                left_anchor_px=left_anchor_px,
                right_anchor_px=right_anchor_px,
                disparity_px=disparity_px,
                vertical_error_px=vertical_error_px,
                box_width_ratio=box_width_ratio,
                box_height_ratio=box_height_ratio,
                gate_config=gate_config,
                rejection_reason="box_height_ratio_out_of_range",
            )
        if (
            gate_config.max_vertical_error_px is not None
            and abs(vertical_error_px) > float(gate_config.max_vertical_error_px)
        ):
            return _reject_stereo_record(
                pair,
                calibration,
                anchor_kind=anchor_kind,
                left_anchor_px=left_anchor_px,
                right_anchor_px=right_anchor_px,
                disparity_px=disparity_px,
                vertical_error_px=vertical_error_px,
                box_width_ratio=box_width_ratio,
                box_height_ratio=box_height_ratio,
                gate_config=gate_config,
                rejection_reason="vertical_error_too_large",
            )
        if disparity_px <= 0.0:
            return _reject_stereo_record(
                pair,
                calibration,
                anchor_kind=anchor_kind,
                left_anchor_px=left_anchor_px,
                right_anchor_px=right_anchor_px,
                disparity_px=disparity_px,
                vertical_error_px=vertical_error_px,
                box_width_ratio=box_width_ratio,
                box_height_ratio=box_height_ratio,
                gate_config=gate_config,
                rejection_reason="non_positive_disparity",
            )

    depth_m = depth_from_disparity(disparity_px, calibration)
    if gate_config is not None:
        if (
            gate_config.min_depth_m is not None
            and depth_m < float(gate_config.min_depth_m)
        ) or (
            gate_config.max_depth_m is not None
            and depth_m > float(gate_config.max_depth_m)
        ):
            return _reject_stereo_record(
                pair,
                calibration,
                anchor_kind=anchor_kind,
                left_anchor_px=left_anchor_px,
                right_anchor_px=right_anchor_px,
                disparity_px=disparity_px,
                vertical_error_px=vertical_error_px,
                box_width_ratio=box_width_ratio,
                box_height_ratio=box_height_ratio,
                gate_config=gate_config,
                rejection_reason="depth_out_of_range",
            )

    position = calibration.left.unproject(left_x, left_y, depth_m)

    record = _base_stereo_record(
        pair,
        calibration,
        anchor_kind=anchor_kind,
        left_anchor_px=left_anchor_px,
        right_anchor_px=right_anchor_px,
        disparity_px=disparity_px,
        vertical_error_px=vertical_error_px,
        box_width_ratio=box_width_ratio,
        box_height_ratio=box_height_ratio,
        gate_config=gate_config,
        stereo_ok=True,
        rejection_reason=None,
    )
    record["depth_m"] = depth_m
    record["position"] = position
    if known_distance_m is not None:
        record["validation"] = validate_known_distance(
            depth_m,
            known_distance_m,
            tolerance_m=tolerance_m,
        )
    return record


def build_known_distance_record(
    *,
    pair_id: str,
    frame_id: int,
    person_id: str,
    known_distance_m: float,
    calibration_ref: str,
    position: Sequence[float] | None = None,
    frame_provenance: str = FRAME_PROVENANCE_POV,
) -> dict[str, Any]:
    known_distance_m = _require_positive(known_distance_m, "known_distance_m")
    if position is None:
        position_value = [0.0, 0.0, known_distance_m]
    else:
        position_value = [float(v) for v in position]
        if len(position_value) != 3:
            raise ValueError("position must contain three values")
    return {
        "schema_version": SCHEMA_VERSION,
        "pair_id": pair_id,
        "frame_id": int(frame_id),
        "frame_provenance": frame_provenance,
        "person_id": person_id,
        "depth_source": DEPTH_SOURCE_KNOWN_DISTANCE_GT,
        "is_ground_truth": True,
        "depth_m": known_distance_m,
        "position": position_value,
        "pose_quality": POSE_QUALITY_STEREO,
        "calibration_ref": calibration_ref,
    }


def replace_depth_value(
    record: Mapping[str, Any],
    *,
    depth_m: float,
    position: Sequence[float],
    depth_source: str,
    calibration_ref: str,
    frame_provenance: str,
    is_ground_truth: bool,
) -> dict[str, Any]:
    position_value = [float(v) for v in position]
    if len(position_value) != 3:
        raise ValueError("position must contain three values")
    updated = dict(record)
    updated.pop("validation", None)
    updated.update(
        {
            "depth_m": _require_positive(depth_m, "depth_m"),
            "position": position_value,
            "depth_source": str(depth_source),
            "calibration_ref": str(calibration_ref),
            "frame_provenance": str(frame_provenance),
            "is_ground_truth": bool(is_ground_truth),
            "pose_quality": POSE_QUALITY_STEREO,
        }
    )
    return updated


def build_stereo_session_metadata(
    calibration: StereoCalibration,
    *,
    pair_count: int,
    dropped_unpaired_left: int,
    dropped_unpaired_right: int,
    max_skew_frames: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "device_id": calibration.device_id,
        "frame_provenance": calibration.frame_provenance,
        "reserved_frame_provenance": [FRAME_PROVENANCE_RAW],
        "calibration": calibration.to_dict(),
        "pairing": {
            "pair_id_scheme": PAIR_ID_SCHEME,
            "frame_id_source": FRAME_ID_SOURCE,
            "max_skew_frames": int(max_skew_frames),
            "stats": {
                "pair_count": int(pair_count),
                "dropped_unpaired_left": int(dropped_unpaired_left),
                "dropped_unpaired_right": int(dropped_unpaired_right),
            },
        },
        "record_reserved_depth_sources": [
            DEPTH_SOURCE_KNOWN_DISTANCE_GT,
            DEPTH_SOURCE_RAW_STEREO,
            DEPTH_SOURCE_HEADSET,
        ],
    }


SCENE_L_T_BC = (
    (-0.9998924382824463, 0.013974435039524438, -0.004452755429011608, 0.038738514610199185),
    (-0.01404699413651315, -0.9997618085192876, 0.016703538007620394, 0.007787803206600496),
    (-0.004218272313784908, 0.01676428917578574, 0.9998505712290796, 0.007319834406613235),
    (0.0, 0.0, 0.0, 1.0),
)

SCENE_R_T_BC = (
    (-0.9998924382824463, 0.013974435039524601, -0.004452755429012945, -0.025185240132668554),
    (-0.014046994136513329, -0.9997618085192878, 0.016703538007620408, 0.006889770004550476),
    (-0.004218272313786235, 0.016764289175785773, 0.9998505712290797, 0.0070501575948875),
    (0.0, 0.0, 0.0, 1.0),
)

SCENE_STEREO_28 = StereoCalibration(
    device_id="28",
    calibration_id="headset-28-scene-pov-v1",
    left=PinholeIntrinsics(
        eye="left",
        width=2328,
        height=1744,
        fx=872.0,
        fy=872.0,
        cx=1164.0,
        cy=872.0,
        t_bc=SCENE_L_T_BC,
    ),
    right=PinholeIntrinsics(
        eye="right",
        width=2328,
        height=1744,
        fx=872.0,
        fy=872.0,
        cx=1164.0,
        cy=872.0,
        t_bc=SCENE_R_T_BC,
    ),
    baseline_m=0.0639,
)
