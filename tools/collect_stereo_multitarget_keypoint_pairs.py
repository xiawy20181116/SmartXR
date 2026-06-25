from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
_ROOT = TOOLS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from collect_stereo_bbox_pairs import nv12_frame_to_bgr  # noqa: E402
from collect_stereo_keypoint_pairs import (  # noqa: E402
    _create_rtmlib_estimator,
    _iter_jsonl,
    _normalize_pose_output_for_bbox,
    build_stereo_keypoint_pair_record,
)
from evaluate_stereo_multitarget_depth import (  # noqa: E402
    _candidate_pair,
    _match_bbox_candidates,
    _target_label,
)
from smartxr.nv12_reader import read_packet_file  # noqa: E402
from smartxr.stereo_depth import (  # noqa: E402
    ANCHOR_KIND_BBOX_TOP_CENTER,
    SCENE_STEREO_28,
    StereoGateConfig,
    triangulate_detection_pair,
)
from smartxr.stereo_package import load_stereo_package  # noqa: E402


def _load_bbox_records(path: Path) -> dict[int, dict[str, Any]]:
    return {int(record["frame_id"]): record for record in _iter_jsonl(path)}


def _rank_bbox_candidates(
    bbox_record: dict[str, Any],
    *,
    recorded_width: int,
    recorded_height: int,
    max_center_y_delta_px: float,
    min_confidence: float,
    min_depth_m: float,
    max_depth_m: float,
    min_box_ratio: float,
    max_box_ratio: float,
    max_vertical_error_px: float | None,
) -> list[dict[str, Any]]:
    calibration = SCENE_STEREO_28.scaled_to(recorded_width, recorded_height)
    gate_config = StereoGateConfig(
        min_confidence=min_confidence,
        min_depth_m=min_depth_m,
        max_depth_m=max_depth_m,
        min_box_ratio=min_box_ratio,
        max_box_ratio=max_box_ratio,
        max_vertical_error_px=max_vertical_error_px,
        gate_box_height_ratio=False,
    )
    candidates: list[dict[str, Any]] = []
    for left_det, right_det, left_bbox, right_bbox in _match_bbox_candidates(
        bbox_record,
        max_center_y_delta_px=max_center_y_delta_px,
    ):
        pair = _candidate_pair(bbox_record, 1, left_det, right_det, left_bbox, right_bbox)
        evaluated = triangulate_detection_pair(
            pair,
            calibration,
            anchor_kind=ANCHOR_KIND_BBOX_TOP_CENTER,
            gate_config=gate_config,
        )
        evaluated["left_bbox_xyxy"] = list(left_bbox)
        evaluated["right_bbox_xyxy"] = list(right_bbox)
        candidates.append(evaluated)

    ranked = sorted(
        [candidate for candidate in candidates if candidate.get("stereo_ok") is True],
        key=lambda candidate: float(candidate["depth_m"]),
    )
    for rank_index, candidate in enumerate(ranked, start=1):
        candidate["bbox_rank"] = rank_index
        candidate["target_label"] = _target_label(rank_index, len(ranked))
    return ranked


def _association_reason(left_association: dict[str, Any], right_association: dict[str, Any]) -> str:
    return f"left_{left_association.get('status', 'unknown')}_right_{right_association.get('status', 'unknown')}"


def build_multitarget_keypoint_records_for_bbox_record(
    bbox_record: dict[str, Any],
    *,
    left_keypoints: Any,
    left_scores: Any,
    right_keypoints: Any,
    right_scores: Any,
    timestamp_ms: int,
    min_score: float,
    recorded_width: int = 1164,
    recorded_height: int = 872,
    max_center_y_delta_px: float = 80.0,
    pose_association_margin_px: float = 8.0,
    max_pose_association_distance_px: float = 120.0,
    min_confidence: float = 0.4,
    min_depth_m: float = 0.2,
    max_depth_m: float = 5.0,
    min_box_ratio: float = 0.5,
    max_box_ratio: float = 2.0,
    max_vertical_error_px: float | None = None,
) -> list[dict[str, Any]]:
    source_pair_id = str(bbox_record.get("pair_id", f"pair-{int(bbox_record['frame_id']):06d}"))
    records: list[dict[str, Any]] = []
    for candidate in _rank_bbox_candidates(
        bbox_record,
        recorded_width=recorded_width,
        recorded_height=recorded_height,
        max_center_y_delta_px=max_center_y_delta_px,
        min_confidence=min_confidence,
        min_depth_m=min_depth_m,
        max_depth_m=max_depth_m,
        min_box_ratio=min_box_ratio,
        max_box_ratio=max_box_ratio,
        max_vertical_error_px=max_vertical_error_px,
    ):
        target_label = str(candidate["target_label"])
        left_normalized, left_association = _normalize_pose_output_for_bbox(
            left_keypoints,
            left_scores,
            target_bbox_xyxy=candidate["left_bbox_xyxy"],
            association_margin_px=pose_association_margin_px,
            max_association_distance_px=max_pose_association_distance_px,
        )
        right_normalized, right_association = _normalize_pose_output_for_bbox(
            right_keypoints,
            right_scores,
            target_bbox_xyxy=candidate["right_bbox_xyxy"],
            association_margin_px=pose_association_margin_px,
            max_association_distance_px=max_pose_association_distance_px,
        )
        bbox_pair = {
            "pair_id": f"{source_pair_id}:{target_label}",
            "frame_id": int(bbox_record["frame_id"]),
            "person_id": str(candidate.get("person_id", target_label)),
            "left_bbox_xyxy": candidate["left_bbox_xyxy"],
            "right_bbox_xyxy": candidate["right_bbox_xyxy"],
            "confidence": float(candidate.get("confidence", bbox_record.get("confidence", 1.0))),
        }
        record = build_stereo_keypoint_pair_record(
            frame_id=int(bbox_record["frame_id"]),
            timestamp_ms=timestamp_ms,
            left_keypoints=left_normalized,
            right_keypoints=right_normalized,
            bbox_pair=bbox_pair,
            min_score=min_score,
            left_pose_association=left_association,
            right_pose_association=right_association,
        )
        record["source"] = "vst_stereo_multitarget_keypoint"
        record["source_pair_id"] = source_pair_id
        record["target_label"] = target_label
        record["bbox_rank"] = int(candidate["bbox_rank"])
        record["bbox_depth_m"] = float(candidate["depth_m"])
        record["association_reason"] = _association_reason(left_association, right_association)
        records.append(record)
    return records


def build_multitarget_keypoint_pairs_from_package(
    *,
    package_dir: Path,
    bbox_pairs_input: Path,
    pose_estimator: Callable[[Any], tuple[Any, Any]],
    out_path: Path,
    frame_decoder: Callable[[Any], Any] | None = None,
    min_score: float = 0.5,
    recorded_width: int = 1164,
    recorded_height: int = 872,
    stop_after_frames: int | None = None,
    max_center_y_delta_px: float = 80.0,
    pose_association_margin_px: float = 8.0,
    max_pose_association_distance_px: float = 120.0,
) -> dict[str, Any]:
    summary = load_stereo_package(package_dir)
    bbox_records = _load_bbox_records(bbox_pairs_input)
    if frame_decoder is None:
        frame_decoder = nv12_frame_to_bgr

    frame_count = 0
    record_count = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for pair in summary.pairs:
            bbox_record = bbox_records.get(pair.frame_id)
            if bbox_record is None:
                continue
            left_frame = frame_decoder(read_packet_file(pair.left.path, index=pair.left.index))
            right_frame = frame_decoder(read_packet_file(pair.right.path, index=pair.right.index))
            left_keypoints, left_scores = pose_estimator(left_frame)
            right_keypoints, right_scores = pose_estimator(right_frame)
            records = build_multitarget_keypoint_records_for_bbox_record(
                bbox_record,
                left_keypoints=left_keypoints,
                left_scores=left_scores,
                right_keypoints=right_keypoints,
                right_scores=right_scores,
                timestamp_ms=min(pair.left.timestamp_us, pair.right.timestamp_us) // 1000,
                min_score=min_score,
                recorded_width=recorded_width,
                recorded_height=recorded_height,
                max_center_y_delta_px=max_center_y_delta_px,
                pose_association_margin_px=pose_association_margin_px,
                max_pose_association_distance_px=max_pose_association_distance_px,
            )
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            frame_count += 1
            record_count += len(records)
            if stop_after_frames is not None and frame_count >= max(1, int(stop_after_frames)):
                break

    return {
        "source": "stereo_record_package",
        "input_package_dir": str(package_dir),
        "bbox_pairs_input": str(bbox_pairs_input),
        "output_jsonl": str(out_path),
        "package_pair_count": summary.pair_count,
        "frame_count": frame_count,
        "record_count": record_count,
        "target_observed": record_count > 0,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect one rtmlib keypoint pair per ranked stereo bbox candidate."
    )
    parser.add_argument("--input-package", required=True, type=Path)
    parser.add_argument("--bbox-pairs-input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--stop-after-frames", type=int, default=None)
    parser.add_argument("--require-target", action="store_true")
    parser.add_argument("--recorded-width", type=int, default=1164)
    parser.add_argument("--recorded-height", type=int, default=872)
    parser.add_argument("--min-keypoint-score", type=float, default=0.5)
    parser.add_argument("--pose-model", choices=["body", "wholebody"], default="body")
    parser.add_argument("--mode", default="balanced")
    parser.add_argument("--backend", default="onnxruntime")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--max-center-y-delta-px", type=float, default=80.0)
    parser.add_argument("--pose-association-margin-px", type=float, default=8.0)
    parser.add_argument("--max-pose-association-distance-px", type=float, default=120.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        pose_estimator = _create_rtmlib_estimator(args)
        status = build_multitarget_keypoint_pairs_from_package(
            package_dir=args.input_package,
            bbox_pairs_input=args.bbox_pairs_input,
            pose_estimator=pose_estimator,
            out_path=args.out,
            min_score=args.min_keypoint_score,
            recorded_width=args.recorded_width,
            recorded_height=args.recorded_height,
            stop_after_frames=args.stop_after_frames,
            max_center_y_delta_px=args.max_center_y_delta_px,
            pose_association_margin_px=args.pose_association_margin_px,
            max_pose_association_distance_px=args.max_pose_association_distance_px,
        )
    except Exception as exc:
        status = {
            "source": "stereo_record_package",
            "target_observed": False,
            "frame_count": 0,
            "record_count": 0,
            "reason": "multitarget_keypoint_collection_failed",
            "error": str(exc),
            "input_package_dir": str(args.input_package),
            "bbox_pairs_input": str(args.bbox_pairs_input),
            "output_jsonl": str(args.out.resolve()),
        }
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
        return 1
    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    if args.require_target and not status["target_observed"]:
        return 2
    return 0 if status["record_count"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
