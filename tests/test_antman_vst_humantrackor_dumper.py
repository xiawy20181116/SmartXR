import importlib.util
import json
import uuid
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DUMPER = ROOT / "tools" / "dump_antman_vst_humantrackor_jsonl.py"
RUNNER = ROOT / "tools" / "run_antman_vst_target_sample_capture.ps1"
TMP = ROOT / ".tmp" / "test_antman_vst_humantrackor_dumper"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeFrame:
    shape = (652, 872, 3)


class FakePerson:
    def __init__(self, track_id=7, bbox=(100, 120, 260, 340), confidence=0.91, tracking_status="tracked"):
        self.track_id = track_id
        self.bbox = bbox
        self.confidence = confidence
        self.tracking_status = tracking_status


class FakeTrackingResult:
    def __init__(self, people, frame_index=3, frame_latency_ms=4.5):
        self.people = people
        self.frame_index = frame_index
        self.frame_latency_ms = frame_latency_ms


class AntmanVstHumanTrackorDumperTests(unittest.TestCase):
    def setUp(self):
        self.out_path = TMP / f"{uuid.uuid4().hex}.jsonl"
        self.out_path.parent.mkdir(parents=True, exist_ok=True)

    def test_builds_jsonl_record_from_tracker_result(self):
        dumper = load_module(DUMPER, "dump_antman_vst_humantrackor_jsonl")

        record = dumper.build_frame_record(
            frame=FakeFrame(),
            frame_id=42,
            timestamp_ms=1780899000000,
            tracking_result=FakeTrackingResult([FakePerson()]),
            source_stats={"producer_pid": 1234},
        )

        self.assertEqual(record["source"], "vst")
        self.assertEqual(record["frame_id"], 42)
        self.assertEqual(record["image_width"], 872)
        self.assertEqual(record["image_height"], 652)
        self.assertEqual(record["people"][0]["track_id"], 7)
        self.assertEqual(record["people"][0]["bbox"], [100, 120, 260, 340])
        self.assertEqual(record["people"][0]["confidence"], 0.91)
        self.assertEqual(record["source_stats"]["producer_pid"], 1234)

    def test_resolves_dual_eye_shm_name_for_antman_v1_contract(self):
        dumper = load_module(DUMPER, "dump_antman_vst_humantrackor_jsonl")

        self.assertEqual(dumper.resolve_vst_shm_name("Antman.VST.AI.v1", "Right"), "Antman.VST.AI.v1.Right")
        self.assertEqual(dumper.resolve_vst_shm_name("Antman.VST.AI.v1", "Left"), "Antman.VST.AI.v1.Left")
        self.assertEqual(dumper.resolve_vst_shm_name("Antman.VST.AI.v1.Right", "Right"), "Antman.VST.AI.v1.Right")
        self.assertEqual(dumper.resolve_vst_shm_name("Antman.VST.AI.v1", ""), "Antman.VST.AI.v1")

        with self.assertRaises(ValueError):
            dumper.resolve_vst_shm_name("Antman.VST.AI.v1", "Center")

    def test_dump_session_writes_empty_frames_and_stops_after_first_target_window(self):
        dumper = load_module(DUMPER, "dump_antman_vst_humantrackor_jsonl")

        frames = [(True, 10, FakeFrame()), (True, 11, FakeFrame()), (True, 12, FakeFrame())]

        class FakeReader:
            def __init__(self):
                self.index = 0
                self.released = False

            def read_latest(self):
                if self.index >= len(frames):
                    return True, -1, None
                item = frames[self.index]
                self.index += 1
                return item

            def get_stats(self):
                return {"received_frames": self.index}

            def release(self):
                self.released = True

        class FakeTracker:
            def __init__(self):
                self.calls = 0

            def process_frame(self, frame):
                self.calls += 1
                people = [] if self.calls == 1 else [FakePerson(track_id=8)]
                return FakeTrackingResult(people, frame_index=self.calls)

        reader = FakeReader()
        status = dumper.dump_vst_humantrackor_jsonl(
            reader=reader,
            tracker=FakeTracker(),
            out_path=self.out_path,
            duration_seconds=30.0,
            stop_after_first_target_frames=2,
            sleep_seconds=0.0,
            clock=lambda: float(reader.index),
        )

        records = [json.loads(line) for line in self.out_path.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(reader.released)
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["people"], [])
        self.assertEqual(records[1]["people"][0]["track_id"], 8)
        self.assertTrue(status["target_observed"])
        self.assertEqual(status["frames_written"], 3)
        self.assertEqual(status["empty_frames"], 1)

    def test_runner_wires_dumper_to_target_sample_session_tool(self):
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("dump_antman_vst_humantrackor_jsonl.py", source)
        self.assertIn("capture_vst_target_sample_session.py", source)
        self.assertIn("vst_target_frames.jsonl", source)
        self.assertIn("Need headset", source)
        self.assertIn("$PythonExe", source)
        self.assertIn("human_detect\\.venv\\Scripts\\python.exe", source)
        self.assertIn(".venv\\Scripts\\python.exe", source)
        self.assertIn(".uv-venv\\Scripts\\python.exe", source)
        self.assertIn("[string]$ShmEye = \"Right\"", source)
        self.assertIn("--shm-eye", source)
        self.assertIn("Dependency unavailable", source)

    def test_dumper_reports_missing_dependency_separately_from_vst_source(self):
        dumper = load_module(DUMPER, "dump_antman_vst_humantrackor_jsonl")

        status, exit_code = dumper.startup_error_status(ModuleNotFoundError("No module named 'numpy'"), self.out_path)

        self.assertEqual(exit_code, 3)
        self.assertEqual(status["reason"], "dependency_unavailable")
        self.assertFalse(status["source_alive"])
        self.assertIn("numpy", status["error"])


if __name__ == "__main__":
    unittest.main()
