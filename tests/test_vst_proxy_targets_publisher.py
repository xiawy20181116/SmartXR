import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "tools" / "vst_proxy_targets_publisher.py"
VALIDATOR = ROOT / "tools" / "validate_proxy_targets_payload_schema.py"
SOURCE_SAMPLE = ROOT / "godot-android" / "fixtures" / "vst_source_sample.json"
STAGED_RUNNER = ROOT / "tools" / "run_godot_script_only_staged_probe.ps1"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class VSTProxyTargetsPublisherTests(unittest.TestCase):
    def test_normalizes_raw_vst_bbox_sample_to_canonical_proxy_targets(self):
        publisher = load_module(PUBLISHER, "vst_proxy_targets_publisher")
        validator = load_module(VALIDATOR, "validate_proxy_targets_payload_schema")
        source = json.loads(SOURCE_SAMPLE.read_text(encoding="utf-8"))

        message = publisher.normalize_source_payload(source, sequence=12)

        self.assertEqual(message["type"], "proxy_targets")
        self.assertEqual(message["sequence"], 12)
        self.assertEqual(message["targets"][0]["source"], "vst")
        self.assertEqual(message["cards"][0]["target_id"], message["targets"][0]["target_id"])
        self.assertEqual(validator.validate_message(message), [])
        serialized = json.dumps(message)
        self.assertNotIn("bbox", serialized)
        self.assertNotIn("detection", serialized)
        self.assertEqual(message["targets"][0]["source_coordinate"]["coordinate_space"], "vst_camera_right")
        self.assertEqual(message["targets"][0]["source_coordinate"]["publisher_convention"], "godot_head")
        self.assertEqual(message["targets"][0]["source_coordinate"]["anchor"], "target_center")
        self.assertEqual(message["targets"][0]["coordinate_space"], "head")
        self.assertEqual(message["targets"][0]["transform_space"], "head")

    def test_vst_bbox_projection_uses_fov_and_head_coordinate_convention(self):
        publisher = load_module(PUBLISHER, "vst_proxy_targets_publisher")

        message = publisher.normalize_source_payload(
            {
                "source": "vst",
                "timestamp_ms": 1780911169157,
                "image": {
                    "w": 872,
                    "h": 652,
                    "camera": {"horizontal_fov_deg": 70.0, "vertical_fov_deg": 43.0},
                },
                "detections": [
                    {
                        "id": "person-right-low",
                        "confidence": 0.9,
                        "depth_m": 2.0,
                        "bbox": {"cx": 872.0, "cy": 652.0, "w": 100.0, "h": 200.0},
                    }
                ],
            }
        )

        position = message["targets"][0]["transform"]["position"]
        self.assertGreater(position[0], 0.0)
        self.assertLess(position[1], 0.0)
        self.assertLess(position[2], 0.0)
        self.assertAlmostEqual(sum(component * component for component in position) ** 0.5, 2.0, places=6)
        self.assertEqual(message["targets"][0]["source_coordinate"]["source_frame"]["horizontal_fov_deg"], 70.0)

    def test_vst_bbox_projection_uses_calibrated_principal_point(self):
        publisher = load_module(PUBLISHER, "vst_proxy_targets_publisher")

        message = publisher.normalize_source_payload(
            {
                "source": "vst",
                "timestamp_ms": 1780911169157,
                "image": {
                    "w": 880,
                    "h": 660,
                    "camera": {
                        "principal_point_x": 430.0,
                        "principal_point_y": 340.0,
                    },
                },
                "detections": [
                    {
                        "id": "person-calibrated-center",
                        "confidence": 0.9,
                        "depth_m": 2.0,
                        "bbox": {"cx": 430.0, "cy": 340.0, "w": 100.0, "h": 200.0},
                    }
                ],
            }
        )

        target = message["targets"][0]
        position = target["transform"]["position"]
        source_frame = target["source_coordinate"]["source_frame"]
        self.assertAlmostEqual(position[0], 0.0, places=6)
        self.assertAlmostEqual(position[1], 0.0, places=6)
        self.assertAlmostEqual(position[2], -2.0, places=6)
        self.assertEqual(source_frame["principal_point_x"], 430.0)
        self.assertEqual(source_frame["principal_point_y"], 340.0)

    def test_vst_bbox_projection_prefers_calibrated_focal_lengths(self):
        publisher = load_module(PUBLISHER, "vst_proxy_targets_publisher")

        message = publisher.normalize_source_payload(
            {
                "source": "vst",
                "timestamp_ms": 1780911169157,
                "image": {
                    "w": 640,
                    "h": 480,
                    "camera": {
                        "fx": 241.14032906751385,
                        "fy": 241.60074879502008,
                        "cx": 318.6850230882512,
                        "cy": 240.9308751924166,
                    },
                },
                "detections": [
                    {
                        "id": "person-rb-principal",
                        "confidence": 0.9,
                        "depth_m": 2.0,
                        "bbox": {"cx": 318.6850230882512, "cy": 240.9308751924166, "w": 100.0, "h": 200.0},
                    }
                ],
            }
        )

        target = message["targets"][0]
        position = target["transform"]["position"]
        source_frame = target["source_coordinate"]["source_frame"]
        self.assertAlmostEqual(position[0], 0.0, places=6)
        self.assertAlmostEqual(position[1], 0.0, places=6)
        self.assertAlmostEqual(position[2], -2.0, places=6)
        self.assertEqual(source_frame["focal_length_x"], 241.14032906751385)
        self.assertEqual(source_frame["focal_length_y"], 241.60074879502008)
        self.assertEqual(source_frame["principal_point_x"], 318.6850230882512)
        self.assertEqual(source_frame["principal_point_y"], 240.9308751924166)

    def test_vst_bbox_without_depth_uses_five_meter_default(self):
        publisher = load_module(PUBLISHER, "vst_proxy_targets_publisher")

        message = publisher.normalize_source_payload(
            {
                "source": "vst",
                "timestamp_ms": 1780911169157,
                "image": {"w": 880, "h": 660},
                "detections": [
                    {
                        "id": "person-center",
                        "confidence": 0.9,
                        "bbox": {"cx": 440.0, "cy": 330.0, "w": 100.0, "h": 200.0},
                    }
                ],
            }
        )

        target = message["targets"][0]
        position = target["transform"]["position"]
        self.assertAlmostEqual(position[0], 0.0)
        self.assertAlmostEqual(position[1], 0.0)
        self.assertAlmostEqual(position[2], -5.0)
        self.assertEqual(target["source_coordinate"]["depth_source"], "default_depth")
        self.assertEqual(target["source_coordinate"]["source_frame"]["anchor_depth"], 5.0)

    def test_vst_bbox_passes_depth_source_and_confidence_to_proxy_target(self):
        publisher = load_module(PUBLISHER, "vst_proxy_targets_publisher")
        validator = load_module(VALIDATOR, "validate_proxy_targets_payload_schema")

        message = publisher.normalize_source_payload(
            {
                "source": "vst",
                "timestamp_ms": 1780911169157,
                "image": {"w": 880, "h": 660},
                "detections": [
                    {
                        "id": "person-fallback",
                        "confidence": 0.9,
                        "depth_m": 1.23,
                        "depth_source": "bbox_top_center_fallback",
                        "depth_confidence": "low",
                        "bbox": {"cx": 440.0, "cy": 330.0, "w": 100.0, "h": 200.0},
                    }
                ],
            }
        )

        target = message["targets"][0]
        self.assertEqual(target["depth_source"], "bbox_top_center_fallback")
        self.assertEqual(target["depth_confidence"], "low")
        self.assertEqual(target["source_coordinate"]["depth_source"], "bbox_top_center_fallback")
        self.assertEqual(validator.validate_message(message), [])

    def test_vst_bbox_depth_confidence_none_is_not_a_publishable_target(self):
        publisher = load_module(PUBLISHER, "vst_proxy_targets_publisher")

        message = publisher.normalize_source_payload(
            {
                "source": "vst",
                "timestamp_ms": 1780911169157,
                "image": {"w": 880, "h": 660},
                "detections": [
                    {
                        "id": "person-none",
                        "confidence": 0.9,
                        "depth_m": 1.23,
                        "depth_source": "bbox_top_center_fallback",
                        "depth_confidence": "none",
                        "bbox": {"cx": 440.0, "cy": 330.0, "w": 100.0, "h": 200.0},
                    }
                ],
            }
        )

        self.assertEqual(message["targets"], [])
        self.assertEqual(message["cards"], [])

    def test_vst_bbox_projection_can_apply_right_eye_to_head_matrix(self):
        publisher = load_module(PUBLISHER, "vst_proxy_targets_publisher")

        message = publisher.normalize_source_payload(
            {
                "source": "vst",
                "timestamp_ms": 1780911169157,
                "image": {
                    "w": 872,
                    "h": 652,
                    "camera": {
                        "right_eye_to_head_matrix": [
                            1.0, 0.0, 0.0, 0.03,
                            0.0, -1.0, 0.0, 0.02,
                            0.0, 0.0, -1.0, 0.0,
                            0.0, 0.0, 0.0, 1.0,
                        ]
                    },
                },
                "detections": [
                    {
                        "id": "person-center",
                        "confidence": 0.9,
                        "depth_m": 1.5,
                        "bbox": {"cx": 436.0, "cy": 326.0, "w": 100.0, "h": 200.0},
                    }
                ],
            }
        )

        position = message["targets"][0]["transform"]["position"]
        self.assertAlmostEqual(position[0], 0.03)
        self.assertAlmostEqual(position[1], 0.02)
        self.assertAlmostEqual(position[2], -1.5)
        self.assertTrue(message["targets"][0]["source_coordinate"]["uses_right_eye_to_head"])

    def test_print_once_outputs_schema_valid_payload(self):
        completed = subprocess.run(
            [sys.executable, str(PUBLISHER), "--input", str(SOURCE_SAMPLE), "--print-once"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        validator = load_module(VALIDATOR, "validate_proxy_targets_payload_schema")
        message = json.loads(completed.stdout)

        self.assertEqual(validator.validate_message(message), [])

    def test_tracker_new_state_is_normalized_to_tracked(self):
        publisher = load_module(PUBLISHER, "vst_proxy_targets_publisher")
        validator = load_module(VALIDATOR, "validate_proxy_targets_payload_schema")

        message = publisher.normalize_source_payload(
            {
                "source": "vst",
                "sequence": 743,
                "timestamp_ms": 1780911169157,
                "image": {"w": 880, "h": 660},
                "detections": [
                    {
                        "id": "person-2",
                        "state": "new",
                        "confidence": 0.568,
                        "bbox": {"cx": 293.0, "cy": 383.5, "w": 128.0, "h": 173.0},
                    }
                ],
            }
        )

        self.assertEqual(message["targets"][0]["state"], "tracked")
        self.assertEqual(validator.validate_message(message), [])

    def test_loads_jsonl_capture_session_as_schema_valid_proxy_targets_frames(self):
        publisher = load_module(PUBLISHER, "vst_proxy_targets_publisher")
        validator = load_module(VALIDATOR, "validate_proxy_targets_payload_schema")
        jsonl_path = ROOT / "godot-android" / "fixtures" / "vst_target_sample_session_input.jsonl"

        messages = publisher.load_source_messages(jsonl_path, card_id="ReplayCard")

        self.assertEqual([message["sequence"] for message in messages], [2])
        self.assertEqual(messages[0]["targets"][0]["target_id"], "vst-person-7")
        self.assertEqual(messages[0]["targets"][0]["state"], "tracked")
        self.assertEqual(messages[0]["cards"][0]["card_id"], "ReplayCard")
        self.assertEqual(validator.validate_message(messages[0]), [])

    def test_replay_sequence_cycles_through_jsonl_frames_with_live_sequence_numbers(self):
        publisher = load_module(PUBLISHER, "vst_proxy_targets_publisher")
        frames = [
            {"type": "proxy_targets", "schema_version": 1, "sequence": 10, "targets": [{"target_id": "a"}], "cards": []},
            {"type": "proxy_targets", "schema_version": 1, "sequence": 11, "targets": [{"target_id": "b"}], "cards": []},
        ]
        replayed = [publisher.replay_message_at(frames, index) for index in range(4)]

        self.assertEqual([message["sequence"] for message in replayed], [0, 1, 2, 3])
        self.assertEqual([message["targets"][0]["target_id"] for message in replayed], ["a", "b", "a", "b"])

    def test_staged_runner_supports_swapping_in_vst_publisher(self):
        source = STAGED_RUNNER.read_text(encoding="utf-8")

        self.assertIn("[string]$PublisherScript", source)
        self.assertIn("[string]$PublisherInput", source)
        self.assertIn("--input", source)
        self.assertIn("Publisher script:", source)


if __name__ == "__main__":
    unittest.main()
