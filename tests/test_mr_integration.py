"""Module 3 (MR integration) C1 -> C2 converter tests (YAN-110).

Verification ladder (baseline section 6):

- **L0/L1 bbox-math fixture dual-lock**: the converter's camera->head alignment
  is driven through every applicable case of
  ``godot-android/fixtures/bbox_math_test_vectors.json`` -- the same fixture that
  locks the math against the GDScript card -- so module 3 cannot drift from the
  single source of truth (``smartxr.geometry``).
- **L1 unit**: state mapping, calibration, staleness, confidence, empty->None,
  multi-target, id shaping, diagnostics.
- **L2 fake end-to-end**: the C1 fake producer (``smartxr.tracking_raw_fakes``)
  feeds the converter and the canonical C2 consumer (``smartxr.schema``) accepts
  every frame across a moving sequence with stable ids.
- **L3 device smoke**: real device only; documented in ``docs/mr_integration.md``.
"""

import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from smartxr import geometry
from smartxr.mr_integration import (
    Calibration,
    TrackingRawToProxyTargetsConverter,
    convert_tracking_raw_message,
)
from smartxr.schema import validate_message as validate_proxy_targets
from smartxr.tracking_raw_fakes import build_fake_tracking_raw_message
from smartxr.tracking_raw_schema import validate_message as validate_tracking_raw

C1_SAMPLE_PATH = os.path.join(REPO_ROOT, "godot-android", "fixtures", "tracking_raw_sample.json")
C2_FIXTURE_PATH = os.path.join(
    REPO_ROOT, "godot-android", "fixtures", "proxy_targets_from_c1_sample.json"
)
BBOX_FIXTURE_PATH = os.path.join(
    REPO_ROOT, "godot-android", "fixtures", "bbox_math_test_vectors.json"
)


def _read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _c1_detection(
    point,
    *,
    track_id="person-1",
    state="confirmed",
    confidence=0.9,
    coordinate_space="vst_right_camera",
    timestamp_ms=1000.0,
    pose_quality="fixed_depth",
):
    """A minimal valid C1 detection whose landmark sits at ``point``."""
    # An axis-aligned unit box around the point keeps bbox_3d valid; only the
    # landmark drives the converter's position.
    verts = [
        [point[0] + sx * 0.25, point[1] + sy * 0.85, point[2] + sz * 0.175]
        for sx in (-1.0, 1.0)
        for sy in (-1.0, 1.0)
        for sz in (-1.0, 1.0)
    ]
    return {
        "id": track_id,
        "state": state,
        "age_frames": 0,
        "confidence": confidence,
        "timestamp_ms": timestamp_ms,
        "bbox_3d": {"vertices": verts},
        "landmark": {"rule": "centroid", "point": list(point)},
        "source_frame": {
            "coordinate_space": coordinate_space,
            "units": "meters",
            "depth_source": "constant_depth",
        },
        "pose_quality": pose_quality,
    }


def _c1_message(detections, *, source="test_source", sequence=0, timestamp_ms=1000.0):
    return {
        "type": "tracking_raw",
        "schema_version": 1,
        "sequence": sequence,
        "source": source,
        "timestamp_ms": timestamp_ms,
        "detections": detections,
    }


class TestSampleFixtureLock(unittest.TestCase):
    def test_converting_c1_sample_equals_checked_in_c2_fixture(self):
        c1 = _read_json(C1_SAMPLE_PATH)
        self.assertEqual(validate_tracking_raw(c1), [], "C1 sample must be valid")
        c2 = convert_tracking_raw_message(c1)
        self.assertIsNotNone(c2)
        self.assertEqual(c2, _read_json(C2_FIXTURE_PATH))

    def test_checked_in_c2_fixture_passes_proxy_targets_gate(self):
        self.assertEqual(validate_proxy_targets(_read_json(C2_FIXTURE_PATH)), [])


class TestBboxMathDualLock(unittest.TestCase):
    """Drive the converter's alignment through the dual-locked head-conversion
    fixture so module 3 stays pinned to smartxr.geometry / the GDScript card."""

    def setUp(self):
        self.fixture = _read_json(BBOX_FIXTURE_PATH)
        self.tol = self.fixture["tolerances"]["python_abs"]

    def test_head_conversion_cases_match_converter_position(self):
        checked = 0
        for case in self.fixture["head_conversion_cases"]:
            if case.get("gdscript_only"):
                continue
            point = case["input"]["point"]
            matrix = case["input"]["right_eye_to_head"]
            calibration = (
                Calibration.with_right_eye_to_head(matrix)
                if matrix is not None
                else Calibration.monocular()
            )
            c2 = convert_tracking_raw_message(
                _c1_message([_c1_detection(point)]), calibration=calibration
            )
            self.assertIsNotNone(c2, case["name"])
            position = c2["targets"][0]["transform"]["position"]
            for i, (a, e) in enumerate(zip(position, case["expected"]["head_point"])):
                self.assertAlmostEqual(a, e, delta=self.tol, msg=f"{case['name']}[{i}]")
            checked += 1
        self.assertGreater(checked, 0)

    def test_full_chain_head_point_matches_converter(self):
        # The full chain's head_point is what module 3 must reproduce from a C1
        # landmark sitting at the chain's camera_point.
        for case in self.fixture["full_chain_cases"]:
            params = case["input"]
            matrix = params["right_eye_to_head"]
            uses = params["uses_eye_to_head_anchor"] and matrix is not None and len(matrix) >= 16
            calibration = (
                Calibration.with_right_eye_to_head(matrix) if uses else Calibration.monocular()
            )
            c2 = convert_tracking_raw_message(
                _c1_message([_c1_detection(case["expected"]["camera_point"])]),
                calibration=calibration,
            )
            position = c2["targets"][0]["transform"]["position"]
            for i, (a, e) in enumerate(zip(position, case["expected"]["head_point"])):
                self.assertAlmostEqual(a, e, delta=self.tol, msg=f"{case['name']}[{i}]")


class TestAlignmentAndCalibration(unittest.TestCase):
    def test_monocular_default_flip_matches_geometry(self):
        point = [0.2, -0.3, 1.5]
        c2 = convert_tracking_raw_message(_c1_message([_c1_detection(point)]))
        position = c2["targets"][0]["transform"]["position"]
        self.assertEqual(position, geometry.vst_camera_point_to_head(point))

    def test_right_eye_to_head_matrix_applied(self):
        point = [0.3, -0.25, 1.8]
        matrix = [
            1.0, 0.0, 0.0, 0.032,
            0.0, -1.0, 0.0, -0.041,
            0.0, 0.0, -1.0, 0.012,
            0.0, 0.0, 0.0, 1.0,
        ]
        c2 = convert_tracking_raw_message(
            _c1_message([_c1_detection(point)]),
            calibration=Calibration.with_right_eye_to_head(matrix),
        )
        position = c2["targets"][0]["transform"]["position"]
        self.assertEqual(position, geometry.vst_camera_point_to_head(point, matrix))
        self.assertEqual(c2["targets"][0]["coordinate_space"], "head")

    def test_short_matrix_degrades_to_monocular_flip(self):
        cal = Calibration.with_right_eye_to_head([1.0, 0.0, 0.0])
        self.assertFalse(cal.uses_right_eye_to_head)
        self.assertEqual(cal.label, "monocular_default_flip")

    def test_head_space_landmark_passes_through_unconverted(self):
        point = [0.1, 0.2, -1.5]
        c2 = convert_tracking_raw_message(
            _c1_message([_c1_detection(point, coordinate_space="head")])
        )
        target = c2["targets"][0]
        self.assertEqual(target["transform"]["position"], point)
        self.assertEqual(target["coordinate_space"], "head")

    def test_world_space_landmark_passes_through_unconverted(self):
        point = [1.0, 0.5, -2.0]
        c2 = convert_tracking_raw_message(
            _c1_message([_c1_detection(point, coordinate_space="world")])
        )
        self.assertEqual(c2["targets"][0]["transform"]["position"], point)
        self.assertEqual(c2["targets"][0]["coordinate_space"], "world")


class TestStateMapping(unittest.TestCase):
    def _state_for(self, c1_state):
        c2 = convert_tracking_raw_message(
            _c1_message([_c1_detection([0.0, 0.0, 1.0], state=c1_state)])
        )
        return c2["targets"][0]["state"]

    def test_lifecycle_states_map(self):
        self.assertEqual(self._state_for("tentative"), "tracked")
        self.assertEqual(self._state_for("confirmed"), "tracked")
        self.assertEqual(self._state_for("lost"), "predicted")
        self.assertEqual(self._state_for("deleted"), "lost")

    def test_unknown_state_defaults_to_lost(self):
        self.assertEqual(self._state_for("garbage"), "lost")

    def test_all_mapped_states_are_valid_c2_states(self):
        for c1_state in ("tentative", "confirmed", "lost", "deleted"):
            c2 = convert_tracking_raw_message(
                _c1_message([_c1_detection([0.0, 0.0, 1.0], state=c1_state)])
            )
            self.assertEqual(validate_proxy_targets(c2), [], c1_state)


class TestStaleness(unittest.TestCase):
    def test_lagging_tracked_pose_downgrades_to_stale(self):
        det = _c1_detection([0.0, 0.0, 1.0], state="confirmed", timestamp_ms=500.0)
        message = _c1_message([det], timestamp_ms=1000.0)
        c2 = convert_tracking_raw_message(message, stale_after_ms=200.0)
        self.assertEqual(c2["targets"][0]["state"], "stale")

    def test_within_threshold_stays_tracked(self):
        det = _c1_detection([0.0, 0.0, 1.0], state="confirmed", timestamp_ms=900.0)
        message = _c1_message([det], timestamp_ms=1000.0)
        c2 = convert_tracking_raw_message(message, stale_after_ms=200.0)
        self.assertEqual(c2["targets"][0]["state"], "tracked")

    def test_no_threshold_never_downgrades(self):
        det = _c1_detection([0.0, 0.0, 1.0], state="confirmed", timestamp_ms=0.0)
        message = _c1_message([det], timestamp_ms=1_000_000.0)
        c2 = convert_tracking_raw_message(message)
        self.assertEqual(c2["targets"][0]["state"], "tracked")

    def test_predicted_is_not_downgraded(self):
        det = _c1_detection([0.0, 0.0, 1.0], state="lost", timestamp_ms=0.0)
        message = _c1_message([det], timestamp_ms=1000.0)
        c2 = convert_tracking_raw_message(message, stale_after_ms=200.0)
        self.assertEqual(c2["targets"][0]["state"], "predicted")


class TestConfidenceAndFiltering(unittest.TestCase):
    def test_confidence_passthrough(self):
        c2 = convert_tracking_raw_message(
            _c1_message([_c1_detection([0.0, 0.0, 1.0], confidence=0.42)])
        )
        self.assertEqual(c2["targets"][0]["confidence"], 0.42)

    def test_confidence_clamped(self):
        c2 = convert_tracking_raw_message(
            _c1_message([_c1_detection([0.0, 0.0, 1.0], confidence=1.5)])
        )
        self.assertEqual(c2["targets"][0]["confidence"], 1.0)

    def test_min_confidence_filters(self):
        message = _c1_message(
            [
                _c1_detection([0.0, 0.0, 1.0], track_id="a", confidence=0.2),
                _c1_detection([1.0, 0.0, 1.0], track_id="b", confidence=0.8),
            ]
        )
        c2 = convert_tracking_raw_message(message, min_confidence=0.5)
        ids = [t["target_id"] for t in c2["targets"]]
        self.assertEqual(ids, ["test_source-b"])

    def test_all_filtered_returns_none(self):
        message = _c1_message([_c1_detection([0.0, 0.0, 1.0], confidence=0.1)])
        self.assertIsNone(convert_tracking_raw_message(message, min_confidence=0.5))


class TestEmptyAndMultiTarget(unittest.TestCase):
    def test_empty_detections_returns_none(self):
        self.assertIsNone(convert_tracking_raw_message(_c1_message([])))

    def test_non_dict_returns_none(self):
        self.assertIsNone(convert_tracking_raw_message("not a message"))

    def test_multi_target_card_binds_to_primary(self):
        message = _c1_message(
            [
                _c1_detection([0.0, 0.0, 1.0], track_id="alice"),
                _c1_detection([1.0, 0.0, 2.0], track_id="bob"),
            ]
        )
        c2 = convert_tracking_raw_message(message)
        self.assertEqual(len(c2["targets"]), 2)
        self.assertEqual(len(c2["cards"]), 1)
        self.assertEqual(c2["cards"][0]["target_id"], c2["targets"][0]["target_id"])
        self.assertEqual(validate_proxy_targets(c2), [])

    def test_target_id_is_source_prefixed_once(self):
        c2 = convert_tracking_raw_message(
            _c1_message([_c1_detection([0.0, 0.0, 1.0], track_id="person-7")], source="vst")
        )
        self.assertEqual(c2["targets"][0]["target_id"], "vst-person-7")
        # Already-prefixed ids are not double-prefixed.
        c2b = convert_tracking_raw_message(
            _c1_message([_c1_detection([0.0, 0.0, 1.0], track_id="vst-person-7")], source="vst")
        )
        self.assertEqual(c2b["targets"][0]["target_id"], "vst-person-7")


class TestDiagnostics(unittest.TestCase):
    def test_diagnostics_present_and_gate_safe(self):
        c2 = convert_tracking_raw_message(
            _c1_message([_c1_detection([0.0, 0.0, 1.0])]), include_diagnostics=True
        )
        diag = c2["targets"][0]["mr_alignment"]
        self.assertEqual(diag["calibration"], "monocular_default_flip")
        self.assertEqual(diag["pose_quality"], "fixed_depth")
        # Diagnostics must not trip the C2 raw-source-field gate.
        self.assertEqual(validate_proxy_targets(c2), [])

    def test_no_diagnostics_by_default(self):
        c2 = convert_tracking_raw_message(_c1_message([_c1_detection([0.0, 0.0, 1.0])]))
        self.assertNotIn("mr_alignment", c2["targets"][0])


class TestFakeProducerEndToEnd(unittest.TestCase):
    """L2: C1 fake producer -> module-3 converter -> canonical C2 consumer."""

    def test_moving_sequence_round_trips_with_stable_ids(self):
        converter = TrackingRawToProxyTargetsConverter()
        seen_ids = set()
        sequences = []
        for step in range(30):
            c1 = build_fake_tracking_raw_message(elapsed_s=step * 0.1, sequence=step)
            self.assertEqual(validate_tracking_raw(c1), [], f"fake C1 step {step}")
            c2 = converter.convert(c1)
            self.assertIsNotNone(c2)
            self.assertEqual(validate_proxy_targets(c2), [], f"C2 step {step}")
            sequences.append(c2["sequence"])
            for target in c2["targets"]:
                seen_ids.add(target["target_id"])
        # One stable track id across the whole sequence.
        self.assertEqual(seen_ids, {"fake_tracking-person-7"})
        # Converter re-stamps a monotonic sequence.
        self.assertEqual(sequences, list(range(30)))

    def test_converter_sequence_only_advances_on_emitted_frames(self):
        converter = TrackingRawToProxyTargetsConverter()
        # Empty frame -> None, sequence does not advance.
        self.assertIsNone(converter.convert(_c1_message([])))
        c2 = converter.convert(_c1_message([_c1_detection([0.0, 0.0, 1.0])]))
        self.assertEqual(c2["sequence"], 0)


class TestConvertCli(unittest.TestCase):
    """Display-wiring tool: C1 (.json/.jsonl) -> validated C2 (.jsonl)."""

    def test_cli_converts_c1_sample_to_valid_c2(self):
        import tempfile

        from smartxr.cli.convert_tracking_raw import main

        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "out.jsonl")
            rc = main(["--input", C1_SAMPLE_PATH, "--output", out_path])
            self.assertEqual(rc, 0)
            with open(out_path, encoding="utf-8") as handle:
                lines = [json.loads(line) for line in handle if line.strip()]
            self.assertEqual(len(lines), 1)
            self.assertEqual(validate_proxy_targets(lines[0]), [])

    def test_cli_rejects_invalid_c1_input(self):
        import tempfile

        from smartxr.cli.convert_tracking_raw import main

        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.json")
            with open(bad, "w", encoding="utf-8") as handle:
                json.dump({"type": "tracking_raw", "schema_version": 1}, handle)
            self.assertEqual(main(["--input", bad]), 1)

    def test_cli_jsonl_stream_skips_empty_frames(self):
        import tempfile

        from smartxr.cli.convert_tracking_raw import main

        with tempfile.TemporaryDirectory() as tmp:
            in_path = os.path.join(tmp, "in.jsonl")
            out_path = os.path.join(tmp, "out.jsonl")
            with open(in_path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(_c1_message([], sequence=0)) + "\n")
                handle.write(
                    json.dumps(_c1_message([_c1_detection([0.0, 0.0, 1.0])], sequence=1)) + "\n"
                )
            self.assertEqual(main(["--input", in_path, "--output", out_path]), 0)
            with open(out_path, encoding="utf-8") as handle:
                lines = [json.loads(line) for line in handle if line.strip()]
            self.assertEqual(len(lines), 1)


if __name__ == "__main__":
    unittest.main()
