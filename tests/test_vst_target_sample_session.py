import importlib.util
import json
import subprocess
import sys
import uuid
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "capture_vst_target_sample_session.py"
PUBLISHER = ROOT / "tools" / "vst_proxy_targets_publisher.py"
VALIDATOR = ROOT / "tools" / "validate_proxy_targets_payload_schema.py"
TMP = ROOT / ".tmp" / "test_vst_target_sample_session"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class VSTTargetSampleSessionTests(unittest.TestCase):
    def setUp(self):
        self.out_dir = TMP / uuid.uuid4().hex
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def test_writes_session_and_first_target_sample_after_empty_frames(self):
        capture = load_module(TOOL, "capture_vst_target_sample_session")
        frames = [
            {
                "frame_id": 10,
                "timestamp_ms": 1000,
                "image_width": 872,
                "image_height": 652,
                "people": [],
            },
            {
                "frame_id": 11,
                "timestamp_ms": 1016,
                "image_width": 872,
                "image_height": 652,
                "people": [
                    {
                        "track_id": 7,
                        "bbox": [100, 120, 260, 340],
                        "confidence": 0.91,
                        "tracking_status": "tracked",
                    }
                ],
            },
        ]

        status = capture.capture_target_sample_session(frames, self.out_dir, min_confidence=0.5)

        self.assertTrue(status["source_alive"])
        self.assertEqual(status["frames_seen"], 2)
        self.assertEqual(status["empty_frames"], 1)
        self.assertTrue(status["target_sample_ready"])
        self.assertEqual(status["first_target_frame"], 11)
        self.assertEqual(status["reason"], "target_sample_ready")

        session_lines = (self.out_dir / "vst_capture_session.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(session_lines), 2)
        self.assertEqual(json.loads(session_lines[0])["detections"], [])

        first_sample = json.loads((self.out_dir / "vst_first_target_sample.json").read_text(encoding="utf-8"))
        self.assertEqual(first_sample["source"], "vst")
        self.assertEqual(first_sample["sequence"], 11)
        self.assertEqual(first_sample["image"], {"w": 872, "h": 652})
        self.assertEqual(first_sample["detections"][0]["id"], "person-7")
        self.assertEqual(first_sample["detections"][0]["bbox"], {"cx": 180.0, "cy": 230.0, "w": 160.0, "h": 220.0})

    def test_no_target_observed_is_not_source_failure(self):
        capture = load_module(TOOL, "capture_vst_target_sample_session")
        frames = [
            {"frame_id": 1, "timestamp_ms": 1000, "image": {"w": 640, "h": 480}, "detections": []},
            {"frame_id": 2, "timestamp_ms": 1016, "image": {"w": 640, "h": 480}, "detections": []},
        ]

        status = capture.capture_target_sample_session(frames, self.out_dir)

        self.assertTrue(status["source_alive"])
        self.assertEqual(status["frames_seen"], 2)
        self.assertFalse(status["target_sample_ready"])
        self.assertEqual(status["reason"], "no_target_observed")
        self.assertFalse((self.out_dir / "vst_first_target_sample.json").exists())

    def test_empty_input_reports_no_frames_seen(self):
        capture = load_module(TOOL, "capture_vst_target_sample_session")

        status = capture.capture_target_sample_session([], self.out_dir)

        self.assertFalse(status["source_alive"])
        self.assertEqual(status["frames_seen"], 0)
        self.assertFalse(status["target_sample_ready"])
        self.assertEqual(status["reason"], "no_frames_seen")

    def test_cli_stdin_jsonl_sample_feeds_existing_proxy_targets_gate(self):
        input_jsonl = "\n".join(
            [
                json.dumps({"frame_id": 1, "image_width": 872, "image_height": 652, "people": []}),
                json.dumps(
                    {
                        "frame_id": 2,
                        "image_width": 872,
                        "image_height": 652,
                        "people": [
                            {
                                "track_id": 8,
                                "bbox": {"x1": 200, "y1": 100, "x2": 300, "y2": 260},
                                "confidence": 0.88,
                            }
                        ],
                    }
                ),
            ]
        )

        completed = subprocess.run(
            [sys.executable, str(TOOL), "--stdin-jsonl", "--out-dir", str(self.out_dir), "--min-confidence", "0.5"],
            cwd=ROOT,
            input=input_jsonl,
            text=True,
            capture_output=True,
            check=True,
        )
        status = json.loads(completed.stdout)
        self.assertTrue(status["target_sample_ready"])

        proxy = subprocess.run(
            [
                sys.executable,
                str(PUBLISHER),
                "--input",
                str(self.out_dir / "vst_first_target_sample.json"),
                "--print-once",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        validator = load_module(VALIDATOR, "validate_proxy_targets_payload_schema")
        self.assertEqual(validator.validate_message(json.loads(proxy.stdout)), [])


if __name__ == "__main__":
    unittest.main()
