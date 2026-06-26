from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


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
        self.assertEqual(message["targets"][0]["depth_source"], "bbox_top_center_fallback")
        self.assertEqual(message["targets"][0]["depth_confidence"], "low")
        self.assertEqual(message["targets"][0]["source_coordinate"]["depth_source"], "bbox_top_center_fallback")
        self.assertEqual(message["targets"][0]["source_coordinate"]["depth_confidence"], "low")
        self.assertEqual(message["cards"][0]["card_id"], "StereoCard")
        self.assertEqual(validator.validate_message(message), [])

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
        self.assertEqual(message["targets"][0]["depth_source"], "bbox_top_center_fallback")
        self.assertEqual(diagnostics["reason"], "target_ready")
        self.assertEqual(diagnostics["frames_seen_left"], 2)
        self.assertEqual(diagnostics["frames_seen_right"], 1)
        self.assertEqual(diagnostics["last_pair_frame_id"], 42)

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
