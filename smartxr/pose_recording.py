"""Pose sidecar normalization helpers."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


INT_FIELDS = {
    "schema_version",
    "pose_time_us",
    "godot_ticks_usec",
    "system_unix_time_usec",
    "sample_index",
}
OPTIONAL_INT_FIELDS = {"flush_drops"}
BOOL_FIELDS = {"xr_active", "tracking_valid"}
STRING_FIELDS = {"timestamp_kind", "pose_time_clock", "reference_space", "camera_node"}


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _to_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not number.is_integer():
        raise ValueError(f"{field} must be an integer")
    return int(number)


def _to_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _to_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    raise ValueError(f"{field} must be boolean")


def _to_float_vector(value: Any, length: int, field: str, shape_name: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field} must be a {shape_name}")
    if len(value) != length:
        raise ValueError(f"{field} must be a {shape_name}")
    return [_to_float(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _to_float_matrix(
    value: Any,
    rows: int,
    cols: int,
    field: str,
    shape_name: str,
) -> list[list[float]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field} must be a {shape_name}")
    if len(value) != rows:
        raise ValueError(f"{field} must be a {shape_name}")
    return [
        _to_float_vector(row, cols, f"{field}[{row_index}]", f"{cols}-element row")
        for row_index, row in enumerate(value)
    ]


def normalize_pose_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a pose sidecar row into predictable Python scalar/container types."""
    if not isinstance(row, Mapping):
        raise ValueError("row must be a mapping")

    normalized: dict[str, Any] = {}
    for field in INT_FIELDS:
        normalized[field] = _to_int(row[field], field)
    for field in OPTIONAL_INT_FIELDS:
        if field in row:
            normalized[field] = _to_int(row[field], field)
    for field in STRING_FIELDS:
        normalized[field] = str(row[field])
    for field in BOOL_FIELDS:
        normalized[field] = _to_bool(row[field], field)

    normalized["world_from_head"] = _to_float_matrix(
        row["world_from_head"], 4, 4, "world_from_head", "4x4 matrix"
    )
    normalized["head_position_m"] = _to_float_vector(
        row["head_position_m"], 3, "head_position_m", "vec3"
    )
    if "head_basis_rows" in row:
        normalized["head_basis_rows"] = _to_float_matrix(
            row["head_basis_rows"], 3, 3, "head_basis_rows", "3x3 matrix"
        )
    return normalized


def _mapping_timestamp_us(value: Mapping[str, Any], side: str) -> int:
    if not isinstance(value, Mapping):
        raise ValueError(f"{side} must be a mapping")
    if "timestamp_us" in value:
        return _to_int(value["timestamp_us"], f"{side}.timestamp_us")
    if "exposure_us" in value:
        return _to_int(value["exposure_us"], f"{side}.exposure_us")
    raise ValueError(f"{side} must include timestamp_us or exposure_us")


def frame_mid_exposure_us(left: Mapping[str, Any], right: Mapping[str, Any]) -> int:
    """Return the integer midpoint between left/right frame timestamps."""
    left_us = _mapping_timestamp_us(left, "left")
    right_us = _mapping_timestamp_us(right, "right")
    return (left_us + right_us) // 2


def sync_quality(delta_ms: float) -> str:
    if not _is_numeric(delta_ms) or not math.isfinite(delta_ms) or delta_ms < 0:
        raise ValueError("delta_ms must be a finite non-negative number")
    if delta_ms <= 8:
        return "good"
    if delta_ms <= 15:
        return "usable"
    return "bad"
