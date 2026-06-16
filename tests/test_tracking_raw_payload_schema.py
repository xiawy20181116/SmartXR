import json
from pathlib import Path
import unittest

from smartxr.tracking_raw_schema import validate_message
from smartxr.tracking_raw_fakes import (
    TrackingRawConsumer,
    build_fake_tracking_raw_message,
)


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "godot-android" / "fixtures" / "tracking_raw_sample.json"
OBB_SAMPLE = ROOT / "godot-android" / "fixtures" / "tracking_raw_obb_sample.json"
CONTRACT = ROOT / "docs" / "tracking_raw_payload_contract.md"


class TrackingRawPayloadSchemaTests(unittest.TestCase):
    def test_fake_producer_output_matches_canonical_schema(self):
        message = build_fake_tracking_raw_message(elapsed_s=0.25, sequence=3, timestamp_ms=1000.0)
        self.assertEqual(validate_message(message), [])

    def test_both_fixture_representations_match_schema(self):
        for path in [SAMPLE, OBB_SAMPLE]:
            message = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                self.assertEqual(validate_message(message), [])

    def test_empty_detection_list_is_a_valid_state(self):
        message = build_fake_tracking_raw_message(elapsed_s=0.0, sequence=0, timestamp_ms=1.0)
        message["detections"] = []
        self.assertEqual(validate_message(message), [])

    def test_rejects_raw_2d_pixel_and_depth_fields(self):
        message = build_fake_tracking_raw_message(elapsed_s=0.0, sequence=0, timestamp_ms=1.0)
        message["detections"][0]["bbox"] = {"cx": 436, "cy": 326, "w": 160, "h": 220}
        message["detections"][0]["depth_m"] = 1.8
        message["image"] = {"w": 880, "h": 660}
        errors = validate_message(message)
        self.assertIn("raw source field not allowed at $.detections[0].bbox", errors)
        self.assertIn("raw source field not allowed at $.detections[0].depth_m", errors)
        self.assertIn("raw source field not allowed at $.image", errors)

    def test_rejects_bad_state_pose_quality_and_bbox(self):
        message = build_fake_tracking_raw_message(elapsed_s=0.0, sequence=0, timestamp_ms=1.0)
        message["detections"][0]["state"] = "tracked"  # a C2 state, not a C1 lifecycle state
        message["detections"][0]["pose_quality"] = "guess"
        errors = validate_message(message)
        self.assertTrue(any("state must be one of" in e for e in errors))
        self.assertTrue(any("pose_quality must be one of" in e for e in errors))

    def test_rejects_bbox_with_both_representations(self):
        message = build_fake_tracking_raw_message(elapsed_s=0.0, sequence=0, timestamp_ms=1.0)
        message["detections"][0]["bbox_3d"]["center"] = [0, 0, 0]
        errors = validate_message(message)
        self.assertTrue(any("exactly one form" in e for e in errors))

    def test_fake_producer_to_fake_consumer_round_trip(self):
        consumer = TrackingRawConsumer()
        for sequence in range(5):
            message = build_fake_tracking_raw_message(
                elapsed_s=sequence * 0.1, sequence=sequence, timestamp_ms=1000.0 + sequence * 40
            )
            # serialize/deserialize so the consumer only ever sees wire JSON
            wire = json.loads(json.dumps(message))
            self.assertTrue(consumer.consume(wire))
        self.assertEqual(consumer.frames_accepted, 5)
        self.assertEqual(consumer.frames_rejected, 0)
        # id stability: a confirmed track keeps its id across the sequence
        self.assertEqual(consumer.seen_ids, {"person-7"})

    def test_consumer_rejects_malformed_payload(self):
        consumer = TrackingRawConsumer()
        self.assertFalse(consumer.consume({"type": "tracking_raw"}))
        self.assertEqual(consumer.frames_rejected, 1)
        self.assertEqual(consumer.frames_accepted, 0)

    def test_contract_documents_c1_boundary(self):
        source = CONTRACT.read_text(encoding="utf-8")
        self.assertIn("tracking_raw", source)
        self.assertIn("schema_version", source)
        self.assertIn("pose_quality", source)


if __name__ == "__main__":
    unittest.main()
