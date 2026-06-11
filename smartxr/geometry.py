"""Pure camera/head geometry shared by SmartXR publishers.

Conventions (see docs/proxy_targets_payload_contract.md):

- Raw VST camera axes are ``+X right, +Y down, +Z forward``.
- Godot/head axes are ``+X right, +Y up, -Z forward``, so the default
  conversion is ``[x, -y, -z]`` and forward targets have negative Godot Z.
- When a 4x4 row-major ``right_eye_to_head`` matrix is available it is
  applied instead of the default axis flip.

The same math exists in GDScript inside ``AndroidMovingCard.gd``
(`_anchor_from_bbox` / `_convert_vst_camera_point_to_head_convention`); this
module is the Python single source of truth for publisher-side conversion.
"""

from __future__ import annotations

import math
from typing import Any


def as_float(value: Any, fallback: float) -> float:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    return fallback


def clamped_fov_deg(value: Any, fallback: float) -> float:
    return min(max(as_float(value, fallback), 1.0), 179.0)


def project_bbox_center_to_camera_point(
    cx: float,
    cy: float,
    image_w: float,
    image_h: float,
    horizontal_fov_deg: float,
    vertical_fov_deg: float,
    depth_m: float,
) -> list[float]:
    """Project a bbox center pixel through the camera FOV onto a point at
    ``depth_m`` along the ray, in VST camera axes."""
    fx = (image_w * 0.5) / math.tan(math.radians(horizontal_fov_deg) * 0.5)
    fy = (image_h * 0.5) / math.tan(math.radians(vertical_fov_deg) * 0.5)
    nx = (cx - image_w * 0.5) / fx
    ny = (cy - image_h * 0.5) / fy
    length = math.sqrt(nx * nx + ny * ny + 1.0)
    return [nx / length * depth_m, ny / length * depth_m, 1.0 / length * depth_m]


def vst_camera_point_to_head(point: list[float], right_eye_to_head: list[float] | None = None) -> list[float]:
    """Convert a VST camera-space point to Godot/head convention.

    Applies the row-major 4x4 ``right_eye_to_head`` transform when provided,
    otherwise falls back to the default ``[x, -y, -z]`` axis flip.
    """
    if right_eye_to_head is None:
        return [point[0], -point[1], -point[2]]
    matrix = right_eye_to_head
    return [
        matrix[0] * point[0] + matrix[1] * point[1] + matrix[2] * point[2] + matrix[3],
        matrix[4] * point[0] + matrix[5] * point[1] + matrix[6] * point[2] + matrix[7],
        matrix[8] * point[0] + matrix[9] * point[1] + matrix[10] * point[2] + matrix[11],
    ]
