from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import uuid
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "evaluate_stereo_keypoint_depth.py"
TMP = ROOT / ".tmp" / "test_evaluate_stereo_keypoint_depth"


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


def keypoint_record(
    frame_id: int,
    *,
    left_px: list[float],
    right_px: list[float],
    score: float = 0.8,
    kind: str = "shoulder_midpoint",
    bbox_left_px: list[float] | None = None,
    bbox_right_px: list[float] | None = None,
) -> dict:
    return {
        "source": "vst_stereo_keypoint",
        "schema_version": 1,
        "pair_id": f"pair-{frame_id:06d}",
        "frame_id": frame_id,
        "person_id": "person-1",
        "timestamp_ms": frame_id * 10,
        "selected_anchor": {
            "kind": kind,
            "keypoints": ["left_shoulder", "right_shoulder"],
            "left_px": left_px,
            "right_px": right_px,
            "score": score,
        },
        "bbox_baseline": {
            "left_anchor_px": bbox_left_px or left_px,
            "right_anchor_px": bbox_right_px or right_px,
            "score": 0.9,
        },
    }


class StereoKeypointDepthEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp_path = TMP / uuid.uuid4().hex
        self.tmp_path.mkdir(parents=True, exist_ok=True)

    def test_evaluates_keypoint_depth_and_bbox_baseline_summary(self):
        evaluator = load_module(TOOL, "evaluate_stereo_keypoint_depth")
        records = [
            keypoint_record(
                10,
                left_px=[680, 300],
                right_px=[648, 301],
                bbox_left_px=[680, 240],
                bbox_right_px=[648, 242],
            ),
            keypoint_record(
                11,
                left_px=[682, 300],
                right_px=[650, 301],
                bbox_left_px=[681, 240],
                bbox_right_px=[649, 242],
            ),
        ]
        input_path = self.tmp_path / "keypoint_pairs.jsonl"
        out_dir = self.tmp_path / "eval"
        write_jsonl(input_path, records)

        status = evaluator.evaluate_stereo_keypoint_depth(
            input_path=input_path,
            out_dir=out_dir,
            max_vertical_error_px=20.0,
        )

        self.assertEqual(status["frames_seen"], 2)
        self.assertEqual(status["keypoint_ok_count"], 2)
        self.assertEqual(status["keypoint_rejected_count"], 0)

        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["keypoint_ok_ratio"], 1.0)
        self.assertEqual(summary["keypoint_anchor_kinds"], [{"kind": "shoulder_midpoint", "count": 2}])
        self.assertEqual(summary["keypoint_depth_m"]["count"], 2)
        self.assertEqual(summary["bbox_baseline"]["ok_count"], 2)
        self.assertEqual(summary["bbox_baseline"]["depth_m"]["count"], 2)
        self.assertIn("keypoint_drift_m", summary)
        self.assertEqual(summary["top_rejection_reasons"], [])

    def test_rejects_low_score_vertical_error_disparity_and_depth_range(self):
        evaluator = load_module(TOOL, "evaluate_stereo_keypoint_depth")
        records = [
            keypoint_record(20, left_px=[680, 300], right_px=[648, 300], score=0.2),
            keypoint_record(21, left_px=[680, 300], right_px=[648, 360], score=0.8),
            keypoint_record(22, left_px=[680, 300], right_px=[690, 300], score=0.8),
            keypoint_record(23, left_px=[680, 300], right_px=[679, 300], score=0.8),
        ]
        input_path = self.tmp_path / "rejects.jsonl"
        out_dir = self.tmp_path / "rejects_eval"
        write_jsonl(input_path, records)

        status = evaluator.evaluate_stereo_keypoint_depth(
            input_path=input_path,
            out_dir=out_dir,
            min_keypoint_score=0.5,
            max_vertical_error_px=20.0,
            max_depth_m=2.0,
        )

        self.assertEqual(status["keypoint_ok_count"], 0)
        self.assertEqual(status["keypoint_rejected_count"], 4)
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(
            summary["top_rejection_reasons"],
            [
                {"reason": "low_keypoint_score", "count": 1},
                {"reason": "vertical_error_too_large", "count": 1},
                {"reason": "non_positive_disparity", "count": 1},
                {"reason": "depth_out_of_range", "count": 1},
            ],
        )

    def test_anchor_kind_gate_can_fallback_to_bbox_top_center(self):
        evaluator = load_module(TOOL, "evaluate_stereo_keypoint_depth")
        record = keypoint_record(
            25,
            left_px=[680, 300],
            right_px=[648, 360],
            kind="mixed",
            bbox_left_px=[680, 240],
            bbox_right_px=[648, 242],
        )
        input_path = self.tmp_path / "anchor_gate.jsonl"
        out_dir = self.tmp_path / "anchor_gate_eval"
        write_jsonl(input_path, [record])

        status = evaluator.evaluate_stereo_keypoint_depth(
            input_path=input_path,
            out_dir=out_dir,
            max_vertical_error_px=20.0,
            require_anchor_kind="shoulder_midpoint",
            anchor_mismatch_policy="fallback_bbox",
        )

        self.assertEqual(status["keypoint_ok_count"], 1)
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["keypoint_anchor_kinds"], [{"kind": "bbox_top_center_fallback", "count": 1}])
        self.assertEqual(summary["top_rejection_reasons"], [])

        per_frame = json.loads((out_dir / "per_frame.jsonl").read_text(encoding="utf-8").strip())
        self.assertEqual(per_frame["selected_anchor"]["kind"], "bbox_top_center_fallback")
        self.assertEqual(per_frame["keypoint"]["anchor_consistency_gate"]["actual_kind"], "mixed")
        self.assertEqual(per_frame["keypoint"]["anchor_consistency_gate"]["policy"], "fallback_bbox")

    def test_cli_accepts_input_and_output_paths(self):
        records = [keypoint_record(30, left_px=[680, 300], right_px=[648, 301])]
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
        self.assertEqual(status["keypoint_ok_count"], 1)
        self.assertTrue((out_dir / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
