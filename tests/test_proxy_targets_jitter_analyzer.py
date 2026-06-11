import importlib.util
import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANALYZER = ROOT / "tools" / "analyze_proxy_targets_jitter.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_session(path: Path, frames):
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for frame in frames:
            handle.write(json.dumps(frame, separators=(",", ":")) + "\n")


def noisy_session_frames(count=60, noise_px=4.0, seed=7):
    rng = random.Random(seed)
    frames = []
    for index in range(count):
        cx = 436.0 + rng.gauss(0.0, noise_px)
        cy = 326.0 + rng.gauss(0.0, noise_px)
        frames.append(
            {
                "frame_id": index + 1,
                "timestamp_ms": 1780899000000 + index * 50,
                "image_width": 872,
                "image_height": 652,
                "people": [
                    {
                        "track_id": 7,
                        "bbox": [int(cx - 80), int(cy - 110), int(cx + 80), int(cy + 110)],
                        "confidence": 0.91,
                        "tracking_status": "tracked",
                    }
                ],
            }
        )
    return frames


class JitterAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = load_module(ANALYZER, "analyze_proxy_targets_jitter")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session_path = Path(self.tmp.name) / "session.jsonl"

    def test_loads_samples_through_publisher_math(self):
        write_session(self.session_path, noisy_session_frames(count=10))
        samples = self.analyzer.load_session_samples(self.session_path)
        self.assertIn("vst-person-7", samples)
        self.assertEqual(len(samples["vst-person-7"]), 10)
        position = samples["vst-person-7"][0]["position"]
        self.assertEqual(len(position), 3)
        self.assertLess(position[2], 0.0)
        self.assertIn("pixel_center", samples["vst-person-7"][0])

    def test_empty_frames_are_skipped_and_no_targets_raises(self):
        write_session(
            self.session_path,
            [{"frame_id": 1, "timestamp_ms": 0, "image_width": 872, "image_height": 652, "people": []}],
        )
        with self.assertRaises(ValueError):
            self.analyzer.load_session_samples(self.session_path)

    def test_report_contains_raw_metrics(self):
        write_session(self.session_path, noisy_session_frames())
        samples = self.analyzer.load_session_samples(self.session_path)
        smoother = self.analyzer.TargetPositionSmoother("none")
        report = self.analyzer.build_report(samples, smoother)
        entry = report["targets"]["vst-person-7"]
        self.assertEqual(entry["raw"]["frames"], 60)
        self.assertGreater(entry["raw"]["frame_delta_m"]["mean"], 0.0)
        self.assertGreaterEqual(
            entry["raw"]["frame_delta_m"]["max"], entry["raw"]["frame_delta_m"]["p95"]
        )
        self.assertGreater(entry["raw"]["frame_delta_deg"]["mean"], 0.0)
        self.assertGreater(entry["pixel"]["frame_delta_px"]["mean"], 0.0)
        self.assertNotIn("smoothed", entry)

    def test_report_with_smoothing_shows_jitter_reduction(self):
        write_session(self.session_path, noisy_session_frames())
        samples = self.analyzer.load_session_samples(self.session_path)
        smoother = self.analyzer.TargetPositionSmoother(
            "one_euro", one_euro_min_cutoff_hz=1.0, one_euro_beta=0.05
        )
        report = self.analyzer.build_report(samples, smoother)
        entry = report["targets"]["vst-person-7"]
        self.assertIn("smoothed", entry)
        self.assertLess(
            entry["smoothed"]["frame_delta_m"]["mean"],
            entry["raw"]["frame_delta_m"]["mean"],
        )
        self.assertGreater(entry["jitter_reduction_pct"], 30.0)
        summary = self.analyzer.format_report_summary(report)
        self.assertIn("smoothed:", summary)
        self.assertIn("reduction=", summary)

    def test_cli_writes_json_report(self):
        write_session(self.session_path, noisy_session_frames(count=20))
        report_path = Path(self.tmp.name) / "report.json"
        result = subprocess.run(
            [
                sys.executable,
                str(ANALYZER),
                "--input",
                str(self.session_path),
                "--smooth",
                "ema",
                "--output",
                str(report_path),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("target vst-person-7", result.stdout)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["type"], "proxy_targets_jitter_report")
        self.assertIn("ema", report["smoothing"])


if __name__ == "__main__":
    unittest.main()
