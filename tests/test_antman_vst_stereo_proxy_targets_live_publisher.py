from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
import json
import unittest
import uuid
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LIVE_PUBLISHER = ROOT / "tools" / "antman_vst_stereo_proxy_targets_live_publisher.py"
RUNNER = ROOT / "tools" / "run_antman_vst_stereo_proxy_targets_live.ps1"
VALIDATOR = ROOT / "tools" / "validate_proxy_targets_payload_schema.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeFrame:
    shape = (660, 880, 3)

    def __init__(self, *, timestamp_us=None, timestamp_ms=None, exposure_timestamp=None):
        if timestamp_us is not None:
            self.timestamp_us = timestamp_us
        if timestamp_ms is not None:
            self.timestamp_ms = timestamp_ms
        if exposure_timestamp is not None:
            self.exposure_timestamp = exposure_timestamp


class FakePerson:
    def __init__(self, track_id=2, bbox=(640, 240, 720, 520), confidence=0.91, tracking_status="tracked"):
        self.track_id = track_id
        self.bbox = bbox
        self.confidence = confidence
        self.tracking_status = tracking_status


class FakeTrackingResult:
    def __init__(self, people):
        self.people = people
        self.frame_index = 7
        self.frame_latency_ms = 12.5


class AntmanVstStereoProxyTargetsLivePublisherTests(unittest.TestCase):
    def test_broadcast_hub_sends_same_message_to_multiple_clients(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeConn:
            def __init__(self):
                self.frames = []

            def sendall(self, frame):
                self.frames.append(frame)

        first = FakeConn()
        second = FakeConn()
        hub = publisher.BroadcastHub()
        hub.add_client(first, ("127.0.0.1", 11111))
        hub.add_client(second, ("127.0.0.1", 11112))

        hub.broadcast({"type": "proxy_targets", "sequence": 7, "targets": [], "cards": []})

        self.assertEqual(len(first.frames), 1)
        self.assertEqual(first.frames, second.frames)

    def test_broadcast_hub_reports_client_labels_and_disconnects(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeConn:
            def __init__(self, fail=False):
                self.fail = fail

            def sendall(self, _frame):
                if self.fail:
                    raise ConnectionResetError("reset by peer")

        godot = FakeConn()
        monitor = FakeConn(fail=True)
        hub = publisher.BroadcastHub()
        godot_id = hub.add_client(godot, ("127.0.0.1", 11111), label="godot")
        monitor_id = hub.add_client(monitor, ("127.0.0.1", 11112), label="monitor")

        delivered = hub.broadcast({"type": "proxy_targets", "sequence": 7, "targets": [], "cards": []})
        summary = hub.status_summary()

        self.assertEqual(delivered, 1)
        self.assertIn(f"{godot_id}=godot@127.0.0.1:11111", summary["active_clients"])
        self.assertEqual(summary["active_client_count"], 1)
        self.assertEqual(summary["last_disconnect"]["client_id"], monitor_id)
        self.assertEqual(summary["last_disconnect"]["label"], "monitor")
        self.assertEqual(summary["last_disconnect"]["reason"], "connection_reset")

    def test_depth_trace_event_includes_publisher_client_status(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        event = publisher.build_depth_trace_event(
            message=None,
            diagnostics={
                "reason": "no_pair",
                "clients": {
                    "active_client_count": 1,
                    "active_clients": ["client-2=monitor@127.0.0.1:12345"],
                    "last_disconnect": {
                        "client_id": "client-1",
                        "label": "godot",
                        "address": "127.0.0.1:12344",
                        "reason": "client_closed",
                    },
                },
            },
            sequence=7,
        )

        self.assertEqual(event["clients"]["active_client_count"], 1)
        self.assertEqual(event["clients"]["last_disconnect"]["label"], "godot")

    def test_builds_schema_valid_message_from_stereo_bbox_pair(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")
        validator = load_module(VALIDATOR, "validate_proxy_targets_payload_schema")

        stereo_record = {
            "source": "vst_stereo_bbox",
            "frame_id": 10,
            "pair_id": "pair-000010",
            "person_id": "person-2-4",
            "timestamp_ms": 1780911169157,
            "left_bbox_xyxy": [640, 240, 720, 520],
            "right_bbox_xyxy": [608, 240, 688, 520],
            "confidence": 0.91,
        }

        message = publisher.build_proxy_targets_message_from_stereo_bbox_record(
            stereo_record,
            sequence=3,
            card_id="StereoCard",
            recorded_width=880,
            recorded_height=660,
        )

        self.assertIsNotNone(message)
        self.assertEqual(message["sequence"], 3)
        self.assertEqual(message["targets"][0]["target_id"], "vst_stereo-person-2-4")
        self.assertEqual(message["targets"][0]["depth_source"], "pov_stereo_triangulation")
        self.assertEqual(message["targets"][0]["depth_confidence"], "high")
        self.assertEqual(message["targets"][0]["source_coordinate"]["depth_source"], "pov_stereo_triangulation")
        self.assertEqual(message["targets"][0]["source_coordinate"]["depth_confidence"], "high")
        self.assertEqual(message["targets"][0]["stereo"]["pair_id"], "pair-000010")
        self.assertEqual(message["cards"][0]["card_id"], "StereoCard")
        self.assertEqual(validator.validate_message(message), [])

    def test_builds_message_with_configured_card_offset_rule(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")
        offset_rule = {
            "mode": "depth_scaled_right_half_width",
            "offset_space": "world",
            "depth_scale": 1.15,
            "depth_offset_m": 0.2,
            "right_width_fraction": -0.5,
            "up_m": 0.1,
            "fallback": "hold_last_pose",
        }

        message = publisher.build_proxy_targets_message_from_stereo_bbox_record(
            {
                "source": "vst_stereo_bbox",
                "frame_id": 10,
                "pair_id": "pair-000010",
                "person_id": "person-2-4",
                "timestamp_ms": 1780911169157,
                "left_bbox_xyxy": [640, 240, 720, 520],
                "right_bbox_xyxy": [608, 240, 688, 520],
                "confidence": 0.91,
            },
            sequence=3,
            card_id="StereoCard",
            recorded_width=880,
            recorded_height=660,
            offset_rule=offset_rule,
        )

        self.assertIsNotNone(message)
        self.assertEqual(message["cards"][0]["offset_rule"], offset_rule)

    def test_depth_override_fixed_updates_target_depth_and_trace_metadata(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")
        record = {
            "source": "vst_stereo_bbox",
            "frame_id": 10,
            "pair_id": "pair-000010",
            "person_id": "person-2-4",
            "timestamp_ms": 1780911169157,
            "left_bbox_xyxy": [640, 240, 720, 520],
            "right_bbox_xyxy": [608, 240, 688, 520],
            "confidence": 0.91,
        }
        baseline = publisher.build_proxy_targets_message_from_stereo_bbox_record(
            record,
            sequence=3,
            recorded_width=880,
            recorded_height=660,
        )
        raw_depth_m = baseline["targets"][0]["source_coordinate"]["source_frame"]["anchor_depth"]

        message = publisher.build_proxy_targets_message_from_stereo_bbox_record(
            record,
            sequence=3,
            recorded_width=880,
            recorded_height=660,
            depth_override=publisher.DepthOverrideConfig(mode="fixed", fixed_m=1.7),
        )

        self.assertIsNotNone(message)
        target = message["targets"][0]
        self.assertEqual(target["depth_source"], "depth_override_fixed")
        self.assertEqual(target["source_coordinate"]["depth_source"], "depth_override_fixed")
        self.assertAlmostEqual(target["source_coordinate"]["source_frame"]["anchor_depth"], 1.7)
        self.assertAlmostEqual(target["stereo"]["depth_m_raw"], raw_depth_m)
        self.assertAlmostEqual(target["stereo"]["depth_m"], 1.7)
        self.assertEqual(target["depth_override"]["mode"], "fixed")
        self.assertEqual(target["depth_override"]["raw_depth_m"], target["stereo"]["depth_m_raw"])
        self.assertEqual(target["depth_override"]["applied_depth_m"], 1.7)

        event = publisher.build_depth_trace_event(
            message=message,
            diagnostics={"reason": "target_ready", "last_pair_frame_id": 10},
        )
        self.assertEqual(event["depth_source"], "depth_override_fixed")
        self.assertAlmostEqual(event["depth_m"], 1.7)
        self.assertEqual(event["depth_override"]["mode"], "fixed")
        self.assertAlmostEqual(event["depth_raw_m"], target["stereo"]["depth_m_raw"])

    def test_depth_override_scale_offset_and_noise_are_deterministic(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")
        raw_depth = 0.83671875

        scaled = publisher.apply_depth_override(
            raw_depth,
            publisher.DepthOverrideConfig(mode="scale_offset", scale=2.0, offset_m=0.1),
            sequence=3,
        )
        noisy_a = publisher.apply_depth_override(
            raw_depth,
            publisher.DepthOverrideConfig(mode="noise", noise_std_m=0.05, seed=42),
            sequence=3,
        )
        noisy_b = publisher.apply_depth_override(
            raw_depth,
            publisher.DepthOverrideConfig(mode="noise", noise_std_m=0.05, seed=42),
            sequence=3,
        )

        self.assertEqual(scaled["mode"], "scale_offset")
        self.assertAlmostEqual(scaled["applied_depth_m"], raw_depth * 2.0 + 0.1)
        self.assertEqual(noisy_a, noisy_b)
        self.assertEqual(noisy_a["mode"], "noise")
        self.assertEqual(noisy_a["seed"], 42)
        self.assertNotAlmostEqual(noisy_a["applied_depth_m"], raw_depth)

    def test_parse_args_exposes_depth_override_controls(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        args = publisher.parse_args(
            [
                "--depth-override-mode",
                "scale_offset",
                "--depth-override-fixed-m",
                "1.7",
                "--depth-override-scale",
                "1.25",
                "--depth-override-offset-m",
                "0.2",
                "--depth-override-noise-std-m",
                "0.03",
                "--depth-override-seed",
                "123",
            ]
        )

        config = publisher.depth_override_config_from_args(args)
        self.assertEqual(args.depth_override_mode, "scale_offset")
        self.assertEqual(config.normalized_mode(), "scale_offset")
        self.assertEqual(config.fixed_m, 1.7)
        self.assertEqual(config.scale, 1.25)
        self.assertEqual(config.offset_m, 0.2)
        self.assertEqual(config.noise_std_m, 0.03)
        self.assertEqual(config.seed, 123)

    def test_builds_message_from_keypoint_anchor_record(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        stereo_record = {
            "source": "vst_stereo_keypoint",
            "frame_id": 12,
            "pair_id": "pair-000012",
            "person_id": "person-2-4",
            "timestamp_ms": 1780911169200,
            "left_bbox_xyxy": [640, 240, 720, 520],
            "right_bbox_xyxy": [608, 240, 688, 520],
            "confidence": 0.91,
            "selected_anchor": {
                "kind": "shoulder_midpoint",
                "keypoints": ["left_shoulder", "right_shoulder"],
                "left_kind": "shoulder_midpoint",
                "right_kind": "shoulder_midpoint",
                "left_keypoints": ["left_shoulder", "right_shoulder"],
                "right_keypoints": ["left_shoulder", "right_shoulder"],
                "left_px": [670.0, 300.0],
                "right_px": [638.0, 300.0],
                "left_score": 0.87,
                "right_score": 0.84,
                "score": 0.84,
            },
            "keypoints": {
                "left": {
                    "left_shoulder": {"xy": [650.0, 300.0], "score": 0.90},
                    "right_shoulder": {"xy": [690.0, 300.0], "score": 0.87},
                },
                "right": {
                    "left_shoulder": {"xy": [618.0, 300.0], "score": 0.88},
                    "right_shoulder": {"xy": [658.0, 300.0], "score": 0.84},
                },
            },
            "pose_association": {
                "left": {"status": "matched", "selected_person_index": 0},
                "right": {"status": "matched", "selected_person_index": 0},
            },
        }

        message = publisher.build_proxy_targets_message_from_stereo_bbox_record(
            stereo_record,
            sequence=5,
            card_id="StereoCard",
            recorded_width=880,
            recorded_height=660,
        )

        self.assertIsNotNone(message)
        target = message["targets"][0]
        self.assertEqual(target["depth_source"], "shoulder_midpoint")
        self.assertEqual(target["depth_confidence"], "high")
        self.assertEqual(target["stereo"]["anchor_kind"], "shoulder_midpoint")
        self.assertEqual(target["stereo"]["left_anchor_px"], [670.0, 300.0])
        self.assertEqual(target["stereo"]["right_anchor_px"], [638.0, 300.0])
        self.assertEqual(target["stereo"]["keypoint_anchor"]["score"], 0.84)
        self.assertEqual(target["stereo"]["pose_association"]["left"]["status"], "matched")

        event = publisher.build_depth_trace_event(
            message=message,
            diagnostics={"reason": "target_ready", "last_pair_frame_id": 12},
        )
        self.assertEqual(event["depth_source"], "shoulder_midpoint")
        self.assertEqual(event["stereo"]["anchor_kind"], "shoulder_midpoint")
        self.assertEqual(event["keypoint_anchor"]["kind"], "shoulder_midpoint")

    def test_keypoint_anchor_record_falls_back_to_bbox_when_anchor_is_mixed(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        stereo_record = {
            "source": "vst_stereo_keypoint",
            "frame_id": 13,
            "pair_id": "pair-000013",
            "person_id": "person-2-4",
            "timestamp_ms": 1780911169233,
            "left_bbox_xyxy": [640, 240, 720, 520],
            "right_bbox_xyxy": [608, 240, 688, 520],
            "confidence": 0.91,
            "selected_anchor": {
                "kind": "mixed",
                "left_kind": "shoulder_midpoint",
                "right_kind": "nose",
                "left_px": [670.0, 300.0],
                "right_px": [648.0, 250.0],
                "score": 0.75,
            },
        }

        message = publisher.build_proxy_targets_message_from_stereo_bbox_record(
            stereo_record,
            sequence=6,
            recorded_width=880,
            recorded_height=660,
        )

        self.assertIsNotNone(message)
        target = message["targets"][0]
        self.assertEqual(target["depth_source"], "bbox_top_center_fallback")
        self.assertEqual(target["depth_confidence"], "low")
        self.assertEqual(target["stereo"]["anchor_kind"], "bbox_top_center")
        self.assertEqual(target["stereo"]["left_anchor_px"], [680.0, 240.0])
        self.assertEqual(target["stereo"]["keypoint_anchor"]["fallback_reason"], "anchor_kind_mismatch")

    def test_depth_gate_marks_held_stereo_record_as_low_confidence(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        stereo_record = {
            "source": "vst_stereo_bbox",
            "frame_id": 11,
            "pair_id": "pair-000011",
            "person_id": "active-1",
            "timestamp_ms": 1780911169190,
            "left_bbox_xyxy": [640, 240, 720, 520],
            "right_bbox_xyxy": [608, 240, 688, 520],
            "confidence": 0.76,
            "selection": {
                "held_last_pose": True,
                "held_reason": "mono_eye_missing",
                "depth_update_allowed": False,
                "depth_gate_reason": "depth_jump",
                "last_good_depth": 1.23,
            },
        }

        message = publisher.build_proxy_targets_message_from_stereo_bbox_record(
            stereo_record,
            sequence=4,
            card_id="StereoCard",
            recorded_width=880,
            recorded_height=660,
        )

        self.assertIsNotNone(message)
        target = message["targets"][0]
        self.assertEqual(target["depth_source"], "held_last_good_depth")
        self.assertEqual(target["depth_confidence"], "low")
        self.assertEqual(target["source_coordinate"]["depth_source"], "held_last_good_depth")
        self.assertEqual(target["source_coordinate"]["depth_confidence"], "low")
        self.assertAlmostEqual(target["source_coordinate"]["source_frame"]["anchor_depth"], 1.23)
        self.assertEqual(target["stereo"]["depth_source"], "held_last_good_depth")
        self.assertFalse(target["stereo"]["depth_update_allowed"])

        event = publisher.build_depth_trace_event(
            message=message,
            diagnostics={"reason": "target_ready", "last_pair_frame_id": 11},
        )
        self.assertEqual(event["depth_source"], "held_last_good_depth")
        self.assertEqual(event["depth_confidence"], "low")
        self.assertAlmostEqual(event["depth_m"], 1.23)
        self.assertFalse(event["depth_update_allowed"])
        self.assertEqual(event["depth_gate_reason"], "depth_jump")

    def test_one_euro_position_filter_smooths_target_transform_and_keeps_raw_diagnostics(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        filter_state = publisher.OneEuroVector3Filter(min_cutoff=0.1, beta=0.0, d_cutoff=1.0)
        first = {
            "type": "proxy_targets",
            "schema_version": 1,
            "sequence": 1,
            "timestamp_ms": 1_000,
            "targets": [
                {
                    "target_id": "vst_stereo-active-1",
                    "source": "vst_stereo",
                    "coordinate_space": "head",
                    "transform_space": "head",
                    "state": "tracked",
                    "confidence": 0.9,
                    "depth_source": "pov_stereo_triangulation",
                    "depth_confidence": "high",
                    "timestamp_ms": 1_000.0,
                    "transform": {
                        "position": [0.0, 0.0, -1.0],
                        "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                        "scale": [1.0, 1.0, 1.0],
                    },
                    "source_coordinate": {"head_position_m": [0.0, 0.0, -1.0]},
                }
            ],
            "cards": [{"card_id": "CardAnchor", "target_id": "vst_stereo-active-1"}],
        }
        second = json.loads(json.dumps(first))
        second["sequence"] = 2
        second["timestamp_ms"] = 1_033
        second["targets"][0]["timestamp_ms"] = 1_033.0
        second["targets"][0]["transform"]["position"] = [0.2, 0.0, -1.0]
        second["targets"][0]["source_coordinate"]["head_position_m"] = [0.2, 0.0, -1.0]

        publisher.apply_position_one_euro_filter(first, filter_state)
        filtered = publisher.apply_position_one_euro_filter(second, filter_state)

        target = filtered["targets"][0]
        filtered_position = target["transform"]["position"]
        self.assertGreater(filtered_position[0], 0.0)
        self.assertLess(filtered_position[0], 0.2)
        self.assertEqual(target["position_filter"]["algorithm"], "one_euro")
        self.assertTrue(target["position_filter"]["enabled"])
        self.assertEqual(target["position_filter"]["raw_position_m"], [0.2, 0.0, -1.0])
        self.assertEqual(target["position_filter"]["filtered_position_m"], filtered_position)
        self.assertEqual(target["source_coordinate"]["head_position_m"], [0.2, 0.0, -1.0])
        self.assertEqual(target["source_coordinate"]["filtered_head_position_m"], filtered_position)

        event = publisher.build_depth_trace_event(
            message=filtered,
            diagnostics={"reason": "target_ready", "last_pair_frame_id": 33},
        )
        self.assertEqual(event["position_filter"]["algorithm"], "one_euro")
        self.assertEqual(event["raw_head_position_m"], [0.2, 0.0, -1.0])
        self.assertEqual(event["filtered_head_position_m"], filtered_position)

    def test_live_stereo_message_waits_for_matched_left_right_frame_ids(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self, frames):
                self.frames = list(frames)
                self.calls = 0

            def read_latest(self):
                self.calls += 1
                if not self.frames:
                    return True, -1, None
                return self.frames.pop(0)

            def get_stats(self):
                return {"calls": self.calls}

        class FakeTracker:
            def __init__(self, bbox):
                self.bbox = bbox

            def process_frame(self, frame):
                return FakeTrackingResult([FakePerson(bbox=self.bbox)])

        message, diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=FakeReader([(True, 41, FakeFrame()), (True, 42, FakeFrame())]),
            right_reader=FakeReader([(True, 42, FakeFrame())]),
            left_tracker=FakeTracker((640, 240, 720, 520)),
            right_tracker=FakeTracker((608, 240, 688, 520)),
            sequence=0,
            max_read_attempts=4,
            sleep_seconds=0,
        )

        self.assertIsNotNone(message)
        self.assertEqual(message["targets"][0]["depth_source"], "pov_stereo_triangulation")
        self.assertEqual(diagnostics["reason"], "target_ready")
        self.assertEqual(diagnostics["frames_seen_left"], 2)
        self.assertEqual(diagnostics["frames_seen_right"], 1)
        self.assertEqual(diagnostics["last_pair_frame_id"], 42)

    def test_live_stereo_message_attaches_keypoint_anchor_from_pose_estimators(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self, frame):
                self.frame = frame
                self.used = False

            def read_latest(self):
                if self.used:
                    return True, -1, None
                self.used = True
                return True, 42, self.frame

            def get_stats(self):
                return {}

        class FakeTracker:
            def __init__(self, bbox):
                self.bbox = bbox

            def process_frame(self, frame):
                return FakeTrackingResult([FakePerson(bbox=self.bbox)])

        class FakePoseEstimator:
            def __init__(self, left_shoulder, right_shoulder):
                self.left_shoulder = left_shoulder
                self.right_shoulder = right_shoulder
                self.calls = []

            def __call__(self, frame):
                self.calls.append(frame)
                points = [[0.0, 0.0] for _ in range(17)]
                scores = [0.0 for _ in range(17)]
                points[5] = list(self.left_shoulder)
                points[6] = list(self.right_shoulder)
                scores[5] = 0.91
                scores[6] = 0.86
                return [points], [scores]

        left_pose = FakePoseEstimator((650.0, 300.0), (690.0, 300.0))
        right_pose = FakePoseEstimator((618.0, 300.0), (658.0, 300.0))

        message, diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=FakeReader(FakeFrame(timestamp_us=1_000_000)),
            right_reader=FakeReader(FakeFrame(timestamp_us=1_000_100)),
            left_tracker=FakeTracker((640, 240, 720, 520)),
            right_tracker=FakeTracker((608, 240, 688, 520)),
            left_pose_estimator=left_pose,
            right_pose_estimator=right_pose,
            min_keypoint_score=0.5,
            sequence=0,
            max_read_attempts=1,
            sleep_seconds=0,
        )

        self.assertIsNotNone(message)
        target = message["targets"][0]
        self.assertEqual(target["depth_source"], "shoulder_midpoint")
        self.assertEqual(target["stereo"]["anchor_kind"], "shoulder_midpoint")
        self.assertEqual(target["stereo"]["left_anchor_px"], [670.0, 300.0])
        self.assertEqual(target["stereo"]["right_anchor_px"], [638.0, 300.0])
        self.assertEqual(diagnostics["keypoint_anchor"]["kind"], "shoulder_midpoint")
        self.assertEqual(diagnostics["pose_association"]["left"]["status"], "matched")
        self.assertEqual(len(left_pose.calls), 1)
        self.assertEqual(len(right_pose.calls), 1)

    def test_live_stereo_pose_failure_falls_back_to_bbox_stereo(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self, frame):
                self.frame = frame
                self.used = False

            def read_latest(self):
                if self.used:
                    return True, -1, None
                self.used = True
                return True, 42, self.frame

            def get_stats(self):
                return {}

        class FakeTracker:
            def __init__(self, bbox):
                self.bbox = bbox

            def process_frame(self, frame):
                return FakeTrackingResult([FakePerson(bbox=self.bbox)])

        class FailingPoseEstimator:
            def __call__(self, frame):
                raise RuntimeError("pose backend unavailable")

        message, diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=FakeReader(FakeFrame(timestamp_us=1_000_000)),
            right_reader=FakeReader(FakeFrame(timestamp_us=1_000_100)),
            left_tracker=FakeTracker((640, 240, 720, 520)),
            right_tracker=FakeTracker((608, 240, 688, 520)),
            left_pose_estimator=FailingPoseEstimator(),
            right_pose_estimator=FailingPoseEstimator(),
            sequence=0,
            max_read_attempts=1,
            sleep_seconds=0,
        )

        self.assertIsNotNone(message)
        self.assertEqual(message["targets"][0]["depth_source"], "pov_stereo_triangulation")
        self.assertEqual(message["targets"][0]["stereo"]["anchor_kind"], "bbox_top_center")
        self.assertEqual(diagnostics["keypoint_anchor"]["fallback_reason"], "pose_estimation_failed")

    def test_live_stereo_diagnostics_include_temporal_pair_details(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self, frames):
                self.frames = list(frames)

            def read_latest(self):
                if not self.frames:
                    return True, -1, None
                return self.frames.pop(0)

            def get_stats(self):
                return {}

        class FakeTracker:
            def __init__(self, bbox, latency_ms):
                self.bbox = bbox
                self.latency_ms = latency_ms

            def process_frame(self, frame):
                result = FakeTrackingResult([FakePerson(bbox=self.bbox)])
                result.frame_latency_ms = self.latency_ms
                return result

        message, diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=FakeReader([(True, 42, FakeFrame(timestamp_us=1_000_000))]),
            right_reader=FakeReader([(True, 42, FakeFrame(timestamp_us=1_012_500))]),
            left_tracker=FakeTracker((640, 240, 720, 520), latency_ms=7.5),
            right_tracker=FakeTracker((608, 240, 688, 520), latency_ms=9.25),
            sequence=0,
            max_read_attempts=1,
            sleep_seconds=0,
            max_pair_capture_delta_ms=15.0,
        )

        self.assertIsNotNone(message)
        temporal = diagnostics["temporal"]
        self.assertEqual(temporal["left_frame_id"], 42)
        self.assertEqual(temporal["right_frame_id"], 42)
        self.assertEqual(temporal["frame_id_delta"], 0)
        self.assertEqual(temporal["left_capture_timestamp_us"], 1_000_000)
        self.assertEqual(temporal["right_capture_timestamp_us"], 1_012_500)
        self.assertEqual(temporal["left_capture_timestamp_source"], "frame_timestamp_us")
        self.assertEqual(temporal["right_capture_timestamp_source"], "frame_timestamp_us")
        self.assertEqual(temporal["pair_capture_delta_ms"], 12.5)
        self.assertIsInstance(temporal["pair_receive_delta_ms"], float)
        self.assertEqual(temporal["left_tracker_latency_ms"], 7.5)
        self.assertEqual(temporal["right_tracker_latency_ms"], 9.25)
        self.assertEqual(message["timestamp_ms"], 1000)
        self.assertEqual(message["targets"][0]["timestamp_ms"], 1000)

        event = publisher.build_depth_trace_event(message=message, diagnostics=diagnostics)
        self.assertEqual(event["temporal"], temporal)
        self.assertEqual(event["pair_capture_delta_ms"], 12.5)
        self.assertEqual(event["frame_id_delta"], 0)

    def test_live_stereo_diagnostics_include_stage_timing_for_published_pair(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self, frame):
                self.frame = frame
                self.used = False

            def read_latest(self):
                if self.used:
                    return True, -1, None
                self.used = True
                return True, 42, self.frame

            def get_stats(self):
                return {}

        class FakeTracker:
            def __init__(self, bbox):
                self.bbox = bbox

            def process_frame(self, frame):
                return FakeTrackingResult([FakePerson(bbox=self.bbox)])

        message, diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=FakeReader(FakeFrame(timestamp_us=1_000_000)),
            right_reader=FakeReader(FakeFrame(timestamp_us=1_000_120)),
            left_tracker=FakeTracker((640, 240, 720, 520)),
            right_tracker=FakeTracker((608, 240, 688, 520)),
            sequence=0,
            max_read_attempts=1,
            sleep_seconds=0,
        )

        self.assertIsNotNone(message)
        stage_timing = diagnostics["stage_timing_ms"]
        for key in (
            "frame_read_ms",
            "pair_select_ms",
            "left_detect_ms",
            "right_detect_ms",
            "pair_build_ms",
            "stabilizer_ms",
            "message_build_ms",
            "total_ms",
        ):
            self.assertIn(key, stage_timing)
            self.assertIsInstance(stage_timing[key], float)
            self.assertGreaterEqual(stage_timing[key], 0.0)
        self.assertIsNone(diagnostics.get("non_publish_reason"))

        event = publisher.build_depth_trace_event(message=message, diagnostics=diagnostics)
        self.assertEqual(event["stage_timing_ms"], stage_timing)
        self.assertIsNone(event.get("non_publish_reason"))

    def test_rejected_trace_records_non_publish_reason_and_stage_timing(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self, frame):
                self.frame = frame
                self.used = False

            def read_latest(self):
                if self.used:
                    return True, -1, None
                self.used = True
                return True, 9, self.frame

            def get_stats(self):
                return {}

        class EmptyTracker:
            def process_frame(self, frame):
                return FakeTrackingResult([])

        message, diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=FakeReader(FakeFrame(timestamp_us=1_000_000)),
            right_reader=FakeReader(FakeFrame(timestamp_us=1_000_100)),
            left_tracker=EmptyTracker(),
            right_tracker=EmptyTracker(),
            sequence=5,
            max_read_attempts=1,
            sleep_seconds=0,
        )

        self.assertIsNone(message)
        self.assertEqual(diagnostics["reason"], "no_target")
        self.assertEqual(diagnostics["non_publish_reason"], "no_target")
        self.assertEqual(diagnostics["non_published_frames"][0]["reason"], "no_target")
        self.assertEqual(diagnostics["non_published_frames"][0]["left_frame_id"], 9)
        self.assertEqual(diagnostics["non_published_frames"][0]["right_frame_id"], 9)
        self.assertEqual(diagnostics["non_published_frames"][0]["pair_capture_delta_ms"], 0.1)
        self.assertIn("left_detect_ms", diagnostics["stage_timing_ms"])
        self.assertIn("pair_build_ms", diagnostics["stage_timing_ms"])

        event = publisher.build_depth_trace_event(message=None, diagnostics=diagnostics, sequence=5)
        self.assertEqual(event["event"], "rejected")
        self.assertEqual(event["non_publish_reason"], "no_target")
        self.assertEqual(event["non_published_frames"][0]["reason"], "no_target")
        self.assertEqual(event["stage_timing_ms"], diagnostics["stage_timing_ms"])

    def test_latest_state_publish_reuses_last_message_with_held_freshness(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeHub:
            def __init__(self):
                self.messages = []

            def client_count(self):
                return 1

            def status_summary(self):
                return {"active_client_count": 1, "active_clients": ["client-1=godot@127.0.0.1:1"]}

            def broadcast(self, message):
                self.messages.append(message)
                return 1

        message = {
            "type": "proxy_targets",
            "sequence": 10,
            "timestamp_ms": 1234,
            "targets": [
                {
                    "target_id": "vst_stereo-active-1",
                    "depth_source": "bbox_top_center_fallback",
                    "depth_confidence": "low",
                    "transform": {"position": [0.1, 0.2, 0.3]},
                }
            ],
            "cards": [{"card_id": "CardAnchor", "target_id": "vst_stereo-active-1"}],
        }
        diagnostics = {
            "reason": "target_ready",
            "non_publish_reason": None,
            "stage_timing_ms": {"total_ms": 1.0},
            "active_target_id": "active-1",
            "held_last_pose": False,
            "switch_reason": "active_continuity",
        }
        hub = FakeHub()
        state = publisher.LatestStereoPublishState()
        state.update(message=message, diagnostics=diagnostics)
        state.update(message=None, diagnostics={"reason": "no_target", "non_publish_reason": "no_target"})

        event = publisher.publish_latest_stereo_state_once(
            hub=hub,
            state=state,
            sequence=11,
            depth_trace=None,
            stale_after_ms=10_000.0,
        )

        self.assertEqual(event["event"], "accepted")
        self.assertEqual(event["sequence"], 11)
        self.assertEqual(event["freshness"]["state"], "held")
        self.assertEqual(event["freshness"]["reason"], "no_target")
        self.assertEqual(len(hub.messages), 1)
        self.assertEqual(hub.messages[0]["sequence"], 11)
        self.assertTrue(hub.messages[0]["targets"][0]["held"])
        self.assertEqual(hub.messages[0]["targets"][0]["freshness"]["state"], "held")

    def test_latest_state_publish_writes_rejected_trace_when_no_latest_message_exists(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeHub:
            def client_count(self):
                return 1

            def status_summary(self):
                return {"active_client_count": 1, "active_clients": ["client-1=monitor@127.0.0.1:2"]}

            def broadcast(self, message):
                raise AssertionError(f"should not publish without a latest message: {message!r}")

        state = publisher.LatestStereoPublishState()
        state.update(message=None, diagnostics={"reason": "no_target", "non_publish_reason": "no_target"})

        event = publisher.publish_latest_stereo_state_once(
            hub=FakeHub(),
            state=state,
            sequence=3,
            depth_trace=None,
        )

        self.assertEqual(event["event"], "rejected")
        self.assertEqual(event["sequence"], 3)
        self.assertEqual(event["non_publish_reason"], "no_target")
        self.assertEqual(event["freshness"]["state"], "empty")

    def test_live_stereo_trace_includes_header_timestamp_debug(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self, frame):
                self.frame = frame
                self.used = False

            def read_latest(self):
                if self.used:
                    return True, -1, None
                self.used = True
                return True, 55, self.frame

            def get_stats(self):
                return {}

        class FakeTracker:
            def __init__(self, bbox):
                self.bbox = bbox

            def process_frame(self, frame):
                return FakeTrackingResult([FakePerson(bbox=self.bbox)])

        left_frame = {
            "timestamp_us": 3_000_000,
            "available_timestamp_keys": ["frame_id", "hardware_timestamp"],
            "header_timestamp_debug": {"frame_id": 55, "hardware_timestamp": 3_000_000},
        }
        right_frame = {
            "timestamp_us": 3_004_000,
            "available_timestamp_keys": ["frame_id", "hardware_timestamp"],
            "header_timestamp_debug": {"frame_id": 55, "hardware_timestamp": 3_004_000},
        }

        message, diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=FakeReader(left_frame),
            right_reader=FakeReader(right_frame),
            left_tracker=FakeTracker((640, 240, 720, 520)),
            right_tracker=FakeTracker((608, 240, 688, 520)),
            sequence=0,
            max_read_attempts=1,
            sleep_seconds=0,
            max_pair_capture_delta_ms=10.0,
        )

        self.assertIsNotNone(message)
        temporal = diagnostics["temporal"]
        self.assertEqual(temporal["left_available_timestamp_keys"], ["frame_id", "hardware_timestamp"])
        self.assertEqual(temporal["right_available_timestamp_keys"], ["frame_id", "hardware_timestamp"])
        self.assertEqual(
            temporal["left_header_timestamp_debug"],
            {"frame_id": 55, "hardware_timestamp": 3_000_000},
        )
        self.assertEqual(
            temporal["right_header_timestamp_debug"],
            {"frame_id": 55, "hardware_timestamp": 3_004_000},
        )

        event = publisher.build_depth_trace_event(message=message, diagnostics=diagnostics)
        self.assertEqual(event["temporal"], temporal)

    def test_live_stereo_converts_vst_ai_shm_nv12_mapping_before_tracking(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self, timestamp_us):
                self.timestamp_us = timestamp_us
                self.used = False

            def read_latest(self):
                if self.used:
                    return True, -1, None
                self.used = True
                return True, 11, {
                    "width": 2,
                    "height": 2,
                    "stride": 2,
                    "payload": b"\x10\x10\x10\x10\x80\x80",
                    "timestamp_us": self.timestamp_us,
                }

            def get_stats(self):
                return {}

        class FakeNv12Array:
            def reshape(self, _shape):
                return self

        fake_numpy = types.SimpleNamespace(
            uint8=object(),
            frombuffer=lambda _payload, dtype=None: FakeNv12Array(),
        )

        class FakeBgrImage:
            def __getitem__(self, _key):
                return "BGR_FRAME"

        fake_cv2 = types.SimpleNamespace(
            COLOR_YUV2BGR_NV12=91,
            cvtColor=lambda _yuv, _code: FakeBgrImage(),
        )

        class FakeTracker:
            def __init__(self, bbox):
                self.bbox = bbox

            def process_frame(self, frame):
                if frame != "BGR_FRAME":
                    raise AssertionError(f"expected converted BGR frame, got {frame!r}")
                return FakeTrackingResult([FakePerson(bbox=self.bbox)])

        with mock.patch.dict(sys.modules, {"numpy": fake_numpy, "cv2": fake_cv2}):
            message, diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
                left_reader=FakeReader(1_000_000),
                right_reader=FakeReader(1_004_000),
                left_tracker=FakeTracker((640, 240, 720, 520)),
                right_tracker=FakeTracker((608, 240, 688, 520)),
                sequence=0,
                max_read_attempts=1,
                sleep_seconds=0,
            )

        self.assertIsNotNone(message)
        self.assertEqual(diagnostics["temporal"]["left_capture_timestamp_source"], "frame_timestamp_us")
        self.assertEqual(diagnostics["temporal"]["right_capture_timestamp_source"], "frame_timestamp_us")

    def test_live_stereo_message_uses_runtime_timestamp_ms_for_record_timestamp(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self, frames):
                self.frames = list(frames)

            def read_latest(self):
                if not self.frames:
                    return True, -1, None
                return self.frames.pop(0)

            def get_stats(self):
                return {}

        class FakeTracker:
            def __init__(self, bbox):
                self.bbox = bbox

            def process_frame(self, frame):
                return FakeTrackingResult([FakePerson(bbox=self.bbox)])

        message, diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=FakeReader([(True, 42, FakeFrame(timestamp_ms=1234.25))]),
            right_reader=FakeReader([(True, 43, FakeFrame(timestamp_ms=1234.75))]),
            left_tracker=FakeTracker((640, 240, 720, 520)),
            right_tracker=FakeTracker((608, 240, 688, 520)),
            sequence=9,
            max_read_attempts=1,
            sleep_seconds=0,
            max_pair_capture_delta_ms=5.0,
        )

        self.assertIsNotNone(message)
        self.assertEqual(message["timestamp_ms"], 1234)
        self.assertEqual(message["targets"][0]["timestamp_ms"], 1234)
        self.assertEqual(diagnostics["temporal"]["left_capture_timestamp_source"], "frame_timestamp_ms")
        self.assertEqual(diagnostics["temporal"]["right_capture_timestamp_source"], "frame_timestamp_ms")

    def test_live_stereo_uses_exposure_timestamp_for_capture_pairing(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self, frames):
                self.frames = list(frames)

            def read_latest(self):
                if not self.frames:
                    return True, -1, None
                return self.frames.pop(0)

            def get_stats(self):
                return {}

        class FakeTracker:
            def __init__(self, bbox):
                self.bbox = bbox

            def process_frame(self, frame):
                return FakeTrackingResult([FakePerson(bbox=self.bbox)])

        message, diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=FakeReader([(True, 42, FakeFrame(exposure_timestamp=2_000_000))]),
            right_reader=FakeReader([(True, 43, FakeFrame(exposure_timestamp=2_004_000))]),
            left_tracker=FakeTracker((640, 240, 720, 520)),
            right_tracker=FakeTracker((608, 240, 688, 520)),
            sequence=0,
            max_read_attempts=1,
            sleep_seconds=0,
            max_pair_capture_delta_ms=10.0,
        )

        self.assertIsNotNone(message)
        temporal = diagnostics["temporal"]
        self.assertEqual(diagnostics["sync"]["pairing_strategy"], "capture_timestamp")
        self.assertEqual(temporal["left_capture_timestamp_us"], 2_000_000)
        self.assertEqual(temporal["right_capture_timestamp_us"], 2_004_000)
        self.assertEqual(temporal["left_capture_timestamp_source"], "frame_exposure_timestamp")
        self.assertEqual(temporal["right_capture_timestamp_source"], "frame_exposure_timestamp")
        self.assertEqual(temporal["pair_capture_delta_ms"], 4.0)

    def test_live_stereo_uses_exposure_us_for_capture_pairing(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self, frames):
                self.frames = list(frames)

            def read_latest(self):
                if not self.frames:
                    return True, -1, None
                return self.frames.pop(0)

            def get_stats(self):
                return {}

        class FakeTracker:
            def __init__(self, bbox):
                self.bbox = bbox

            def process_frame(self, frame):
                return FakeTrackingResult([FakePerson(bbox=self.bbox)])

        message, diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=FakeReader([(True, 52, {"exposure_us": 4_000_000})]),
            right_reader=FakeReader([(True, 53, {"exposure_us": 4_000_286})]),
            left_tracker=FakeTracker((640, 240, 720, 520)),
            right_tracker=FakeTracker((608, 240, 688, 520)),
            sequence=0,
            max_read_attempts=1,
            sleep_seconds=0,
            max_pair_capture_delta_ms=10.0,
        )

        self.assertIsNotNone(message)
        temporal = diagnostics["temporal"]
        self.assertEqual(diagnostics["sync"]["pairing_strategy"], "capture_timestamp")
        self.assertEqual(temporal["left_capture_timestamp_us"], 4_000_000)
        self.assertEqual(temporal["right_capture_timestamp_us"], 4_000_286)
        self.assertEqual(temporal["left_capture_timestamp_source"], "frame_exposure_us")
        self.assertEqual(temporal["right_capture_timestamp_source"], "frame_exposure_us")
        self.assertEqual(temporal["pair_capture_delta_ms"], 0.286)

    def test_live_stereo_pairs_closest_capture_timestamps_before_tracking(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self, frames):
                self.frames = list(frames)

            def read_latest(self):
                if not self.frames:
                    return True, -1, None
                return self.frames.pop(0)

            def get_stats(self):
                return {}

        class FakeTracker:
            def __init__(self, bbox):
                self.bbox = bbox
                self.frames = []

            def process_frame(self, frame):
                self.frames.append(frame.timestamp_us)
                return FakeTrackingResult([FakePerson(bbox=self.bbox)])

        left_tracker = FakeTracker((640, 240, 720, 520))
        right_tracker = FakeTracker((608, 240, 688, 520))

        message, diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=FakeReader(
                [
                    (True, 100, FakeFrame(timestamp_us=1_000_000)),
                    (True, 101, FakeFrame(timestamp_us=1_022_222)),
                ]
            ),
            right_reader=FakeReader([(True, 201, FakeFrame(timestamp_us=1_000_500))]),
            left_tracker=left_tracker,
            right_tracker=right_tracker,
            sequence=0,
            max_read_attempts=2,
            sleep_seconds=0,
            max_pair_capture_delta_ms=5.0,
        )

        self.assertIsNotNone(message)
        self.assertEqual(left_tracker.frames, [1_000_000])
        self.assertEqual(right_tracker.frames, [1_000_500])
        self.assertEqual(diagnostics["reason"], "target_ready")
        self.assertEqual(diagnostics["temporal"]["left_frame_id"], 100)
        self.assertEqual(diagnostics["temporal"]["right_frame_id"], 201)
        self.assertEqual(diagnostics["temporal"]["pair_capture_delta_ms"], 0.5)
        self.assertEqual(diagnostics["sync"]["pairing_strategy"], "capture_timestamp")

        event = publisher.build_depth_trace_event(message=message, diagnostics=diagnostics)
        self.assertEqual(event["left_frame_id"], 100)
        self.assertEqual(event["right_frame_id"], 201)
        self.assertEqual(event["sync"]["pairing_strategy"], "capture_timestamp")

    def test_live_stereo_rejects_timestamp_mismatch_and_reports_drops(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self, frames):
                self.frames = list(frames)

            def read_latest(self):
                if not self.frames:
                    return True, -1, None
                return self.frames.pop(0)

            def get_stats(self):
                return {}

        class FakeTracker:
            calls = 0

            def process_frame(self, frame):
                self.calls += 1
                return FakeTrackingResult([FakePerson()])

        left_tracker = FakeTracker()
        right_tracker = FakeTracker()

        message, diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=FakeReader([(True, 10, FakeFrame(timestamp_us=1_000_000))]),
            right_reader=FakeReader([(True, 11, FakeFrame(timestamp_us=1_030_000))]),
            left_tracker=left_tracker,
            right_tracker=right_tracker,
            sequence=0,
            max_read_attempts=1,
            sleep_seconds=0,
            max_pair_capture_delta_ms=5.0,
        )

        self.assertIsNone(message)
        self.assertEqual(left_tracker.calls, 0)
        self.assertEqual(right_tracker.calls, 0)
        self.assertEqual(diagnostics["reason"], "temporal_mismatch")
        self.assertEqual(diagnostics["sync"]["temporal_mismatch_count"], 1)
        self.assertEqual(diagnostics["realtime"]["target_source_hz"], 45.0)
        self.assertEqual(diagnostics["realtime"]["frames_seen_left"], 1)
        self.assertEqual(diagnostics["realtime"]["frames_seen_right"], 1)

    def test_live_stereo_message_uses_stable_active_target_and_traces_raw_ids(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self, frames):
                self.frames = list(frames)

            def read_latest(self):
                if not self.frames:
                    return True, -1, None
                return self.frames.pop(0)

            def get_stats(self):
                return {}

        class FakeTracker:
            def __init__(self, people_by_call):
                self.people_by_call = list(people_by_call)
                self.calls = 0

            def process_frame(self, frame):
                people = self.people_by_call[self.calls]
                self.calls += 1
                return FakeTrackingResult(people)

        stabilizer = publisher.StereoActiveTargetStabilizer(switch_confirm_frames=2, switch_score_margin=0.05)
        first, first_diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=FakeReader([(True, 50, FakeFrame())]),
            right_reader=FakeReader([(True, 50, FakeFrame())]),
            left_tracker=FakeTracker([[FakePerson(track_id=1, bbox=(640, 240, 720, 520), confidence=0.70)]]),
            right_tracker=FakeTracker([[FakePerson(track_id=2, bbox=(608, 240, 688, 520), confidence=0.70)]]),
            sequence=0,
            max_read_attempts=1,
            sleep_seconds=0,
            target_stabilizer=stabilizer,
        )
        second, second_diagnostics = publisher.next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=FakeReader([(True, 51, FakeFrame())]),
            right_reader=FakeReader([(True, 51, FakeFrame())]),
            left_tracker=FakeTracker(
                [[FakePerson(track_id=1, bbox=(641, 240, 721, 520), confidence=0.62), FakePerson(track_id=9, bbox=(420, 250, 500, 530), confidence=0.96)]]
            ),
            right_tracker=FakeTracker(
                [[FakePerson(track_id=2, bbox=(609, 240, 689, 520), confidence=0.62), FakePerson(track_id=10, bbox=(388, 250, 468, 530), confidence=0.96)]]
            ),
            sequence=1,
            max_read_attempts=1,
            sleep_seconds=0,
            target_stabilizer=stabilizer,
        )

        self.assertEqual(first["targets"][0]["target_id"], "vst_stereo-active-1")
        self.assertEqual(second["targets"][0]["target_id"], "vst_stereo-active-1")
        self.assertEqual(first_diagnostics["raw_left_track_id"], 1)
        self.assertEqual(second_diagnostics["raw_right_track_id"], 2)
        self.assertEqual(second_diagnostics["candidate_count"], 4)
        self.assertEqual(second_diagnostics["switch_count"], 0)
        self.assertEqual(second_diagnostics["switch_reason"], "active_continuity")

        event = publisher.build_depth_trace_event(message=second, diagnostics=second_diagnostics)
        self.assertEqual(event["active_target_id"], "active-1")
        self.assertEqual(event["raw_left_track_id"], 1)
        self.assertEqual(event["raw_right_track_id"], 2)
        self.assertEqual(event["candidate_count"], 4)
        self.assertEqual(event["switch_reason"], "active_continuity")
        self.assertEqual(event["active_state"], "TRACKING_STEREO")
        self.assertTrue(event["left_active_seen"])
        self.assertTrue(event["right_active_seen"])
        self.assertEqual(event["mono_missing_frames"], 0)
        self.assertEqual(event["both_missing_frames"], 0)
        self.assertTrue(event["depth_update_allowed"])
        self.assertFalse(event["held_last_pose"])

    def test_depth_trace_event_records_accepted_target_depth_details(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        stereo_record = {
            "source": "vst_stereo_bbox",
            "frame_id": 10,
            "pair_id": "pair-000010",
            "person_id": "person-2-4",
            "timestamp_ms": 1780911169157,
            "left_bbox_xyxy": [640, 240, 720, 520],
            "right_bbox_xyxy": [608, 240, 688, 520],
            "confidence": 0.91,
        }
        message = publisher.build_proxy_targets_message_from_stereo_bbox_record(
            stereo_record,
            sequence=3,
            card_id="StereoCard",
            recorded_width=880,
            recorded_height=660,
        )

        event = publisher.build_depth_trace_event(
            message=message,
            diagnostics={"reason": "target_ready", "last_pair_frame_id": 10},
        )

        self.assertEqual(event["event"], "accepted")
        self.assertEqual(event["sequence"], 3)
        self.assertEqual(event["target_id"], "vst_stereo-person-2-4")
        self.assertEqual(event["left_frame_id"], 10)
        self.assertEqual(event["right_frame_id"], 10)
        self.assertEqual(event["depth_source"], "pov_stereo_triangulation")
        self.assertEqual(event["depth_confidence"], "high")
        self.assertIsInstance(event["depth_m"], float)
        self.assertEqual(event["source_frame"]["anchor_depth"], event["depth_m"])
        self.assertIn("camera_point_m", event)
        self.assertIn("head_position_m", event)
        self.assertIsInstance(event["camera_point_m"], list)
        self.assertIsInstance(event["head_position_m"], list)
        self.assertEqual(len(event["camera_point_m"]), 3)
        self.assertEqual(len(event["head_position_m"]), 3)
        self.assertIn("bbox", event)
        self.assertEqual(event["stereo"]["pair_id"], "pair-000010")

    def test_depth_trace_event_preserves_stereo_fields_after_context_is_consumed(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        stereo_record = {
            "source": "vst_stereo_bbox",
            "frame_id": 10,
            "pair_id": "pair-000010",
            "person_id": "person-2-4",
            "timestamp_ms": 1780911169157,
            "left_bbox_xyxy": [640, 240, 720, 520],
            "right_bbox_xyxy": [608, 240, 688, 520],
            "confidence": 0.91,
        }
        message = publisher.build_proxy_targets_message_from_stereo_bbox_record(
            stereo_record,
            sequence=3,
            card_id="StereoCard",
            recorded_width=880,
            recorded_height=660,
        )

        first = publisher.build_depth_trace_event(
            message=message,
            diagnostics={"reason": "target_ready", "last_pair_frame_id": 10},
        )
        stale = publisher.build_depth_trace_event(
            message=message,
            diagnostics={"reason": "target_ready", "last_pair_frame_id": 10, "held_last_pose": True},
        )

        self.assertEqual(first["stereo"]["pair_id"], "pair-000010")
        self.assertEqual(stale["stereo"]["pair_id"], "pair-000010")
        self.assertEqual(stale["stereo"]["depth_source"], "pov_stereo_triangulation")
        self.assertTrue(stale["held_last_pose"])

    def test_depth_trace_writer_appends_rejected_events_as_jsonl(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_stereo_proxy_targets_live_publisher")

        trace_path = ROOT / ".tmp" / "tests" / f"depth_estimation_trace_{uuid.uuid4().hex}.jsonl"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.unlink(missing_ok=True)
        publisher.write_depth_trace_event(
            trace_path,
            publisher.build_depth_trace_event(
                message=None,
                diagnostics={
                    "reason": "no_target",
                    "read_attempts": 7,
                    "frames_seen_left": 3,
                    "frames_seen_right": 2,
                    "last_pair_frame_id": 42,
                    "left_pending": 1,
                    "right_pending": 0,
                },
                sequence=5,
            ),
        )

        rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
        try:
            trace_path.unlink(missing_ok=True)
        except PermissionError:
            pass

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "rejected")
        self.assertEqual(rows[0]["sequence"], 5)
        self.assertEqual(rows[0]["reason"], "no_target")
        self.assertEqual(rows[0]["left_frame_id"], 42)
        self.assertEqual(rows[0]["right_frame_id"], 42)
        self.assertEqual(rows[0]["read_attempts"], 7)

    def test_runner_wires_depth_trace_jsonl_into_stereo_publisher(self):
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("depth_estimation_trace.jsonl", source)
        self.assertIn("--depth-trace", source)
        self.assertIn("EnableKeypointAnchor", source)
        self.assertIn("--enable-keypoint-anchor", source)
        self.assertIn("--min-keypoint-score", source)

    def test_runner_declares_stereo_source_and_staged_probe(self):
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("antman_vst_stereo_proxy_targets_live_publisher.py", source)
        self.assertIn("run_godot_script_only_staged_probe.ps1", source)
        self.assertIn("Left/Right VST SHM", source)
        self.assertIn("-ExternalPublisher", source)
        self.assertIn("run_proxy_targets_live_monitor.ps1", source)
        self.assertIn("finally", source)


if __name__ == "__main__":
    unittest.main()
