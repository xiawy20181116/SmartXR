"""YAN-119 stereo VST calibration/depth tests.

Pure-python coverage for the first stereo-depth slice: scale the #28 POV Scene
calibration to recorded resolution, triangulate rectified L/R detections, emit
hot-swappable depth records, and map the stereo depth value into C1 without a
contract change.
"""

from __future__ import annotations

import unittest

from smartxr.detection_backend import detections_from_records
from smartxr.stereo_depth import (
    ANCHOR_KIND_BBOX_CENTER,
    ANCHOR_KIND_BBOX_TOP_CENTER,
    DEPTH_SOURCE_KNOWN_DISTANCE_GT,
    DEPTH_SOURCE_POV_STEREO,
    DEPTH_SOURCE_RAW_STEREO,
    FRAME_PROVENANCE_POV,
    FRAME_PROVENANCE_RAW,
    POSE_QUALITY_STEREO,
    SCENE_STEREO_28,
    StereoDepthSource,
    StereoDetectionPair,
    StereoGateConfig,
    build_known_distance_record,
    build_stereo_session_metadata,
    replace_depth_value,
    triangulate_detection_pair,
)
from smartxr.tracker import HumanTracker
from smartxr.tracking_raw_producer import TrackingRawProducer
from smartxr.tracking_raw_schema import validate_message


class CalibrationScalingTests(unittest.TestCase):
    def test_scales_scene_intrinsics_uniformly_and_preserves_fov(self):
        scaled = SCENE_STEREO_28.scaled_to(1164, 872)

        self.assertEqual(scaled.left.width, 1164)
        self.assertEqual(scaled.left.height, 872)
        self.assertEqual(scaled.left.fx, 436.0)
        self.assertEqual(scaled.left.fy, 436.0)
        self.assertEqual(scaled.left.cx, 582.0)
        self.assertEqual(scaled.left.cy, 436.0)
        self.assertAlmostEqual(
            scaled.left.horizontal_fov_deg,
            SCENE_STEREO_28.left.horizontal_fov_deg,
            places=9,
        )
        self.assertAlmostEqual(
            scaled.left.vertical_fov_deg,
            SCENE_STEREO_28.left.vertical_fov_deg,
            places=9,
        )
        self.assertAlmostEqual(scaled.baseline_m, 0.0639, places=4)
        self.assertEqual(scaled.frame_provenance, FRAME_PROVENANCE_POV)
        self.assertEqual(scaled.calibration_kind, "pov_virtual")

    def test_rejects_non_uniform_recorded_resolution(self):
        with self.assertRaises(ValueError):
            SCENE_STEREO_28.scaled_to(1000, 600)


class StereoTriangulationTests(unittest.TestCase):
    def test_triangulates_metric_depth_from_rectified_disparity(self):
        scaled = SCENE_STEREO_28.scaled_to(1164, 872)
        pair = StereoDetectionPair(
            pair_id="pair-000042",
            frame_id=42,
            person_id="person-1",
            left_bbox_xyxy=(640.0, 240.0, 720.0, 520.0),
            right_bbox_xyxy=(608.0, 240.0, 688.0, 520.0),
            confidence=0.91,
        )

        record = triangulate_detection_pair(
            pair,
            scaled,
            known_distance_m=0.8706375,
            tolerance_m=0.02,
        )

        self.assertEqual(record["pair_id"], "pair-000042")
        self.assertEqual(record["frame_id"], 42)
        self.assertEqual(record["person_id"], "person-1")
        self.assertEqual(record["depth_source"], DEPTH_SOURCE_POV_STEREO)
        self.assertFalse(record["is_ground_truth"])
        self.assertEqual(record["pose_quality"], POSE_QUALITY_STEREO)
        self.assertEqual(record["calibration_ref"], scaled.calibration_id)
        self.assertAlmostEqual(record["depth_m"], 0.8706375, places=7)
        self.assertEqual(record["anchor_kind"], ANCHOR_KIND_BBOX_CENTER)
        self.assertEqual(record["left_anchor_px"], [680.0, 380.0])
        self.assertEqual(record["right_anchor_px"], [648.0, 380.0])
        self.assertAlmostEqual(record["validation"]["known_distance_m"], 0.8706375)
        self.assertAlmostEqual(record["validation"]["depth_error_m"], 0.0)
        self.assertTrue(record["validation"]["within_tolerance"])
        self.assertAlmostEqual(record["position"][2], record["depth_m"])

    def test_triangulates_bbox_top_center_anchor_and_emits_diagnostics(self):
        scaled = SCENE_STEREO_28.scaled_to(1164, 872)
        pair = StereoDetectionPair(
            pair_id="pair-000044",
            frame_id=44,
            person_id="person-1",
            left_bbox_xyxy=(640.0, 240.0, 720.0, 520.0),
            right_bbox_xyxy=(608.0, 250.0, 688.0, 530.0),
            confidence=0.91,
        )

        record = triangulate_detection_pair(
            pair,
            scaled,
            anchor_kind=ANCHOR_KIND_BBOX_TOP_CENTER,
        )

        self.assertEqual(record["anchor_kind"], ANCHOR_KIND_BBOX_TOP_CENTER)
        self.assertEqual(record["left_anchor_px"], [680.0, 240.0])
        self.assertEqual(record["right_anchor_px"], [648.0, 250.0])
        self.assertAlmostEqual(record["disparity_px"], 32.0)
        self.assertAlmostEqual(record["vertical_error_px"], -10.0)
        self.assertAlmostEqual(record["depth_m"], 0.8706375, places=7)
        self.assertAlmostEqual(record["position"][0], 0.19569375)
        self.assertAlmostEqual(record["position"][1], -0.3913875)
        self.assertAlmostEqual(record["position"][2], record["depth_m"])

    def test_gate_success_emits_ok_and_gate_diagnostics(self):
        scaled = SCENE_STEREO_28.scaled_to(1164, 872)
        pair = StereoDetectionPair(
            pair_id="pair-000045",
            frame_id=45,
            person_id="person-1",
            left_bbox_xyxy=(640.0, 240.0, 720.0, 520.0),
            right_bbox_xyxy=(608.0, 250.0, 688.0, 530.0),
            confidence=0.91,
        )

        record = triangulate_detection_pair(
            pair,
            scaled,
            anchor_kind=ANCHOR_KIND_BBOX_TOP_CENTER,
            gate_config=StereoGateConfig(
                min_confidence=0.4,
                min_depth_m=0.2,
                max_depth_m=5.0,
                min_box_ratio=0.5,
                max_box_ratio=2.0,
                max_vertical_error_px=12.0,
            ),
        )

        self.assertTrue(record["stereo_ok"])
        self.assertIsNone(record["rejection_reason"])
        self.assertEqual(record["gates"]["confidence_min"], 0.4)
        self.assertEqual(record["gates"]["depth_range_m"], [0.2, 5.0])
        self.assertEqual(record["gates"]["box_ratio_range"], [0.5, 2.0])
        self.assertEqual(record["gates"]["vertical_error_max_px"], 12.0)
        self.assertAlmostEqual(record["box_width_ratio"], 1.0)
        self.assertAlmostEqual(record["box_height_ratio"], 1.0)

    def test_gates_reject_with_rejection_reason(self):
        scaled = SCENE_STEREO_28.scaled_to(1164, 872)

        cases = [
            (
                "low_confidence",
                StereoDetectionPair(
                    pair_id="pair-000046",
                    frame_id=46,
                    person_id="person-1",
                    left_bbox_xyxy=(640.0, 240.0, 720.0, 520.0),
                    right_bbox_xyxy=(608.0, 240.0, 688.0, 520.0),
                    confidence=0.39,
                ),
                StereoGateConfig(min_confidence=0.4),
            ),
            (
                "box_width_ratio_out_of_range",
                StereoDetectionPair(
                    pair_id="pair-000047",
                    frame_id=47,
                    person_id="person-1",
                    left_bbox_xyxy=(640.0, 240.0, 720.0, 520.0),
                    right_bbox_xyxy=(608.0, 240.0, 648.0, 520.0),
                    confidence=0.91,
                ),
                StereoGateConfig(min_box_ratio=0.75, max_box_ratio=1.5),
            ),
            (
                "box_height_ratio_out_of_range",
                StereoDetectionPair(
                    pair_id="pair-000048",
                    frame_id=48,
                    person_id="person-1",
                    left_bbox_xyxy=(640.0, 240.0, 720.0, 520.0),
                    right_bbox_xyxy=(608.0, 240.0, 688.0, 380.0),
                    confidence=0.91,
                ),
                StereoGateConfig(min_box_ratio=0.75, max_box_ratio=1.5),
            ),
            (
                "vertical_error_too_large",
                StereoDetectionPair(
                    pair_id="pair-000049",
                    frame_id=49,
                    person_id="person-1",
                    left_bbox_xyxy=(640.0, 240.0, 720.0, 520.0),
                    right_bbox_xyxy=(608.0, 260.0, 688.0, 540.0),
                    confidence=0.91,
                ),
                StereoGateConfig(max_vertical_error_px=12.0),
            ),
            (
                "depth_out_of_range",
                StereoDetectionPair(
                    pair_id="pair-000050",
                    frame_id=50,
                    person_id="person-1",
                    left_bbox_xyxy=(640.0, 240.0, 720.0, 520.0),
                    right_bbox_xyxy=(636.0, 240.0, 716.0, 520.0),
                    confidence=0.91,
                ),
                StereoGateConfig(min_depth_m=0.2, max_depth_m=5.0),
            ),
        ]

        for expected_reason, pair, gate_config in cases:
            with self.subTest(expected_reason):
                record = triangulate_detection_pair(
                    pair,
                    scaled,
                    anchor_kind=ANCHOR_KIND_BBOX_TOP_CENTER,
                    gate_config=gate_config,
                )

                self.assertFalse(record["stereo_ok"])
                self.assertEqual(record["rejection_reason"], expected_reason)
                self.assertEqual(record["depth_source"], DEPTH_SOURCE_POV_STEREO)
                self.assertNotIn("depth_m", record)
                self.assertNotIn("position", record)

    def test_rejects_zero_or_negative_disparity(self):
        scaled = SCENE_STEREO_28.scaled_to(1164, 872)
        pair = StereoDetectionPair(
            pair_id="pair-000043",
            frame_id=43,
            person_id="person-1",
            left_bbox_xyxy=(608.0, 240.0, 688.0, 520.0),
            right_bbox_xyxy=(640.0, 240.0, 720.0, 520.0),
            confidence=0.91,
        )

        with self.assertRaises(ValueError):
            triangulate_detection_pair(pair, scaled)


class StereoRecordTests(unittest.TestCase):
    def test_session_metadata_contains_hot_swappable_identifiers(self):
        scaled = SCENE_STEREO_28.scaled_to(1164, 872)
        metadata = build_stereo_session_metadata(
            scaled,
            pair_count=12,
            dropped_unpaired_left=2,
            dropped_unpaired_right=1,
            max_skew_frames=0,
        )

        self.assertEqual(metadata["schema_version"], 1)
        self.assertEqual(metadata["device_id"], "28")
        self.assertEqual(metadata["frame_provenance"], FRAME_PROVENANCE_POV)
        self.assertIn(FRAME_PROVENANCE_RAW, metadata["reserved_frame_provenance"])
        self.assertEqual(metadata["calibration"]["kind"], "pov_virtual")
        self.assertIn("physical_raw", metadata["calibration"]["reserved_kinds"])
        self.assertEqual(metadata["pairing"]["pair_id_scheme"], "pair-{frame_id:06d}")
        self.assertEqual(metadata["pairing"]["frame_id_source"], "shared_vst_shm_frame_id")
        self.assertEqual(metadata["pairing"]["stats"]["pair_count"], 12)
        self.assertEqual(metadata["pairing"]["stats"]["dropped_unpaired_left"], 2)
        self.assertEqual(metadata["pairing"]["stats"]["dropped_unpaired_right"], 1)

    def test_known_distance_record_is_the_ground_truth_anchor(self):
        record = build_known_distance_record(
            pair_id="pair-000042",
            frame_id=42,
            person_id="person-1",
            known_distance_m=1.25,
            calibration_ref="measured-rig-v1",
        )

        self.assertEqual(record["depth_source"], DEPTH_SOURCE_KNOWN_DISTANCE_GT)
        self.assertTrue(record["is_ground_truth"])
        self.assertEqual(record["pose_quality"], POSE_QUALITY_STEREO)
        self.assertEqual(record["depth_m"], 1.25)
        self.assertEqual(record["position"], [0.0, 0.0, 1.25])

    def test_depth_value_swap_preserves_record_identity(self):
        original = build_known_distance_record(
            pair_id="pair-000042",
            frame_id=42,
            person_id="person-1",
            known_distance_m=1.25,
            calibration_ref="measured-rig-v1",
        )

        raw = replace_depth_value(
            original,
            depth_m=1.23,
            position=[0.01, -0.02, 1.23],
            depth_source=DEPTH_SOURCE_RAW_STEREO,
            calibration_ref="headset-28-physical-raw-v1",
            frame_provenance=FRAME_PROVENANCE_RAW,
            is_ground_truth=False,
        )

        self.assertEqual(raw["pair_id"], original["pair_id"])
        self.assertEqual(raw["frame_id"], original["frame_id"])
        self.assertEqual(raw["person_id"], original["person_id"])
        self.assertEqual(raw["depth_source"], DEPTH_SOURCE_RAW_STEREO)
        self.assertEqual(raw["frame_provenance"], FRAME_PROVENANCE_RAW)
        self.assertEqual(raw["schema_version"], original["schema_version"])
        self.assertFalse(raw["is_ground_truth"])

    def test_depth_value_swap_drops_stale_validation(self):
        scaled = SCENE_STEREO_28.scaled_to(1164, 872)
        original = triangulate_detection_pair(
            StereoDetectionPair(
                pair_id="pair-000042",
                frame_id=42,
                person_id="person-1",
                left_bbox_xyxy=(640.0, 240.0, 720.0, 520.0),
                right_bbox_xyxy=(608.0, 240.0, 688.0, 520.0),
                confidence=0.91,
            ),
            scaled,
            known_distance_m=0.8706375,
            tolerance_m=0.02,
        )

        raw = replace_depth_value(
            original,
            depth_m=1.23,
            position=[0.01, -0.02, 1.23],
            depth_source=DEPTH_SOURCE_RAW_STEREO,
            calibration_ref="headset-28-physical-raw-v1",
            frame_provenance=FRAME_PROVENANCE_RAW,
            is_ground_truth=False,
        )

        self.assertNotIn("validation", raw)

    def test_stereo_depth_source_maps_record_to_c1_without_schema_change(self):
        depth_source = StereoDepthSource(
            {
                "person-1": {
                    "depth_m": 1.25,
                    "depth_source": DEPTH_SOURCE_POV_STEREO,
                    "pose_quality": POSE_QUALITY_STEREO,
                }
            }
        )
        producer = TrackingRawProducer(
            HumanTracker(n_confirm=1),
            depth_source,
            coordinate_space="vst_left_camera",
        )
        detections = detections_from_records(
            [{"bbox": [0.4, 0.25, 0.2, 0.5], "confidence": 0.9}]
        )

        message = producer.produce_frame(detections, sequence=7, timestamp_ms=1000.0)

        self.assertEqual(validate_message(message), [])
        det = message["detections"][0]
        self.assertEqual(det["pose_quality"], POSE_QUALITY_STEREO)
        self.assertEqual(det["source_frame"]["depth_source"], DEPTH_SOURCE_POV_STEREO)
        self.assertNotIn("depth_m", det)


if __name__ == "__main__":
    unittest.main()
