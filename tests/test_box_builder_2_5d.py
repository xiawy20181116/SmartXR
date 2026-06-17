"""L1 projection/derivation math tests for the 2.5D box builder (YAN-108)."""

from __future__ import annotations

import math
import unittest

from smartxr.box_builder_2_5d import (
    DEFAULT_HFOV_DEG,
    DEFAULT_VFOV_DEG,
    EXTENT_NOMINAL_HUMAN,
    EXTENT_PROJECTED_BBOX,
    NOMINAL_HUMAN_DEPTH_M,
    NOMINAL_HUMAN_HEIGHT_M,
    NOMINAL_HUMAN_WIDTH_M,
    Bbox2DNorm,
    box_vertices,
    build_2_5d_bbox,
    landmark_from_vertices,
)
from smartxr.tracking_raw_schema import validate_message


class Bbox2DNormTests(unittest.TestCase):
    def test_from_xywh_norm(self):
        b = Bbox2DNorm.from_xywh_norm(0.2, 0.1, 0.4, 0.6)
        self.assertAlmostEqual(b.cx, 0.4)
        self.assertAlmostEqual(b.cy, 0.4)
        self.assertAlmostEqual(b.w, 0.4)
        self.assertAlmostEqual(b.h, 0.6)

    def test_from_xyxy_norm(self):
        b = Bbox2DNorm.from_xyxy_norm(0.2, 0.1, 0.6, 0.7)
        self.assertAlmostEqual(b.cx, 0.4)
        self.assertAlmostEqual(b.cy, 0.4)
        self.assertAlmostEqual(b.w, 0.4)
        self.assertAlmostEqual(b.h, 0.6)


class VertexOrderTests(unittest.TestCase):
    def test_canonical_sign_order(self):
        v = box_vertices([0.0, 0.0, 0.0], [1.0, 2.0, 3.0])
        self.assertEqual(len(v), 8)
        # (-,-,-), (-,-,+), (-,+,-), (-,+,+), (+,-,-), (+,-,+), (+,+,-), (+,+,+)
        self.assertEqual(v[0], [-1.0, -2.0, -3.0])
        self.assertEqual(v[1], [-1.0, -2.0, 3.0])
        self.assertEqual(v[2], [-1.0, 2.0, -3.0])
        self.assertEqual(v[7], [1.0, 2.0, 3.0])


class ProjectionTests(unittest.TestCase):
    def test_centered_bbox_projects_onto_forward_axis(self):
        # Center pixel -> point straight ahead at depth on +Z.
        out = build_2_5d_bbox(Bbox2DNorm(0.5, 0.5, 0.2, 0.5), depth_m=2.0)
        cx, cy, cz = out["center"]
        self.assertAlmostEqual(cx, 0.0, places=9)
        self.assertAlmostEqual(cy, 0.0, places=9)
        self.assertAlmostEqual(cz, 2.0, places=9)

    def test_projected_extent_scales_with_depth_and_fov(self):
        bbox = Bbox2DNorm(0.5, 0.5, 0.3, 0.4)
        depth = 1.8
        out = build_2_5d_bbox(bbox, depth_m=depth)
        hx, hy, hz = out["half_extent"]
        expected_hx = bbox.w * math.tan(math.radians(DEFAULT_HFOV_DEG) * 0.5) * depth
        expected_hy = bbox.h * math.tan(math.radians(DEFAULT_VFOV_DEG) * 0.5) * depth
        self.assertAlmostEqual(hx, expected_hx, places=9)
        self.assertAlmostEqual(hy, expected_hy, places=9)
        self.assertAlmostEqual(hz, NOMINAL_HUMAN_DEPTH_M * 0.5, places=9)

    def test_closer_person_yields_larger_box(self):
        bbox = Bbox2DNorm(0.5, 0.5, 0.3, 0.6)
        near = build_2_5d_bbox(bbox, depth_m=1.0)["half_extent"]
        far = build_2_5d_bbox(bbox, depth_m=3.0)["half_extent"]
        self.assertGreater(near[0], 0.0)
        # X/Y scale with depth; at 3x depth the same pixel box is 3x metric size.
        self.assertAlmostEqual(far[0] / near[0], 3.0, places=6)
        self.assertAlmostEqual(far[1] / near[1], 3.0, places=6)

    def test_nominal_human_extent_mode(self):
        out = build_2_5d_bbox(
            Bbox2DNorm(0.5, 0.5, 0.9, 0.9), depth_m=2.0, extent_mode=EXTENT_NOMINAL_HUMAN
        )
        hx, hy, hz = out["half_extent"]
        self.assertAlmostEqual(hx, NOMINAL_HUMAN_WIDTH_M * 0.5)
        self.assertAlmostEqual(hy, NOMINAL_HUMAN_HEIGHT_M * 0.5)
        self.assertAlmostEqual(hz, NOMINAL_HUMAN_DEPTH_M * 0.5)

    def test_off_center_bbox_shifts_in_expected_direction(self):
        # bbox right of center -> +X; below center -> +Y (down).
        out = build_2_5d_bbox(Bbox2DNorm(0.75, 0.75, 0.1, 0.1), depth_m=2.0)
        cx, cy, cz = out["center"]
        self.assertGreater(cx, 0.0)
        self.assertGreater(cy, 0.0)
        self.assertGreater(cz, 0.0)

    def test_depth_must_be_positive(self):
        with self.assertRaises(ValueError):
            build_2_5d_bbox(Bbox2DNorm(0.5, 0.5, 0.2, 0.5), depth_m=0.0)

    def test_unknown_extent_mode_rejected(self):
        with self.assertRaises(ValueError):
            build_2_5d_bbox(Bbox2DNorm(0.5, 0.5, 0.2, 0.5), depth_m=1.0, extent_mode="bogus")


class LandmarkRuleTests(unittest.TestCase):
    def setUp(self):
        # Axis-aligned box at center (1, 2, 3), half-extent (0.5, 1.0, 0.2).
        self.center = [1.0, 2.0, 3.0]
        self.half = [0.5, 1.0, 0.2]
        self.vertices = box_vertices(self.center, self.half)

    def test_centroid_is_center(self):
        lm = landmark_from_vertices(self.vertices, "centroid")
        self.assertEqual(lm["rule"], "centroid")
        for got, want in zip(lm["point"], self.center):
            self.assertAlmostEqual(got, want, places=9)

    def test_bottom_center_is_max_y(self):
        # Camera +Y is down, so feet = largest y.
        lm = landmark_from_vertices(self.vertices, "bottom_center")
        self.assertAlmostEqual(lm["point"][0], self.center[0])
        self.assertAlmostEqual(lm["point"][1], self.center[1] + self.half[1])
        self.assertAlmostEqual(lm["point"][2], self.center[2])

    def test_top_center_is_min_y(self):
        lm = landmark_from_vertices(self.vertices, "top_center")
        self.assertAlmostEqual(lm["point"][1], self.center[1] - self.half[1])

    def test_front_top_center_is_min_y_min_z(self):
        lm = landmark_from_vertices(self.vertices, "front_top_center")
        self.assertAlmostEqual(lm["point"][0], self.center[0])
        self.assertAlmostEqual(lm["point"][1], self.center[1] - self.half[1])
        self.assertAlmostEqual(lm["point"][2], self.center[2] - self.half[2])

    def test_unknown_rule_rejected(self):
        with self.assertRaises(ValueError):
            landmark_from_vertices(self.vertices, "nope")


class SchemaConformanceTests(unittest.TestCase):
    """The geometry the builder produces must satisfy the frozen C1 schema."""

    def _wrap(self, out: dict) -> dict:
        return {
            "type": "tracking_raw",
            "schema_version": 1,
            "sequence": 0,
            "source": "replay",
            "timestamp_ms": 1000.0,
            "detections": [
                {
                    "id": "person-1",
                    "state": "confirmed",
                    "age_frames": 0,
                    "confidence": 0.9,
                    "timestamp_ms": 1000.0,
                    "bbox_3d": out["bbox_3d"],
                    "landmark": out["landmark"],
                    "source_frame": {
                        "coordinate_space": "vst_right_camera",
                        "units": "meters",
                        "depth_source": "constant_depth",
                    },
                    "pose_quality": "fixed_depth",
                }
            ],
        }

    def test_builder_output_passes_c1_schema(self):
        for rule in ("centroid", "bottom_center", "top_center", "front_top_center"):
            out = build_2_5d_bbox(
                Bbox2DNorm(0.4, 0.55, 0.25, 0.5), depth_m=1.8, landmark_rule=rule
            )
            errors = validate_message(self._wrap(out))
            self.assertEqual(errors, [], f"rule={rule}: {errors}")


if __name__ == "__main__":
    unittest.main()
