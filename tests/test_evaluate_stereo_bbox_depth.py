from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import uuid
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "evaluate_stereo_bbox_depth.py"
TMP = ROOT / ".tmp" / "test_evaluate_stereo_bbox_depth"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )


class StereoBboxDepthEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp_path = TMP / uuid.uuid4().hex
        self.tmp_path.mkdir(parents=True, exist_ok=True)

    def test_evaluates_jsonl_and_writes_per_frame_summary(self):
        evaluator = load_module(TOOL, "evaluate_stereo_bbox_depth")
        records = [
            {
                "frame_id": 10,
                "person_id": "person-1",
                "left_bbox_xyxy": [640, 240, 720, 520],
                "right_bbox_xyxy": [608, 250, 688, 530],
                "confidence": 0.91,
            },
            {
                "frame_id": 11,
                "person_id": "person-1",
                "left_bbox_xyxy": [644, 240, 724, 520],
                "right_bbox_xyxy": [612, 250, 692, 530],
                "confidence": 0.93,
            },
            {
                "frame_id": 12,
                "person_id": "person-1",
                "left_bbox_xyxy": [640, 240, 720, 520],
                "right_bbox_xyxy": [608, 280, 688, 560],
                "confidence": 0.92,
            },
        ]

        input_path = self.tmp_path / "stereo_input.jsonl"
        out_dir = self.tmp_path / "eval"
        write_jsonl(input_path, records)

        status = evaluator.evaluate_stereo_bbox_depth(
            input_path=input_path,
            out_dir=out_dir,
            max_vertical_error_px=20.0,
        )

        self.assertEqual(status["frames_seen"], 3)
        self.assertEqual(status["stereo_ok_count"], 2)
        self.assertEqual(status["stereo_rejected_count"], 1)
        self.assertEqual(status["summary_json"], str(out_dir / "summary.json"))
        self.assertEqual(status["per_frame_jsonl"], str(out_dir / "per_frame.jsonl"))

        per_frame = [
            json.loads(line)
            for line in (out_dir / "per_frame.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual([record["stereo_ok"] for record in per_frame], [True, True, False])
        self.assertEqual(per_frame[2]["rejection_reason"], "vertical_error_too_large")
        self.assertNotIn("depth_m", per_frame[2])

        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["frames_seen"], 3)
        self.assertAlmostEqual(summary["stereo_ok_ratio"], 2 / 3)
        self.assertEqual(summary["depth_m"]["count"], 2)
        self.assertAlmostEqual(summary["depth_m"]["median"], 0.8706375)
        self.assertAlmostEqual(summary["depth_m"]["p10"], 0.8706375)
        self.assertAlmostEqual(summary["depth_m"]["p90"], 0.8706375)
        self.assertGreater(summary["position_drift_m"], 0.0)
        self.assertEqual(
            summary["top_rejection_reasons"],
            [{"reason": "vertical_error_too_large", "count": 1}],
        )

    def test_cli_accepts_input_and_output_paths(self):
        records = [
            {
                "frame_id": 20,
                "left_bbox_xyxy": [640, 240, 720, 520],
                "right_bbox_xyxy": [608, 240, 688, 520],
                "confidence": 0.91,
            }
        ]

        input_path = self.tmp_path / "input.jsonl"
        out_dir = self.tmp_path / "out"
        write_jsonl(input_path, records)

        completed = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--input",
                str(input_path),
                "--out-dir",
                str(out_dir),
                "--max-vertical-error-px",
                "20",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )

        status = json.loads(completed.stdout)
        self.assertEqual(status["stereo_ok_count"], 1)
        self.assertTrue((out_dir / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
