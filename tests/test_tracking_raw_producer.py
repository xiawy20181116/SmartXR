"""L2 replay tests for the C1 (tracking_raw) producer (YAN-108).

Replays a window of REAL recorded VST detections
(``tracking_raw_replay_detections.jsonl``, dumped from the fixed_replay capture
package by ``tools/verify_yolov8n_on_capture.py``) through the real producer and
the contract-only fake consumer, the publisher->consumer leg of the L0/L1/L2
ladder. Also pins the producer's per-detection contract behaviour and the
pluggable-depth axis. Pure-python: no ncnn/numpy, no device.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from smartxr.detection_backend import detections_from_records
from smartxr.tracker import (
    STATE_CONFIRMED,
    STATE_DELETED,
    STATE_LOST,
    STATE_TENTATIVE,
    HumanTracker,
)
from smartxr.tracking_raw_fakes import TrackingRawConsumer
from smartxr.tracking_raw_producer import (
    ConstantDepthSource,
    TrackingRawProducer,
)
from smartxr.tracking_raw_schema import validate_message

import sys

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "godot-android" / "fixtures"
DETECTIONS_JSONL = FIXTURES / "tracking_raw_replay_detections.jsonl"
C1_GOLDEN_JSONL = FIXTURES / "tracking_raw_replay_c1.jsonl"

# tools/ holds the dependency-free fixture builder (pinned producer recipe).
sys.path.insert(0, str(ROOT / "tools"))
from build_tracking_raw_replay_fixture import build_messages, read_detection_frames  # noqa: E402


def _read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _almost_equal(a, b, tol=1e-6) -> bool:
    """Structural equality with a numeric tolerance (libm differs across OS)."""
    if isinstance(a, dict):
        if not isinstance(b, dict) or a.keys() != b.keys():
            return False
        return all(_almost_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list):
        if not isinstance(b, list) or len(a) != len(b):
            return False
        return all(_almost_equal(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    return a == b


class FixturePresenceTests(unittest.TestCase):
    def test_fixtures_exist(self):
        self.assertTrue(DETECTIONS_JSONL.exists(), DETECTIONS_JSONL)
        self.assertTrue(C1_GOLDEN_JSONL.exists(), C1_GOLDEN_JSONL)


class L2ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detection_frames = read_detection_frames(DETECTIONS_JSONL)
        cls.messages = build_messages(cls.detection_frames)
        cls.golden = _read_jsonl(C1_GOLDEN_JSONL)

    def test_every_message_is_schema_valid(self):
        for i, msg in enumerate(self.messages):
            errors = validate_message(msg)
            self.assertEqual(errors, [], f"frame {i}: {errors}")

    def test_consumer_accepts_every_message(self):
        consumer = TrackingRawConsumer()
        for msg in self.messages:
            self.assertTrue(consumer.consume(msg))
        self.assertEqual(consumer.frames_rejected, 0)
        self.assertEqual(consumer.frames_accepted, len(self.messages))

    def test_reproduces_committed_golden_within_tolerance(self):
        # The committed C1 fixture is the producer drift gate: re-running the
        # pinned pipeline must reproduce it (tolerant on transcendental floats).
        self.assertEqual(len(self.messages), len(self.golden))
        for i, (got, want) in enumerate(zip(self.messages, self.golden)):
            self.assertTrue(_almost_equal(got, want), f"frame {i} diverged from golden")

    def test_replay_uses_real_capture_window(self):
        # Sanity: detections came from the recorded capture, not a synthetic stub.
        self.assertGreaterEqual(len(self.detection_frames), 100)
        self.assertTrue(any(f["detections"] for f in self.detection_frames))
        self.assertTrue(any(not f["detections"] for f in self.detection_frames))

    def test_empty_frames_are_valid_no_people_states(self):
        empty = [m for m in self.messages if not m["detections"]]
        self.assertTrue(empty)
        for msg in empty:
            self.assertEqual(validate_message(msg), [])

    def test_full_lifecycle_is_exercised_on_real_data(self):
        states = {d["state"] for m in self.messages for d in m["detections"]}
        self.assertEqual(
            states,
            {STATE_TENTATIVE, STATE_CONFIRMED, STATE_LOST, STATE_DELETED},
            f"expected all four lifecycle states, saw {sorted(states)}",
        )

    def test_ids_are_stable_not_churning(self):
        # An id-switch sanity bound: distinct ids must be far fewer than the
        # number of detection-bearing frames (no per-frame id reassignment).
        ids = {d["id"] for m in self.messages for d in m["detections"]}
        frames_with_dets = sum(1 for m in self.messages if m["detections"])
        self.assertLessEqual(len(ids), frames_with_dets // 4)
        # A confirmed track holds one id across consecutive confirmed frames.
        runs: dict[str, int] = {}
        for m in self.messages:
            for d in m["detections"]:
                if d["state"] == STATE_CONFIRMED:
                    runs[d["id"]] = runs.get(d["id"], 0) + 1
        self.assertTrue(any(count >= 5 for count in runs.values()))

    def test_lost_track_timestamp_lags_frame_clock(self):
        # For at least one lost detection, its observation time predates the
        # frame clock (the contract's stale-depth/held-pose property).
        found = False
        for m in self.messages:
            for d in m["detections"]:
                if d["state"] == STATE_LOST and d["timestamp_ms"] < m["timestamp_ms"]:
                    found = True
        self.assertTrue(found)


class ProducerContractTests(unittest.TestCase):
    def test_empty_detections_yields_valid_empty_message(self):
        producer = TrackingRawProducer(HumanTracker())
        msg = producer.produce_frame([], sequence=0, timestamp_ms=10.0)
        self.assertEqual(msg["detections"], [])
        self.assertEqual(validate_message(msg), [])
        self.assertEqual(msg["type"], "tracking_raw")
        self.assertEqual(msg["schema_version"], 1)

    def test_pluggable_depth_changes_value_not_shape(self):
        recs = [{"bbox": [0.4, 0.3, 0.2, 0.5], "confidence": 0.9}]
        near = TrackingRawProducer(HumanTracker(n_confirm=1), ConstantDepthSource(1.0))
        far = TrackingRawProducer(HumanTracker(n_confirm=1), ConstantDepthSource(3.0))
        m_near = near.produce_frame(detections_from_records(recs), 0, 0.0)
        m_far = far.produce_frame(detections_from_records(recs), 0, 0.0)
        self.assertEqual(validate_message(m_near), [])
        self.assertEqual(validate_message(m_far), [])
        z_near = m_near["detections"][0]["bbox_3d"]["vertices"][0][2]
        z_far = m_far["detections"][0]["bbox_3d"]["vertices"][0][2]
        self.assertGreater(z_far, z_near)  # farther depth -> larger forward z
        # both keep the identical contract shape / tags
        self.assertEqual(
            m_near["detections"][0]["source_frame"],
            m_far["detections"][0]["source_frame"],
        )

    def test_alternate_depth_source_only_swaps_tags(self):
        class MonoMetricDepth:
            def depth_for(self, track):
                return (2.2, "monodepth", "mono_metric")

        recs = [{"bbox": [0.4, 0.3, 0.2, 0.5], "confidence": 0.9}]
        producer = TrackingRawProducer(HumanTracker(n_confirm=1), MonoMetricDepth())
        msg = producer.produce_frame(detections_from_records(recs), 0, 0.0)
        self.assertEqual(validate_message(msg), [])  # shape unchanged
        det = msg["detections"][0]
        self.assertEqual(det["pose_quality"], "mono_metric")
        self.assertEqual(det["source_frame"]["depth_source"], "monodepth")

    def test_invalid_emission_raises_when_validation_on(self):
        class BadDepth:
            def depth_for(self, track):
                return (1.0, "", "fixed_depth")  # empty depth_source -> invalid

        recs = [{"bbox": [0.4, 0.3, 0.2, 0.5], "confidence": 0.9}]
        producer = TrackingRawProducer(HumanTracker(n_confirm=1), BadDepth())
        with self.assertRaises(ValueError):
            producer.produce_frame(detections_from_records(recs), 0, 0.0)


if __name__ == "__main__":
    unittest.main()
