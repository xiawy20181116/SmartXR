from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "evaluate_stereo_multitarget_depth.py"
TMP = ROOT / ".tmp" / "test_evaluate_stereo_multitarget_depth"


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


def bbox_pair_record(frame_id: int) -> dict:
    return {
        "pair_id": f"pair-{frame_id:06d}",
        "frame_id": frame_id,
        "left": {
            "people": [
                {"track_id": 10, "bbox": [260, 140, 340, 260], "confidence": 0.82},
                {"track_id": 11, "bbox": [430, 260, 570, 430], "confidence": 0.90},
            ]
        },
        "right": {
            "people": [
                {"track_id": 20, "bbox": [252, 141, 332, 261], "confidence": 0.80},
                {"track_id": 21, "bbox": [409, 261, 549, 431], "confidence": 0.88},
            ]
        },
        "left_bbox_xyxy": [430, 260, 570, 430],
        "right_bbox_xyxy": [409, 261, 549, 431],
        "confidence": 0.88,
    }


def keypoint_pair_record(frame_id: int) -> dict:
    return {
        "pair_id": f"pair-{frame_id:06d}",
        "frame_id": frame_id,
        "person_id": "person-1",
        "selected_anchor": {
            "kind": "shoulder_midpoint",
            "keypoints": ["left_shoulder", "right_shoulder"],
            "left_px": [300, 190],
            "right_px": [292, 191],
            "score": 0.81,
        },
        "left_bbox_xyxy": [430, 260, 570, 430],
        "right_bbox_xyxy": [409, 261, 549, 431],
        "bbox_baseline": {
            "left_anchor_px": [500, 260],
            "right_anchor_px": [479, 261],
            "score": 0.88,
        },
    }


class StereoMultitargetDepthEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp_path = TMP / uuid.uuid4().hex
        self.tmp_path.mkdir(parents=True, exist_ok=True)

    def test_summarizes_near_and_far_bbox_targets(self):
        evaluator = load_module(TOOL, "evaluate_stereo_multitarget_depth")
        input_path = self.tmp_path / "bbox.jsonl"
        out_dir = self.tmp_path / "eval"
        write_jsonl(input_path, [bbox_pair_record(1), bbox_pair_record(2)])

        status = evaluator.evaluate_stereo_multitarget_depth(
            bbox_input_path=input_path,
            keypoint_input_path=None,
            out_dir=out_dir,
            max_vertical_error_px=20.0,
        )

        self.assertEqual(status["frames_seen"], 2)
        self.assertEqual(status["bbox_candidate_count"], 4)
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["targets"]["rank_1_near"]["bbox"]["ok_count"], 2)
        self.assertEqual(summary["targets"]["rank_2_far"]["bbox"]["ok_count"], 2)
        self.assertLess(
            summary["targets"]["rank_1_near"]["bbox"]["depth_m"]["median"],
            summary["targets"]["rank_2_far"]["bbox"]["depth_m"]["median"],
        )

    def test_associates_keypoint_to_matching_target_and_reports_mismatch(self):
        evaluator = load_module(TOOL, "evaluate_stereo_multitarget_depth")
        bbox_path = self.tmp_path / "bbox.jsonl"
        keypoint_path = self.tmp_path / "keypoint.jsonl"
        out_dir = self.tmp_path / "eval"
        write_jsonl(bbox_path, [bbox_pair_record(1)])
        write_jsonl(keypoint_path, [keypoint_pair_record(1)])

        evaluator.evaluate_stereo_multitarget_depth(
            bbox_input_path=bbox_path,
            keypoint_input_path=keypoint_path,
            out_dir=out_dir,
            max_vertical_error_px=20.0,
        )

        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["keypoint_association"]["associated_count"], 1)
        self.assertEqual(summary["keypoint_association"]["bbox_target_mismatch_count"], 1)
        self.assertEqual(summary["targets"]["rank_2_far"]["keypoint"]["ok_count"], 1)
        self.assertEqual(summary["targets"]["rank_1_near"]["keypoint"]["ok_count"], 0)

    def test_does_not_force_distant_keypoint_onto_only_bbox_candidate(self):
        evaluator = load_module(TOOL, "evaluate_stereo_multitarget_depth")
        bbox_path = self.tmp_path / "bbox.jsonl"
        keypoint_path = self.tmp_path / "keypoint.jsonl"
        out_dir = self.tmp_path / "eval"
        source = bbox_pair_record(1)
        source["left"]["people"] = [source["left"]["people"][1]]
        source["right"]["people"] = [source["right"]["people"][1]]
        write_jsonl(bbox_path, [source])
        write_jsonl(keypoint_path, [keypoint_pair_record(1)])

        evaluator.evaluate_stereo_multitarget_depth(
            bbox_input_path=bbox_path,
            keypoint_input_path=keypoint_path,
            out_dir=out_dir,
            max_vertical_error_px=20.0,
            max_association_distance_px=120.0,
        )

        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["keypoint_association"]["associated_count"], 0)
        self.assertEqual(summary["keypoint_association"]["unassociated_count"], 1)
        self.assertEqual(summary["targets"]["rank_1_near"]["keypoint"]["ok_count"], 0)

    def test_cli_accepts_bbox_and_keypoint_inputs(self):
        bbox_path = self.tmp_path / "bbox.jsonl"
        keypoint_path = self.tmp_path / "keypoint.jsonl"
        out_dir = self.tmp_path / "out"
        write_jsonl(bbox_path, [bbox_pair_record(1)])
        write_jsonl(keypoint_path, [keypoint_pair_record(1)])

        completed = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--bbox-input",
                str(bbox_path),
                "--keypoint-input",
                str(keypoint_path),
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
        self.assertEqual(status["frames_seen"], 1)
        self.assertTrue((out_dir / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
