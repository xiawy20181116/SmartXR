"""Shared bbox->head math test vectors, Python consumer (M4-1, YAN-80).

Runs every applicable case in
godot-android/fixtures/bbox_math_test_vectors.json through
``smartxr.geometry`` and asserts within tolerance. The same fixture is
consumed at runtime by the GDScript probe
(godot-android/tests/script_only_bbox_math_probe.gd via
tools/run_godot_bbox_math_probe.ps1), which locks the duplicated math in
AndroidMovingCard.gd against the same numbers.

Python verifies the chain up to the head point (projection + head
conversion). The yaw/pitch/depth/angular-size decomposition and the final
anchor position are GDScript-only math; here they are checked for fixture
self-consistency (the expected position must recompose from the expected
yaw/pitch/depth exactly as ``_target_position_from_bbox_anchor`` does) so a
hand-edited fixture cannot drift silently between the two consumers.
"""

import json
import math
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from smartxr import geometry

FIXTURE_PATH = os.path.join(
    REPO_ROOT, "godot-android", "fixtures", "bbox_math_test_vectors.json"
)
PROBE_PATH = os.path.join(
    REPO_ROOT, "godot-android", "tests", "script_only_bbox_math_probe.gd"
)
RUNNER_PATH = os.path.join(REPO_ROOT, "tools", "run_godot_bbox_math_probe.ps1")
CARD_PATH = os.path.join(
    REPO_ROOT, "godot-android", "scripts", "AndroidMovingCard.gd"
)


def load_fixture():
    with open(FIXTURE_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def read_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class TestFixtureShape(unittest.TestCase):
    def setUp(self):
        self.fixture = load_fixture()

    def test_schema_version_is_one(self):
        self.assertEqual(self.fixture["schema_version"], 1)

    def test_sections_present_and_non_empty(self):
        for section in ("projection_cases", "head_conversion_cases", "full_chain_cases"):
            self.assertIn(section, self.fixture)
            self.assertGreater(len(self.fixture[section]), 0, section)

    def test_case_names_unique_per_section(self):
        for section in ("projection_cases", "head_conversion_cases", "full_chain_cases"):
            names = [case["name"] for case in self.fixture[section]]
            self.assertEqual(len(names), len(set(names)), section)

    def test_tolerances_declared(self):
        tolerances = self.fixture["tolerances"]
        self.assertLessEqual(tolerances["python_abs"], 1e-6)
        self.assertLessEqual(tolerances["gdscript_abs"], 1e-3)

    def test_full_chain_fov_matches_card_consts(self):
        # The GDScript chain reads BBOX_*_FOV_DEG consts, so every full_chain
        # case must be authored with the card's FOV pair.
        card_source = read_text(CARD_PATH)
        self.assertIn("const BBOX_HORIZONTAL_FOV_DEG := 70.0", card_source)
        self.assertIn("const BBOX_VERTICAL_FOV_DEG := 43.0", card_source)
        for case in self.fixture["full_chain_cases"]:
            self.assertEqual(case["input"]["horizontal_fov_deg"], 70.0, case["name"])
            self.assertEqual(case["input"]["vertical_fov_deg"], 43.0, case["name"])


class TestProjectionCases(unittest.TestCase):
    def setUp(self):
        self.fixture = load_fixture()
        self.tol = self.fixture["tolerances"]["python_abs"]

    def assert_vec_close(self, actual, expected, name):
        self.assertEqual(len(actual), len(expected), name)
        for index, (a, e) in enumerate(zip(actual, expected)):
            self.assertAlmostEqual(a, e, delta=self.tol, msg=f"{name}[{index}]")

    def test_projection_cases(self):
        for case in self.fixture["projection_cases"]:
            params = case["input"]
            actual = geometry.project_bbox_center_to_camera_point(
                params["cx"],
                params["cy"],
                params["image_w"],
                params["image_h"],
                params["horizontal_fov_deg"],
                params["vertical_fov_deg"],
                params["depth_m"],
            )
            self.assert_vec_close(actual, case["expected"]["camera_point"], case["name"])

    def test_centered_pixel_projects_straight_ahead(self):
        # Hand-verified anchor case: the fixture must contain the trivial
        # centered-pixel case and its expectation must be exactly [0, 0, d].
        cases = {case["name"]: case for case in self.fixture["projection_cases"]}
        case = cases["centered_default_fov"]
        self.assertEqual(case["expected"]["camera_point"], [0.0, 0.0, case["input"]["depth_m"]])


class TestHeadConversionCases(unittest.TestCase):
    def setUp(self):
        self.fixture = load_fixture()
        self.tol = self.fixture["tolerances"]["python_abs"]

    def assert_vec_close(self, actual, expected, name):
        for index, (a, e) in enumerate(zip(actual, expected)):
            self.assertAlmostEqual(a, e, delta=self.tol, msg=f"{name}[{index}]")

    def test_head_conversion_cases(self):
        for case in self.fixture["head_conversion_cases"]:
            point = case["input"]["point"]
            matrix = case["input"]["right_eye_to_head"]
            if matrix is not None and len(matrix) < 16:
                # GDScript-only fallback: Python has no short-matrix branch,
                # so verify the expected values equal the default flip.
                self.assertTrue(case.get("gdscript_only"), case["name"])
                actual = geometry.vst_camera_point_to_head(point)
            elif matrix is None:
                actual = geometry.vst_camera_point_to_head(point)
            else:
                actual = geometry.vst_camera_point_to_head(point, matrix)
            self.assert_vec_close(actual, case["expected"]["head_point"], case["name"])

    def test_default_flip_forward_is_negative_z(self):
        cases = {case["name"]: case for case in self.fixture["head_conversion_cases"]}
        case = cases["default_flip_forward"]
        self.assertEqual(case["expected"]["head_point"], [0.0, -0.0, -1.35])


class TestFullChainCases(unittest.TestCase):
    def setUp(self):
        self.fixture = load_fixture()
        self.tol = self.fixture["tolerances"]["python_abs"]

    def assert_vec_close(self, actual, expected, name):
        for index, (a, e) in enumerate(zip(actual, expected)):
            self.assertAlmostEqual(a, e, delta=self.tol, msg=f"{name}[{index}]")

    def test_chain_through_smartxr_geometry(self):
        for case in self.fixture["full_chain_cases"]:
            params = case["input"]
            camera_point = geometry.project_bbox_center_to_camera_point(
                params["cx"],
                params["cy"],
                params["image_w"],
                params["image_h"],
                params["horizontal_fov_deg"],
                params["vertical_fov_deg"],
                params["depth_m"],
            )
            self.assert_vec_close(
                camera_point, case["expected"]["camera_point"], case["name"] + ":camera"
            )
            matrix = params["right_eye_to_head"]
            if params["uses_eye_to_head_anchor"] and matrix is not None and len(matrix) >= 16:
                head_point = geometry.vst_camera_point_to_head(camera_point, matrix)
            else:
                head_point = geometry.vst_camera_point_to_head(camera_point)
            self.assert_vec_close(
                head_point, case["expected"]["head_point"], case["name"] + ":head"
            )

    def test_fixture_self_consistency(self):
        # The yaw/pitch/depth/angular/position values are produced by
        # GDScript-only card math; pin their internal consistency so the
        # fixture cannot be hand-edited into a state where the two consumers
        # silently disagree about what "correct" means.
        for case in self.fixture["full_chain_cases"]:
            params = case["input"]
            expected = case["expected"]
            head = expected["head_point"]
            # yaw/pitch decompose from the expected head point.
            yaw_deg = math.degrees(math.atan2(head[0], -head[2]))
            pitch_deg = math.degrees(math.atan2(head[1], math.hypot(head[0], head[2])))
            self.assertAlmostEqual(expected["yaw_deg"], yaw_deg, delta=self.tol, msg=case["name"])
            self.assertAlmostEqual(
                expected["pitch_deg"], pitch_deg, delta=self.tol, msg=case["name"]
            )
            # depth_m: point_head.length() when the eye-to-head anchor is
            # active, the input depth otherwise.
            if params["uses_eye_to_head_anchor"]:
                depth = math.sqrt(head[0] ** 2 + head[1] ** 2 + head[2] ** 2)
            else:
                depth = params["depth_m"]
            self.assertAlmostEqual(expected["depth_m"], depth, delta=self.tol, msg=case["name"])
            # Angular size from the same pinhole focal lengths.
            fx = (params["image_w"] * 0.5) / math.tan(
                math.radians(params["horizontal_fov_deg"]) * 0.5
            )
            fy = (params["image_h"] * 0.5) / math.tan(
                math.radians(params["vertical_fov_deg"]) * 0.5
            )
            self.assertAlmostEqual(
                expected["angular_size_deg"][0],
                math.degrees(2.0 * math.atan((params["w"] * 0.5) / fx)),
                delta=self.tol,
                msg=case["name"],
            )
            self.assertAlmostEqual(
                expected["angular_size_deg"][1],
                math.degrees(2.0 * math.atan((params["h"] * 0.5) / fy)),
                delta=self.tol,
                msg=case["name"],
            )
            # The final position must recompose from yaw/pitch/depth exactly
            # as _target_position_from_bbox_anchor does.
            yaw = math.radians(expected["yaw_deg"])
            pitch = math.radians(expected["pitch_deg"])
            horizontal_depth = expected["depth_m"] * math.cos(pitch)
            recomposed = [
                horizontal_depth * math.sin(yaw),
                expected["depth_m"] * math.sin(pitch),
                -horizontal_depth * math.cos(yaw),
            ]
            self.assert_vec_close(
                recomposed, expected["position"], case["name"] + ":position"
            )

    def test_centered_chain_is_trivial(self):
        cases = {case["name"]: case for case in self.fixture["full_chain_cases"]}
        case = cases["chain_centered_no_matrix"]
        self.assertEqual(case["expected"]["yaw_deg"], 0.0)
        self.assertEqual(case["expected"]["pitch_deg"], 0.0)
        self.assertEqual(case["expected"]["depth_m"], case["input"]["depth_m"])
        self.assertEqual(case["expected"]["head_point"][2], -case["input"]["depth_m"])


class TestProbeAndRunnerWiring(unittest.TestCase):
    """Static pins on the GDScript consumer so the cross-language lock cannot
    be detached from the fixture without failing the suite."""

    def test_probe_consumes_fixture_and_card_methods(self):
        probe_source = read_text(PROBE_PATH)
        self.assertIn("SMARTXR_BBOX_MATH_FIXTURE_PATH", probe_source)
        self.assertIn("SMARTXR_BBOX_MATH_CARD_SCRIPT", probe_source)
        for method in (
            "_anchor_from_bbox",
            "_convert_vst_camera_point_to_head_convention",
            "_transform_right_vst_point_to_head",
            "_target_position_from_bbox_anchor",
        ):
            self.assertIn(method, probe_source)
        self.assertIn("_vst_right_eye_to_head_matrix", probe_source)
        self.assertIn("_vst_uses_eye_to_head_anchor", probe_source)

    def test_runner_stages_scripts_without_project(self):
        runner_source = read_text(RUNNER_PATH)
        self.assertIn("script_only_bbox_math_probe.gd", runner_source)
        self.assertIn("bbox_math_test_vectors.json", runner_source)
        # No-project-mode staging (HANDOFF.md rule): the card preloads sibling
        # scripts, so the runner must copy scripts/ into a temp cwd that has
        # no project.godot.
        self.assertIn(".tmp\\bbox_math_probe", runner_source)
        self.assertIn("Copy-Item", runner_source)
        self.assertIn("-WorkingDirectory $WorkDir", runner_source)
        self.assertNotIn("project.godot", runner_source)


if __name__ == "__main__":
    unittest.main()
