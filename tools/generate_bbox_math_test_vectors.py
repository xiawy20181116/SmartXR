"""Generator for godot-android/fixtures/bbox_math_test_vectors.json (M4-1, YAN-80).

The fixture is the checked-in source of truth; this script exists so the
vectors can be regenerated/extended deterministically. Projection and head
conversion expectations come straight from ``smartxr.geometry`` (the Python
single source of truth). The yaw/pitch/depth/angular-size decomposition and
the final anchor position are GDScript-only math (``_anchor_from_bbox`` /
``_target_position_from_bbox_anchor`` in ``AndroidMovingCard.gd``); the
formulas are replicated here in float64 so the fixture can pin them, and the
cross-language lock comes from the GDScript probe
(``godot-android/tests/script_only_bbox_math_probe.gd``) reproducing the same
numbers at runtime.

Conventions per docs/proxy_targets_payload_contract.md: VST camera axes are
+X right / +Y down / +Z forward; head axes are +X right / +Y up / -Z forward;
the default conversion is [x, -y, -z]; a row-major 4x4 right_eye_to_head
matrix replaces the default flip when present (GDScript falls back to the
flip when the matrix has fewer than 16 elements).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from smartxr import geometry

# Must match BBOX_HORIZONTAL_FOV_DEG / BBOX_VERTICAL_FOV_DEG in
# AndroidMovingCard.gd: the GDScript full-chain math reads the card consts,
# so every full_chain case is generated with this pair (the probe asserts
# the match and fails on drift).
CARD_HFOV_DEG = 70.0
CARD_VFOV_DEG = 43.0

DEFAULT_OUTPUT = os.path.join(
    REPO_ROOT, "godot-android", "fixtures", "bbox_math_test_vectors.json"
)


def identity_matrix(tx: float = 0.0, ty: float = 0.0, tz: float = 0.0) -> list[float]:
    return [
        1.0, 0.0, 0.0, tx,
        0.0, 1.0, 0.0, ty,
        0.0, 0.0, 1.0, tz,
        0.0, 0.0, 0.0, 1.0,
    ]


def flip_matrix(tx: float = 0.0, ty: float = 0.0, tz: float = 0.0) -> list[float]:
    """Rotation equal to the default [x, -y, -z] axis flip (180 deg about X)."""
    return [
        1.0, 0.0, 0.0, tx,
        0.0, -1.0, 0.0, ty,
        0.0, 0.0, -1.0, tz,
        0.0, 0.0, 0.0, 1.0,
    ]


def rotation_y90_matrix() -> list[float]:
    """90 deg about +Y: maps (x, y, z) -> (z, y, -x)."""
    return [
        0.0, 0.0, 1.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        -1.0, 0.0, 0.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def ry_then_flip_matrix(yaw_deg: float, tx: float, ty: float, tz: float) -> list[float]:
    """Ry(yaw) composed with the default flip, plus a translation."""
    c = math.cos(math.radians(yaw_deg))
    s = math.sin(math.radians(yaw_deg))
    return [
        c, 0.0, -s, tx,
        0.0, -1.0, 0.0, ty,
        -s, 0.0, -c, tz,
        0.0, 0.0, 0.0, 1.0,
    ]


def angular_size_deg(
    w: float, h: float, image_w: float, image_h: float, hfov_deg: float, vfov_deg: float
) -> list[float]:
    fx = (image_w * 0.5) / math.tan(math.radians(hfov_deg) * 0.5)
    fy = (image_h * 0.5) / math.tan(math.radians(vfov_deg) * 0.5)
    return [
        math.degrees(2.0 * math.atan((w * 0.5) / fx)),
        math.degrees(2.0 * math.atan((h * 0.5) / fy)),
    ]


def anchor_from_head_point(
    head: list[float], depth_m: float, uses_eye_to_head: bool
) -> tuple[float, float, float]:
    """yaw/pitch/depth exactly as GDScript _anchor_from_bbox derives them."""
    yaw_deg = math.degrees(math.atan2(head[0], -head[2]))
    pitch_deg = math.degrees(math.atan2(head[1], math.hypot(head[0], head[2])))
    if uses_eye_to_head:
        depth_out = math.sqrt(head[0] ** 2 + head[1] ** 2 + head[2] ** 2)
    else:
        depth_out = depth_m
    return yaw_deg, pitch_deg, depth_out


def position_from_anchor(yaw_deg: float, pitch_deg: float, depth_m: float) -> list[float]:
    """Final position exactly as GDScript _target_position_from_bbox_anchor."""
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    horizontal_depth = depth_m * math.cos(pitch)
    return [
        horizontal_depth * math.sin(yaw),
        depth_m * math.sin(pitch),
        -horizontal_depth * math.cos(yaw),
    ]


def projection_case(
    name: str,
    cx: float,
    cy: float,
    image_w: float,
    image_h: float,
    hfov_deg: float,
    vfov_deg: float,
    depth_m: float,
) -> dict:
    return {
        "name": name,
        "input": {
            "cx": cx,
            "cy": cy,
            "image_w": image_w,
            "image_h": image_h,
            "horizontal_fov_deg": hfov_deg,
            "vertical_fov_deg": vfov_deg,
            "depth_m": depth_m,
        },
        "expected": {
            "camera_point": geometry.project_bbox_center_to_camera_point(
                cx, cy, image_w, image_h, hfov_deg, vfov_deg, depth_m
            ),
        },
    }


def head_conversion_case(
    name: str,
    point: list[float],
    right_eye_to_head: list[float] | None,
    gdscript_only: bool = False,
) -> dict:
    if right_eye_to_head is not None and len(right_eye_to_head) >= 16:
        expected = geometry.vst_camera_point_to_head(point, right_eye_to_head)
    else:
        # None, or the GDScript-only short-matrix fallback: default flip.
        expected = geometry.vst_camera_point_to_head(point)
    case = {
        "name": name,
        "input": {
            "point": point,
            "right_eye_to_head": right_eye_to_head,
        },
        "expected": {"head_point": expected},
    }
    if gdscript_only:
        case["gdscript_only"] = True
    return case


def full_chain_case(
    name: str,
    cx: float,
    cy: float,
    w: float,
    h: float,
    image_w: float,
    image_h: float,
    depth_m: float,
    uses_eye_to_head_anchor: bool = False,
    right_eye_to_head: list[float] | None = None,
) -> dict:
    camera_point = geometry.project_bbox_center_to_camera_point(
        cx, cy, image_w, image_h, CARD_HFOV_DEG, CARD_VFOV_DEG, depth_m
    )
    if uses_eye_to_head_anchor and right_eye_to_head is not None and len(right_eye_to_head) >= 16:
        head_point = geometry.vst_camera_point_to_head(camera_point, right_eye_to_head)
    else:
        head_point = geometry.vst_camera_point_to_head(camera_point)
    yaw_deg, pitch_deg, depth_out = anchor_from_head_point(
        head_point, depth_m, uses_eye_to_head_anchor
    )
    return {
        "name": name,
        "input": {
            "cx": cx,
            "cy": cy,
            "w": w,
            "h": h,
            "image_w": image_w,
            "image_h": image_h,
            "horizontal_fov_deg": CARD_HFOV_DEG,
            "vertical_fov_deg": CARD_VFOV_DEG,
            "depth_m": depth_m,
            "uses_eye_to_head_anchor": uses_eye_to_head_anchor,
            "right_eye_to_head": right_eye_to_head,
        },
        "expected": {
            "camera_point": camera_point,
            "head_point": head_point,
            "yaw_deg": yaw_deg,
            "pitch_deg": pitch_deg,
            "depth_m": depth_out,
            "angular_size_deg": angular_size_deg(
                w, h, image_w, image_h, CARD_HFOV_DEG, CARD_VFOV_DEG
            ),
            "position": position_from_anchor(yaw_deg, pitch_deg, depth_out),
        },
    }


def build_fixture() -> dict:
    flip_with_baseline = flip_matrix(0.032, -0.041, 0.012)
    short_matrix = [1.0, 0.0, 0.0]

    projection_cases = [
        # Hand check: centered pixel -> [0, 0, depth].
        projection_case("centered_default_fov", 320.0, 240.0, 640.0, 480.0, 70.0, 43.0, 1.35),
        projection_case("off_center_right_down", 480.0, 360.0, 640.0, 480.0, 70.0, 43.0, 2.0),
        projection_case("corner_top_left", 0.0, 0.0, 640.0, 480.0, 70.0, 43.0, 1.0),
        projection_case("corner_bottom_right", 872.0, 652.0, 872.0, 652.0, 70.0, 43.0, 3.5),
        projection_case("off_center_near_depth", 300.0, 200.0, 872.0, 652.0, 70.0, 43.0, 0.65),
        projection_case("off_center_far_depth", 560.0, 420.0, 872.0, 652.0, 70.0, 43.0, 4.0),
        # Hand check: centered pixel is FOV-independent -> [0, 0, depth].
        projection_case("centered_wide_fov", 640.0, 360.0, 1280.0, 720.0, 90.0, 60.0, 1.0),
        projection_case("off_center_wide_fov", 320.0, 540.0, 1280.0, 720.0, 90.0, 60.0, 1.0),
        projection_case("off_center_narrow_fov", 600.0, 150.0, 800.0, 600.0, 50.0, 30.0, 0.75),
    ]

    head_conversion_cases = [
        head_conversion_case("default_flip_off_center", [0.2, -0.3, 1.5], None),
        # Hand check: forward stays forward, [0,0,d] -> [0,0,-d].
        head_conversion_case("default_flip_forward", [0.0, 0.0, 1.35], None),
        # Identity matrix means NO flip: the matrix path replaces the default
        # conversion, it does not compose with it.
        head_conversion_case("matrix_identity", [0.2, -0.3, 1.5], identity_matrix()),
        head_conversion_case(
            "matrix_pure_translation", [-0.45, 0.18, 2.2], identity_matrix(0.1, -0.05, 0.02)
        ),
        # Hand check: 180 deg about X reproduces the default flip exactly.
        head_conversion_case("matrix_pure_rotation_x180", [0.2, -0.3, 1.5], flip_matrix()),
        # Hand check: (x, y, z) -> (z, y, -x).
        head_conversion_case("matrix_pure_rotation_y90", [0.2, -0.3, 1.5], rotation_y90_matrix()),
        head_conversion_case(
            "matrix_combined_flip_translation", [0.3, -0.25, 1.8], flip_with_baseline
        ),
        # GDScript-only fallback (_transform_right_vst_point_to_head): fewer
        # than 16 matrix elements -> default flip. Python's
        # vst_camera_point_to_head has no such branch, so the Python test
        # verifies the expected values equal the default flip instead.
        head_conversion_case(
            "matrix_short_fallback", [0.2, -0.3, 1.5], short_matrix, gdscript_only=True
        ),
    ]

    full_chain_cases = [
        # Hand check: centered pixel -> camera [0,0,d] -> head [0,0,-d],
        # yaw = pitch = 0, position [0,0,-d].
        full_chain_case("chain_centered_no_matrix", 320.0, 240.0, 100.0, 80.0, 640.0, 480.0, 1.35),
        full_chain_case("chain_off_center_no_matrix", 560.0, 420.0, 180.0, 240.0, 872.0, 652.0, 2.0),
        full_chain_case("chain_corner_no_matrix", 40.0, 440.0, 60.0, 60.0, 640.0, 480.0, 0.9),
        full_chain_case(
            "chain_matrix_identity",
            480.0, 300.0, 120.0, 90.0, 640.0, 480.0, 1.5,
            uses_eye_to_head_anchor=True,
            right_eye_to_head=identity_matrix(),
        ),
        # Hand check: centered pixel through flip+baseline -> head
        # [0.032, -0.041, -1.338]; depth_m becomes point_head.length().
        full_chain_case(
            "chain_matrix_flip_translation",
            436.0, 326.0, 180.0, 240.0, 872.0, 652.0, 1.35,
            uses_eye_to_head_anchor=True,
            right_eye_to_head=flip_with_baseline,
        ),
        full_chain_case(
            "chain_matrix_rotated_combined",
            380.0, 200.0, 90.0, 120.0, 640.0, 480.0, 2.5,
            uses_eye_to_head_anchor=True,
            right_eye_to_head=ry_then_flip_matrix(10.0, 0.03, -0.04, 0.01),
        ),
        # GDScript-only: the eye-to-head flag is on but the matrix is short,
        # so _transform_right_vst_point_to_head falls back to the default
        # flip while depth_m still becomes point_head.length().
        full_chain_case(
            "chain_short_matrix_fallback",
            480.0, 360.0, 100.0, 80.0, 640.0, 480.0, 2.0,
            uses_eye_to_head_anchor=True,
            right_eye_to_head=short_matrix,
        ),
    ]

    return {
        "schema_version": 1,
        "description": (
            "Shared bbox->head math test vectors consumed by both "
            "tests/test_bbox_math_vectors.py (smartxr.geometry) and "
            "godot-android/tests/script_only_bbox_math_probe.gd "
            "(AndroidMovingCard.gd). Regenerate with "
            "tools/generate_bbox_math_test_vectors.py."
        ),
        "conventions": {
            "camera_axes": "+X right, +Y down, +Z forward",
            "head_axes": "+X right, +Y up, -Z forward",
            "default_conversion": "[x, -y, -z]",
            "right_eye_to_head": "row-major 4x4; <16 elements falls back to the default flip (GDScript only)",
        },
        "tolerances": {
            "python_abs": 1e-09,
            "gdscript_abs": 0.0001,
        },
        "projection_cases": projection_cases,
        "head_conversion_cases": head_conversion_cases,
        "full_chain_cases": full_chain_cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    fixture = build_fixture()
    with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(fixture, handle, indent=2)
        handle.write("\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
