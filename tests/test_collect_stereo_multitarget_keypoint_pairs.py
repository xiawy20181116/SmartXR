from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "collect_stereo_multitarget_keypoint_pairs.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def bbox_record() -> dict:
    return {
        "pair_id": "pair-000001",
        "frame_id": 1,
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
        "confidence": 0.88,
    }


def pose_at(x: float, y: float) -> list[list[float]]:
    pose = [[x, y] for _ in range(17)]
    pose[5] = [x - 20.0, y]
    pose[6] = [x + 20.0, y]
    return pose


class StereoMultitargetKeypointCollectorTests(unittest.TestCase):
    def test_builds_one_keypoint_record_per_ranked_bbox_candidate(self):
        collector = load_module(TOOL, "collect_stereo_multitarget_keypoint_pairs")
        records = collector.build_multitarget_keypoint_records_for_bbox_record(
            bbox_record(),
            left_keypoints=[pose_at(300, 190), pose_at(500, 330)],
            left_scores=[[0.8] * 17, [0.9] * 17],
            right_keypoints=[pose_at(292, 191), pose_at(479, 331)],
            right_scores=[[0.78] * 17, [0.88] * 17],
            timestamp_ms=123,
            min_score=0.5,
            recorded_width=880,
            recorded_height=660,
            max_center_y_delta_px=80.0,
            pose_association_margin_px=8.0,
            max_pose_association_distance_px=120.0,
        )

        self.assertEqual([record["target_label"] for record in records], ["rank_1_near", "rank_2_far"])
        self.assertEqual([record["bbox_rank"] for record in records], [1, 2])
        self.assertEqual(records[0]["source_pair_id"], "pair-000001")
        self.assertEqual(records[0]["pair_id"], "pair-000001:rank_1_near")
        self.assertEqual(records[1]["pair_id"], "pair-000001:rank_2_far")
        self.assertEqual(records[0]["selected_anchor"]["kind"], "shoulder_midpoint")
        self.assertEqual(records[1]["pose_association"]["left"]["status"], "matched")


if __name__ == "__main__":
    unittest.main()
