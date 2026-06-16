"""2.5D bounding-box builder for the C1 (tracking_raw) producer (YAN-108).

Turns a 2D person detection (normalized image-space bbox) plus a **pluggable
scalar depth** into the authoritative C1 ``bbox_3d`` (8 vertices) and a derived
``landmark``, in the ``vst_right_camera`` frame.

This is the v1 "2.5D approximation" the architecture baseline calls for: the
bbox center is projected through the camera FOV onto a point at the given depth,
then a box is extruded around it. X/Y half-extents come from the 2D bbox extent
projected to metric at that depth (so a closer person yields a larger box);
the Z (toward-camera) half-extent uses a nominal human thickness because a
single VST eye cannot measure it. The result is tagged ``pose_quality =
fixed_depth``. Upgrading depth (mono_metric, stereo) swaps the scalar and the
tags **behind** C1 without changing this shape -- see
``docs/tracking_raw_payload_contract.md``.

Conventions (``architecture_modules.md`` section 11, ``smartxr/geometry.py``):
``vst_right_camera`` axes are +X right, +Y down, +Z forward (positive z); meters.
Module 3 applies the camera->head conversion when it builds C2; module 1 stays
in camera-native axes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from smartxr.geometry import project_bbox_center_to_camera_point

# Nominal standing-human box, meters. Width/height are fallbacks for the
# ``nominal_human`` extent mode; depth is always nominal (un-measurable from one
# eye). Matches the values used by the C1 fake producer.
NOMINAL_HUMAN_WIDTH_M = 0.5
NOMINAL_HUMAN_HEIGHT_M = 1.7
NOMINAL_HUMAN_DEPTH_M = 0.35

# VST right-eye camera FOV used on-device (AndroidMovingCard BBOX_*_FOV_DEG).
DEFAULT_HFOV_DEG = 70.0
DEFAULT_VFOV_DEG = 43.0

# Extent modes for the X/Y box size.
EXTENT_PROJECTED_BBOX = "projected_bbox"  # scale from the 2D bbox (default)
EXTENT_NOMINAL_HUMAN = "nominal_human"    # fixed nominal human width/height


@dataclass(frozen=True)
class CameraIntrinsics:
    """Camera FOV for the pinhole projection. Image size cancels out because
    detections are supplied in normalized [0,1] image coordinates."""

    horizontal_fov_deg: float = DEFAULT_HFOV_DEG
    vertical_fov_deg: float = DEFAULT_VFOV_DEG


VST_RIGHT_CAMERA = CameraIntrinsics()


@dataclass(frozen=True)
class Bbox2DNorm:
    """A 2D detection box in normalized image coordinates (0..1), center+size."""

    cx: float
    cy: float
    w: float
    h: float

    @classmethod
    def from_xywh_norm(cls, x: float, y: float, w: float, h: float) -> "Bbox2DNorm":
        """From a normalized top-left x/y + width/height box."""
        return cls(cx=x + w * 0.5, cy=y + h * 0.5, w=w, h=h)

    @classmethod
    def from_xyxy_norm(cls, x1: float, y1: float, x2: float, y2: float) -> "Bbox2DNorm":
        """From a normalized corner box."""
        return cls(cx=(x1 + x2) * 0.5, cy=(y1 + y2) * 0.5, w=x2 - x1, h=y2 - y1)


# Canonical vertex order: sign-product of half-extents over (x, y, z), i.e.
# (-,-,-), (-,-,+), (-,+,-), (-,+,+), (+,-,-), (+,-,+), (+,+,-), (+,+,+).
_VERTEX_SIGNS = [(sx, sy, sz) for sx in (-1.0, 1.0) for sy in (-1.0, 1.0) for sz in (-1.0, 1.0)]


def box_vertices(center: list[float], half_extent: list[float]) -> list[list[float]]:
    """8 axis-aligned box vertices from a center + half-extent, canonical order."""
    cx, cy, cz = center
    hx, hy, hz = half_extent
    return [[cx + sx * hx, cy + sy * hy, cz + sz * hz] for sx, sy, sz in _VERTEX_SIGNS]


def _bounds(vertices: list[list[float]]) -> tuple[list[float], list[float], list[float]]:
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]
    mins = [min(xs), min(ys), min(zs)]
    maxs = [max(xs), max(ys), max(zs)]
    center = [(mins[i] + maxs[i]) * 0.5 for i in range(3)]
    return mins, maxs, center


# Landmark rules: each maps the 8 box vertices to a single derived point.
# Camera axes are +X right, +Y down, +Z forward, so "top" = min y, "bottom" =
# max y, and "front" (the face nearest the camera) = min z.
def _rule_centroid(vertices):
    n = len(vertices)
    return [sum(v[i] for v in vertices) / n for i in range(3)]


def _rule_bottom_center(vertices):
    mins, maxs, c = _bounds(vertices)
    return [c[0], maxs[1], c[2]]  # feet: largest y (down)


def _rule_top_center(vertices):
    mins, maxs, c = _bounds(vertices)
    return [c[0], mins[1], c[2]]  # head top: smallest y (up)


def _rule_front_top_center(vertices):
    mins, maxs, c = _bounds(vertices)
    return [c[0], mins[1], mins[2]]  # top, on the face nearest the camera


LANDMARK_RULES: dict[str, Callable[[list[list[float]]], list[float]]] = {
    "centroid": _rule_centroid,
    "bottom_center": _rule_bottom_center,
    "top_center": _rule_top_center,
    "front_top_center": _rule_front_top_center,
}

DEFAULT_LANDMARK_RULE = "centroid"


def landmark_from_vertices(vertices: list[list[float]], rule: str) -> dict:
    """Compute the derived ``landmark`` {rule, point} from the 8 box vertices."""
    if rule not in LANDMARK_RULES:
        raise ValueError(f"unknown landmark rule {rule!r}; known: {sorted(LANDMARK_RULES)}")
    return {"rule": rule, "point": LANDMARK_RULES[rule](vertices)}


def build_2_5d_bbox(
    bbox: Bbox2DNorm,
    depth_m: float,
    intrinsics: CameraIntrinsics = VST_RIGHT_CAMERA,
    *,
    extent_mode: str = EXTENT_PROJECTED_BBOX,
    nominal_depth_m: float = NOMINAL_HUMAN_DEPTH_M,
    landmark_rule: str = DEFAULT_LANDMARK_RULE,
) -> dict:
    """Build the C1 geometry for one detection.

    Returns ``{"bbox_3d": {"vertices": [...8...]}, "landmark": {...},
    "center": [...], "half_extent": [...]}`` in ``vst_right_camera`` axes. The
    producer attaches id/state/confidence/source_frame/pose_quality; this
    function owns only the pure 3D geometry so it is fully unit-testable.
    """
    if depth_m <= 0.0:
        raise ValueError(f"depth_m must be positive, got {depth_m}")

    center = project_bbox_center_to_camera_point(
        bbox.cx, bbox.cy, 1.0, 1.0,
        intrinsics.horizontal_fov_deg, intrinsics.vertical_fov_deg, depth_m,
    )

    if extent_mode == EXTENT_PROJECTED_BBOX:
        # Metric half-size of a normalized span s at this depth on the image
        # plane is s * tan(fov/2) * depth (image width cancels with focal length).
        half_x = bbox.w * math.tan(math.radians(intrinsics.horizontal_fov_deg) * 0.5) * depth_m
        half_y = bbox.h * math.tan(math.radians(intrinsics.vertical_fov_deg) * 0.5) * depth_m
    elif extent_mode == EXTENT_NOMINAL_HUMAN:
        half_x = NOMINAL_HUMAN_WIDTH_M * 0.5
        half_y = NOMINAL_HUMAN_HEIGHT_M * 0.5
    else:
        raise ValueError(f"unknown extent_mode {extent_mode!r}")
    half_z = nominal_depth_m * 0.5

    half_extent = [half_x, half_y, half_z]
    vertices = box_vertices(center, half_extent)
    landmark = landmark_from_vertices(vertices, landmark_rule)
    return {
        "bbox_3d": {"vertices": vertices},
        "landmark": landmark,
        "center": center,
        "half_extent": half_extent,
    }
