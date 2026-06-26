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


def selected_bbox_outside_multitarget_match_record(frame_id: int) -> dict:
    return {
        "pair_id": f"pair-{frame_id:06d}",
        "frame_id": frame_id,
        "left_bbox_xyxy": [443, 151, 587, 369],
        "right_bbox_xyxy": [416, 205, 583, 521],
        "left": {
            "people": [
                {"track_id": 10, "bbox": [443, 151, 587, 369], "confidence": 0.72},
            ]
        },
        "right": {
            "people": [
                {"track_id": 20, "bbox": [416, 205, 583, 521], "confidence": 0.68},
            ]
        },
        "confidence": 0.68,
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


def target_keypoint_pair_record(frame_id: int, target_label: str, left_px: list[float], right_px: list[float]) -> dict:
    return {
        "pair_id": f"pair-{frame_id:06d}:{target_label}",
        "source_pair_id": f"pair-{frame_id:06d}",
        "frame_id": frame_id,
        "person_id": f"{target_label}-person",
        "target_label": target_label,
        "selected_anchor": {
            "kind": "shoulder_midpoint",
            "keypoints": ["left_shoulder", "right_shoulder"],
            "left_px": left_px,
            "right_px": right_px,
            "score": 0.81,
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
        self.assertEqual(summary["input_frames"], 2)
        self.assertEqual(summary["matched_candidate_count"], 4)
        self.assertEqual(summary["frames_with_candidate"], 2)
        self.assertEqual(summary["target_coverage_ratio"], 1.0)

    def test_selected_bbox_fallback_counts_as_candidate_coverage(self):
        evaluator = load_module(TOOL, "evaluate_stereo_multitarget_depth")
        input_path = self.tmp_path / "bbox.jsonl"
        out_dir = self.tmp_path / "eval"
        write_jsonl(input_path, [selected_bbox_outside_multitarget_match_record(1)])

        evaluator.evaluate_stereo_multitarget_depth(
            bbox_input_path=input_path,
            keypoint_input_path=None,
            out_dir=out_dir,
            max_vertical_error_px=None,
            max_center_y_delta_px=80.0,
        )

        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["input_frames"], 1)
        self.assertEqual(summary["matched_candidate_count"], 1)
        self.assertEqual(summary["frames_with_candidate"], 1)
        self.assertEqual(summary["target_coverage_ratio"], 1.0)
        self.assertEqual(summary["targets"]["rank_1_near"]["bbox"]["ok_count"], 1)

        per_frame = json.loads((out_dir / "per_frame.jsonl").read_text(encoding="utf-8").strip())
        self.assertEqual(per_frame["bbox_candidates"][0]["candidate_source"], "selected_bbox_fallback")

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

    def test_summarizes_multitarget_keypoints_by_source_pair_and_target_label(self):
        evaluator = load_module(TOOL, "evaluate_stereo_multitarget_depth")
        bbox_path = self.tmp_path / "bbox.jsonl"
        keypoint_path = self.tmp_path / "keypoint.jsonl"
        out_dir = self.tmp_path / "eval"
        write_jsonl(bbox_path, [bbox_pair_record(1)])
        write_jsonl(
            keypoint_path,
            [
                target_keypoint_pair_record(1, "rank_1_near", [500, 330], [479, 331]),
                target_keypoint_pair_record(1, "rank_2_far", [300, 190], [292, 191]),
            ],
        )

        evaluator.evaluate_stereo_multitarget_depth(
            bbox_input_path=bbox_path,
            keypoint_input_path=keypoint_path,
            out_dir=out_dir,
            max_vertical_error_px=20.0,
        )

        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["keypoint_association"]["input_count"], 2)
        self.assertEqual(summary["keypoint_association"]["associated_count"], 2)
        self.assertEqual(summary["keypoint_association"]["bbox_target_mismatch_count"], 0)
        self.assertEqual(summary["targets"]["rank_1_near"]["keypoint"]["ok_count"], 1)
        self.assertEqual(summary["targets"]["rank_2_far"]["keypoint"]["ok_count"], 1)

    def test_anchor_kind_gate_fallback_is_used_for_keypoint_metric(self):
        evaluator = load_module(TOOL, "evaluate_stereo_multitarget_depth")
        bbox_path = self.tmp_path / "bbox.jsonl"
        keypoint_path = self.tmp_path / "keypoint.jsonl"
        out_dir = self.tmp_path / "eval"
        keypoint = keypoint_pair_record(1)
        keypoint["selected_anchor"]["kind"] = "mixed"
        keypoint["selected_anchor"]["left_px"] = [500, 260]
        keypoint["selected_anchor"]["right_px"] = [479, 340]
        write_jsonl(bbox_path, [bbox_pair_record(1)])
        write_jsonl(keypoint_path, [keypoint])

        evaluator.evaluate_stereo_multitarget_depth(
            bbox_input_path=bbox_path,
            keypoint_input_path=keypoint_path,
            out_dir=out_dir,
            max_vertical_error_px=20.0,
            require_anchor_kind="shoulder_midpoint",
            anchor_mismatch_policy="fallback_bbox",
        )

        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["targets"]["rank_1_near"]["keypoint"]["ok_count"], 1)
        self.assertEqual(summary["targets"]["rank_1_near"]["keypoint"]["top_rejection_reasons"], [])

        per_frame = json.loads((out_dir / "per_frame.jsonl").read_text(encoding="utf-8").strip())
        self.assertEqual(per_frame["keypoint"]["anchor_consistency_gate"]["policy"], "fallback_bbox")

    def test_exports_top_rejected_anchor_diagnostics(self):
        evaluator = load_module(TOOL, "evaluate_stereo_multitarget_depth")
        bbox_path = self.tmp_path / "bbox.jsonl"
        keypoint_path = self.tmp_path / "keypoint.jsonl"
        out_dir = self.tmp_path / "eval"
        mismatch = target_keypoint_pair_record(1, "rank_1_near", [500, 330], [479, 331])
        mismatch["selected_anchor"].update(
            {
                "kind": "mixed",
                "left_kind": "shoulder_midpoint",
                "right_kind": "nose",
                "left_keypoints": ["left_shoulder", "right_shoulder"],
                "right_keypoints": ["nose"],
                "left_score": 0.81,
                "right_score": 0.72,
            }
        )
        vertical = target_keypoint_pair_record(2, "rank_1_near", [500, 330], [479, 380])
        vertical["selected_anchor"].update(
            {
                "left_kind": "shoulder_midpoint",
                "right_kind": "shoulder_midpoint",
                "left_keypoints": ["left_shoulder", "right_shoulder"],
                "right_keypoints": ["left_shoulder", "right_shoulder"],
                "left_score": 0.81,
                "right_score": 0.79,
            }
        )
        write_jsonl(bbox_path, [bbox_pair_record(1), bbox_pair_record(2)])
        write_jsonl(keypoint_path, [mismatch, vertical])

        status = evaluator.evaluate_stereo_multitarget_depth(
            bbox_input_path=bbox_path,
            keypoint_input_path=keypoint_path,
            out_dir=out_dir,
            max_vertical_error_px=20.0,
            require_anchor_kind="shoulder_midpoint",
            anchor_mismatch_policy="reject",
            diagnostic_reasons=["anchor_kind_mismatch", "vertical_error_too_large"],
            diagnostic_top_n=5,
        )

        self.assertIn("diagnostics_jsonl", status)
        mismatch_samples = [
            json.loads(line)
            for line in (out_dir / "diagnostics" / "anchor_kind_mismatch_top.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        vertical_samples = [
            json.loads(line)
            for line in (out_dir / "diagnostics" / "vertical_error_too_large_top.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual(mismatch_samples[0]["frame_id"], 1)
        self.assertEqual(mismatch_samples[0]["target_label"], "rank_1_near")
        self.assertEqual(mismatch_samples[0]["left_anchor_kind"], "shoulder_midpoint")
        self.assertEqual(mismatch_samples[0]["right_anchor_kind"], "nose")
        self.assertEqual(mismatch_samples[0]["candidate_source"], "matched_bbox")
        self.assertEqual(mismatch_samples[0]["bbox"]["left_xyxy"], [430.0, 260.0, 570.0, 430.0])
        self.assertEqual(mismatch_samples[0]["selected_keypoints"]["right"], ["nose"])
        self.assertEqual(mismatch_samples[0]["scores"]["right"], 0.72)
        self.assertEqual(vertical_samples[0]["frame_id"], 2)
        self.assertEqual(vertical_samples[0]["vertical_error_px"], -50.0)

        per_frames = [
            json.loads(line)
            for line in (out_dir / "per_frame.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            per_frames[0]["keypoint"]["diagnostic"]["rejection_reason"],
            "anchor_kind_mismatch",
        )

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
