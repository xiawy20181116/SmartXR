import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIVE_PUBLISHER = ROOT / "tools" / "antman_vst_proxy_targets_live_publisher.py"
RUNNER = ROOT / "tools" / "run_antman_vst_proxy_targets_live_publisher.ps1"
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
    def __init__(self, track_id=2, bbox=(229, 297, 357, 470), confidence=0.568, tracking_status="new"):
        self.track_id = track_id
        self.bbox = bbox
        self.confidence = confidence
        self.tracking_status = tracking_status


class FakeTrackingResult:
    def __init__(self, people):
        self.people = people
        self.frame_index = 7
        self.frame_latency_ms = 12.5


class AntmanVstProxyTargetsLivePublisherTests(unittest.TestCase):
    def test_builds_schema_valid_proxy_targets_message_from_live_tracker_frame(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_proxy_targets_live_publisher")
        validator = load_module(VALIDATOR, "validate_proxy_targets_payload_schema")

        message = publisher.build_proxy_targets_message_from_live_frame(
            frame=FakeFrame(),
            frame_id=743,
            timestamp_ms=1780911169157,
            tracking_result=FakeTrackingResult([FakePerson()]),
            sequence=3,
            card_id="LiveCard",
        )

        self.assertIsNotNone(message)
        self.assertEqual(message["sequence"], 3)
        self.assertEqual(message["targets"][0]["target_id"], "vst-person-2")
        self.assertEqual(message["targets"][0]["state"], "tracked")
        self.assertEqual(message["targets"][0]["source_coordinate"]["depth_source"], "default_depth")
        self.assertEqual(message["targets"][0]["source_coordinate"]["source_frame"]["anchor_depth"], 5.0)
        self.assertEqual(message["cards"][0]["card_id"], "LiveCard")
        self.assertEqual(validator.validate_message(message), [])

    def test_next_live_message_skips_empty_frames_and_publishes_first_target(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_proxy_targets_live_publisher")

        class FakeReader:
            def __init__(self):
                self.index = 0

            def read_latest(self):
                self.index += 1
                return True, 740 + self.index, FakeFrame()

            def get_stats(self):
                return {"received_frames": self.index}

        class FakeTracker:
            def __init__(self):
                self.calls = 0

            def process_frame(self, frame):
                self.calls += 1
                people = [] if self.calls == 1 else [FakePerson(track_id=5, tracking_status="tracked")]
                return FakeTrackingResult(people)

        message = publisher.next_live_proxy_targets_message(
            reader=FakeReader(),
            tracker=FakeTracker(),
            sequence=0,
            min_confidence=0.5,
            max_empty_reads=3,
        )

        self.assertIsNotNone(message)
        self.assertEqual(message["sequence"], 0)
        self.assertEqual(message["targets"][0]["target_id"], "vst-person-5")

    def test_source_mentions_antman_reader_tracker_and_websocket_boundary(self):
        source = LIVE_PUBLISHER.read_text(encoding="utf-8")

        self.assertIn("_create_live_reader_and_tracker", source)
        self.assertIn("VST SHM + HumanTrackor", source)
        self.assertIn("proxy_targets live publisher listening", source)
        self.assertIn("waiting for WebSocket client", source)
        self.assertIn("sent seq appears after a client connects", source)
        self.assertIn("No target frames available", source)
        self.assertIn("source diagnostics:", source)

    def test_live_diagnostics_distinguishes_no_frames_from_no_targets(self):
        publisher = load_module(LIVE_PUBLISHER, "antman_vst_proxy_targets_live_publisher")

        class NoFrameReader:
            def __init__(self):
                self.calls = 0

            def read_latest(self):
                self.calls += 1
                return True, -1, None

            def get_stats(self):
                return {"received_frames": 0, "last_frame_id": -1}

        class EmptyTracker:
            def process_frame(self, frame):
                return FakeTrackingResult([])

        message, diagnostics = publisher.next_live_proxy_targets_message_with_diagnostics(
            reader=NoFrameReader(),
            tracker=EmptyTracker(),
            sequence=0,
            max_empty_reads=2,
            sleep_seconds=0,
        )

        self.assertIsNone(message)
        self.assertEqual(diagnostics["reason"], "no_frame")
        self.assertEqual(diagnostics["read_attempts"], 2)
        self.assertEqual(diagnostics["frames_seen"], 0)
        self.assertEqual(diagnostics["tracker_people"], 0)
        self.assertIn("reason=no_frame", publisher.format_source_diagnostics(diagnostics))

        class EmptyTargetReader:
            def read_latest(self):
                return True, 743, FakeFrame()

            def get_stats(self):
                return {"received_frames": 1, "last_frame_id": 743}

        message, diagnostics = publisher.next_live_proxy_targets_message_with_diagnostics(
            reader=EmptyTargetReader(),
            tracker=EmptyTracker(),
            sequence=0,
            max_empty_reads=1,
            sleep_seconds=0,
        )

        self.assertIsNone(message)
        self.assertEqual(diagnostics["reason"], "no_target")
        self.assertEqual(diagnostics["frames_seen"], 1)
        self.assertEqual(diagnostics["last_frame_id"], 743)
        self.assertEqual(diagnostics["tracker_people"], 0)
        self.assertIn("reason=no_target", publisher.format_source_diagnostics(diagnostics))

    def test_runner_selects_antman_python_and_starts_live_publisher(self):
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("antman_vst_proxy_targets_live_publisher.py", source)
        self.assertIn("human_detect\\.venv\\Scripts\\python.exe", source)
        self.assertIn("--host", source)
        self.assertIn("--port", source)
        self.assertIn("--min-confidence", source)
        self.assertIn("Seq appears after a WebSocket client connects", source)
        self.assertIn("WebSocket listener was not started", source)
        self.assertIn("VST SHM source is unavailable", source)


if __name__ == "__main__":
    unittest.main()
