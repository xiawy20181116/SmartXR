from __future__ import annotations

import importlib.util
import json
import uuid
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "collect_stereo_keypoint_pairs.py"
TMP = ROOT / ".tmp" / "test_collect_stereo_keypoint_pairs"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class StereoKeypointPairCollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp_path = TMP / uuid.uuid4().hex
        self.tmp_path.mkdir(parents=True, exist_ok=True)

    def test_selects_shoulder_midpoint_then_fallbacks(self):
        collector = load_module(TOOL, "collect_stereo_keypoint_pairs")
        bbox = [640, 240, 720, 520]

        shoulder_anchor = collector.select_anchor(
            {
                "left_shoulder": {"xy": [650, 300], "score": 0.9},
                "right_shoulder": {"xy": [690, 300], "score": 0.8},
                "nose": {"xy": [670, 260], "score": 0.7},
            },
            bbox_xyxy=bbox,
            min_score=0.5,
        )
        self.assertEqual(shoulder_anchor["kind"], "shoulder_midpoint")
        self.assertEqual(shoulder_anchor["keypoints"], ["left_shoulder", "right_shoulder"])
        self.assertEqual(shoulder_anchor["xy"], [670.0, 300.0])
        self.assertAlmostEqual(shoulder_anchor["score"], 0.8)

        nose_anchor = collector.select_anchor(
            {
                "left_shoulder": {"xy": [650, 300], "score": 0.3},
                "right_shoulder": {"xy": [690, 300], "score": 0.2},
                "nose": {"xy": [671, 261], "score": 0.7},
            },
            bbox_xyxy=bbox,
            min_score=0.5,
        )
        self.assertEqual(nose_anchor["kind"], "nose")
        self.assertEqual(nose_anchor["xy"], [671.0, 261.0])

        ear_anchor = collector.select_anchor(
            {
                "left_ear": {"xy": [650, 260], "score": 0.7},
                "right_ear": {"xy": [690, 260], "score": 0.8},
            },
            bbox_xyxy=bbox,
            min_score=0.5,
        )
        self.assertEqual(ear_anchor["kind"], "ear_midpoint")
        self.assertEqual(ear_anchor["xy"], [670.0, 260.0])

        fallback_anchor = collector.select_anchor({}, bbox_xyxy=bbox, min_score=0.5)
        self.assertEqual(fallback_anchor["kind"], "bbox_top_center")
        self.assertEqual(fallback_anchor["xy"], [680.0, 240.0])

    def test_builds_pair_record_with_selected_anchor_and_bbox_baseline(self):
        collector = load_module(TOOL, "collect_stereo_keypoint_pairs")
        bbox_pair = {
            "frame_id": 77,
            "pair_id": "pair-000077",
            "person_id": "person-1-1",
            "timestamp_ms": 123456,
            "left_bbox_xyxy": [640, 240, 720, 520],
            "right_bbox_xyxy": [608, 242, 688, 522],
            "confidence": 0.91,
        }

        record = collector.build_stereo_keypoint_pair_record(
            frame_id=77,
            timestamp_ms=123456,
            left_keypoints={
                "left_shoulder": {"xy": [650, 300], "score": 0.9},
                "right_shoulder": {"xy": [690, 300], "score": 0.8},
            },
            right_keypoints={
                "left_shoulder": {"xy": [618, 301], "score": 0.85},
                "right_shoulder": {"xy": [658, 301], "score": 0.82},
            },
            bbox_pair=bbox_pair,
            min_score=0.5,
        )

        self.assertEqual(record["source"], "vst_stereo_keypoint")
        self.assertEqual(record["frame_id"], 77)
        self.assertEqual(record["selected_anchor"]["kind"], "shoulder_midpoint")
        self.assertEqual(record["selected_anchor"]["left_px"], [670.0, 300.0])
        self.assertEqual(record["selected_anchor"]["right_px"], [638.0, 301.0])
        self.assertAlmostEqual(record["selected_anchor"]["score"], 0.8)
        self.assertEqual(record["bbox_baseline"]["left_anchor_px"], [680.0, 240.0])
        self.assertEqual(record["bbox_baseline"]["right_anchor_px"], [648.0, 242.0])
        self.assertEqual(record["left_bbox_xyxy"], bbox_pair["left_bbox_xyxy"])

    def test_selects_pose_matching_bbox_target_over_highest_score_pose(self):
        collector = load_module(TOOL, "collect_stereo_keypoint_pairs")
        person_far = [[100.0, 90.0] for _ in range(17)]
        person_target = [[500.0, 350.0] for _ in range(17)]
        person_target[5] = [430.0, 300.0]
        person_target[6] = [530.0, 300.0]

        keypoints, association = collector._normalize_pose_output_for_bbox(
            [person_far, person_target],
            [[0.95] * 17, [0.65] * 17],
            target_bbox_xyxy=[400.0, 240.0, 560.0, 430.0],
            association_margin_px=8.0,
            max_association_distance_px=120.0,
        )

        self.assertEqual(keypoints["left_shoulder"]["xy"], [430.0, 300.0])
        self.assertEqual(keypoints["right_shoulder"]["xy"], [530.0, 300.0])
        self.assertEqual(association["status"], "matched")
        self.assertEqual(association["selected_person_index"], 1)
        self.assertGreater(association["inside_keypoint_count"], 0)

    def test_unmatched_bbox_target_does_not_fall_back_to_wrong_pose(self):
        collector = load_module(TOOL, "collect_stereo_keypoint_pairs")
        keypoints, association = collector._normalize_pose_output_for_bbox(
            [[[100.0, 90.0] for _ in range(17)]],
            [[0.95] * 17],
            target_bbox_xyxy=[400.0, 240.0, 560.0, 430.0],
            association_margin_px=8.0,
            max_association_distance_px=120.0,
        )

        self.assertEqual(keypoints, {})
        self.assertEqual(association["status"], "unassociated")

    def test_writes_jsonl_from_in_memory_records(self):
        collector = load_module(TOOL, "collect_stereo_keypoint_pairs")
        out_path = self.tmp_path / "keypoint_pairs.jsonl"
        records = [
            {
                "frame_id": 1,
                "timestamp_ms": 10,
                "left_keypoints": {"nose": {"xy": [680, 240], "score": 0.8}},
                "right_keypoints": {"nose": {"xy": [648, 241], "score": 0.7}},
                "bbox_pair": {
                    "left_bbox_xyxy": [640, 220, 720, 520],
                    "right_bbox_xyxy": [608, 222, 688, 522],
                    "confidence": 0.9,
                },
            }
        ]

        status = collector.write_stereo_keypoint_pair_records(
            records=records,
            out_path=out_path,
            min_score=0.5,
        )

        self.assertEqual(status["pair_count"], 1)
        payload = json.loads(out_path.read_text(encoding="utf-8").strip())
        self.assertEqual(payload["selected_anchor"]["kind"], "nose")

    def test_selected_anchor_preserves_per_eye_anchor_details(self):
        collector = load_module(TOOL, "collect_stereo_keypoint_pairs")

        record = collector.build_stereo_keypoint_pair_record(
            frame_id=40,
            timestamp_ms=400,
            left_keypoints={
                "left_shoulder": {"xy": [100, 200], "score": 0.9},
                "right_shoulder": {"xy": [120, 204], "score": 0.8},
            },
            right_keypoints={
                "nose": {"xy": [98, 190], "score": 0.7},
            },
            bbox_pair={
                "pair_id": "pair-000040:rank_1_near",
                "person_id": "target",
                "left_bbox_xyxy": [80, 160, 140, 260],
                "right_bbox_xyxy": [78, 160, 138, 260],
                "confidence": 0.95,
            },
            min_score=0.5,
        )

        anchor = record["selected_anchor"]
        self.assertEqual(anchor["kind"], "mixed")
        self.assertEqual(anchor["left_kind"], "shoulder_midpoint")
        self.assertEqual(anchor["right_kind"], "nose")
        self.assertEqual(anchor["left_keypoints"], ["left_shoulder", "right_shoulder"])
        self.assertEqual(anchor["right_keypoints"], ["nose"])
        self.assertEqual(anchor["left_score"], 0.8)
        self.assertEqual(anchor["right_score"], 0.7)


if __name__ == "__main__":
    unittest.main()
