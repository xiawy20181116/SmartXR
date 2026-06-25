from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartxr.stereo_depth import (  # noqa: E402
    ANCHOR_KIND_BBOX_TOP_CENTER,
    SCENE_STEREO_28,
    StereoDetectionPair,
    StereoGateConfig,
    triangulate_detection_pair,
)


PER_FRAME_FILE = "per_frame.jsonl"
SUMMARY_FILE = "summary.json"


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_number} must be a JSON object")
            yield payload


def _bbox_xyxy(value: Any) -> tuple[float, float, float, float]:
    if isinstance(value, dict):
        if {"x1", "y1", "x2", "y2"}.issubset(value):
            return (
                float(value["x1"]),
                float(value["y1"]),
                float(value["x2"]),
                float(value["y2"]),
            )
        if {"cx", "cy", "w", "h"}.issubset(value):
            cx = float(value["cx"])
            cy = float(value["cy"])
            half_w = float(value["w"]) * 0.5
            half_h = float(value["h"]) * 0.5
            return (cx - half_w, cy - half_h, cx + half_w, cy + half_h)
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return tuple(float(item) for item in value)  # type: ignore[return-value]
    raise ValueError(f"bbox must be xyxy list or bbox dict, got {value!r}")


def _first_detection(eye: Any) -> dict[str, Any] | None:
    if not isinstance(eye, dict):
        return None
    detections = eye.get("detections")
    if isinstance(detections, list) and detections:
        first = detections[0]
        if isinstance(first, dict):
            return first
    people = eye.get("people")
    if isinstance(people, list) and people:
        first = people[0]
        if isinstance(first, dict):
            return first
    return eye


def _record_to_pair(record: dict[str, Any], index: int) -> StereoDetectionPair:
    left_record = _first_detection(record.get("left"))
    right_record = _first_detection(record.get("right"))
    left_bbox = record.get("left_bbox_xyxy")
    right_bbox = record.get("right_bbox_xyxy")
    if left_bbox is None and left_record is not None:
        left_bbox = left_record.get("bbox")
    if right_bbox is None and right_record is not None:
        right_bbox = right_record.get("bbox")
    if left_bbox is None or right_bbox is None:
        raise ValueError(f"record {index} must contain left/right bbox values")

    confidence_values = [
        value
        for value in (
            record.get("confidence"),
            None if left_record is None else left_record.get("confidence"),
            None if right_record is None else right_record.get("confidence"),
        )
        if value is not None
    ]
    confidence = min(float(value) for value in confidence_values) if confidence_values else 1.0
    frame_id = int(record.get("frame_id", record.get("sequence", index)))
    person_id = str(record.get("person_id", record.get("track_id", "person-1")))
    pair_id = str(record.get("pair_id", f"pair-{frame_id:06d}"))
    return StereoDetectionPair(
        pair_id=pair_id,
        frame_id=frame_id,
        person_id=person_id,
        left_bbox_xyxy=_bbox_xyxy(left_bbox),
        right_bbox_xyxy=_bbox_xyxy(right_bbox),
        confidence=confidence,
    )


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((float(av) - float(bv)) ** 2 for av, bv in zip(a, b, strict=True)))


def _series_summary(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "p10": _percentile(values, 0.10),
        "median": _percentile(values, 0.50),
        "p90": _percentile(values, 0.90),
    }


def _median_position(positions: list[list[float]]) -> list[float]:
    return [
        float(_percentile([float(position[axis]) for position in positions], 0.50))
        for axis in range(3)
    ]


def _temporal_median_positions(
    positions: list[list[float]],
    *,
    window: int,
    outlier_max_delta_m: float | None,
) -> tuple[list[list[float]], int]:
    if not positions:
        return ([], 0)
    window = max(1, int(window))
    smoothed: list[list[float]] = []
    outlier_rejected_count = 0
    for index, position in enumerate(positions):
        start = max(0, index - window + 1)
        median_position = _median_position(positions[start : index + 1])
        if (
            outlier_max_delta_m is not None
            and _distance(position, median_position) > float(outlier_max_delta_m)
        ):
            outlier_rejected_count += 1
        smoothed.append(median_position)
    return (smoothed, outlier_rejected_count)


def _max_drift_from_first(positions: list[list[float]]) -> float:
    if not positions:
        return 0.0
    first_position = positions[0]
    return max(_distance(first_position, position) for position in positions)


def _summarize(
    records: list[dict[str, Any]],
    *,
    temporal_median_window: int = 1,
    temporal_outlier_max_delta_m: float | None = None,
) -> dict[str, Any]:
    frames_seen = len(records)
    ok_records = [record for record in records if record.get("stereo_ok") is True]
    rejected_records = [record for record in records if record.get("stereo_ok") is False]
    depths = [float(record["depth_m"]) for record in ok_records if "depth_m" in record]
    positions = [record["position"] for record in ok_records if "position" in record]
    rejection_counts = Counter(
        str(record.get("rejection_reason") or "unknown")
        for record in rejected_records
    )
    raw_position_drift_m = _max_drift_from_first(positions)
    smoothed_positions, outlier_rejected_count = _temporal_median_positions(
        positions,
        window=temporal_median_window,
        outlier_max_delta_m=temporal_outlier_max_delta_m,
    )
    smoothed_position_drift_m = _max_drift_from_first(smoothed_positions)
    disparity_values = [
        float(record["disparity_px"]) for record in records if "disparity_px" in record
    ]
    vertical_error_values = [
        float(record["vertical_error_px"]) for record in records if "vertical_error_px" in record
    ]
    box_width_ratio_values = [
        float(record["box_width_ratio"]) for record in records if "box_width_ratio" in record
    ]
    box_height_ratio_values = [
        float(record["box_height_ratio"]) for record in records if "box_height_ratio" in record
    ]

    return {
        "frames_seen": frames_seen,
        "stereo_ok_count": len(ok_records),
        "stereo_rejected_count": len(rejected_records),
        "stereo_ok_ratio": 0.0 if frames_seen == 0 else len(ok_records) / frames_seen,
        "depth_m": _series_summary(depths),
        "disparity_px": _series_summary(disparity_values),
        "vertical_error_px": _series_summary(vertical_error_values),
        "box_width_ratio": _series_summary(box_width_ratio_values),
        "box_height_ratio": _series_summary(box_height_ratio_values),
        "raw_position_drift_m": raw_position_drift_m,
        "smoothed_position_drift_m": smoothed_position_drift_m,
        "position_drift_m": smoothed_position_drift_m,
        "target_head_point_drift_m": smoothed_position_drift_m,
        "temporal_filter": {
            "median_window": max(1, int(temporal_median_window)),
            "outlier_max_delta_m": temporal_outlier_max_delta_m,
            "outlier_rejected_count": outlier_rejected_count,
        },
        "top_rejection_reasons": [
            {"reason": reason, "count": count}
            for reason, count in rejection_counts.most_common()
        ],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def evaluate_stereo_bbox_depth(
    *,
    input_path: Path,
    out_dir: Path,
    recorded_width: int = 1164,
    recorded_height: int = 872,
    min_confidence: float = 0.4,
    min_depth_m: float = 0.2,
    max_depth_m: float = 5.0,
    min_box_ratio: float = 0.5,
    max_box_ratio: float = 2.0,
    max_vertical_error_px: float | None = None,
    temporal_median_window: int = 1,
    temporal_outlier_max_delta_m: float | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
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
    per_frame_path = out_dir / PER_FRAME_FILE
    records: list[dict[str, Any]] = []
    with per_frame_path.open("w", encoding="utf-8", newline="\n") as handle:
        for index, record in enumerate(_iter_jsonl(input_path), start=1):
            pair = _record_to_pair(record, index)
            evaluated = triangulate_detection_pair(
                pair,
                calibration,
                anchor_kind=ANCHOR_KIND_BBOX_TOP_CENTER,
                gate_config=gate_config,
            )
            records.append(evaluated)
            handle.write(json.dumps(evaluated, ensure_ascii=False, separators=(",", ":")) + "\n")

    summary = _summarize(
        records,
        temporal_median_window=temporal_median_window,
        temporal_outlier_max_delta_m=temporal_outlier_max_delta_m,
    )
    summary_path = out_dir / SUMMARY_FILE
    _write_json(summary_path, summary)
    status = {
        "input_jsonl": str(input_path),
        "per_frame_jsonl": str(per_frame_path),
        "summary_json": str(summary_path),
        "frames_seen": summary["frames_seen"],
        "stereo_ok_count": summary["stereo_ok_count"],
        "stereo_rejected_count": summary["stereo_rejected_count"],
        "stereo_ok_ratio": summary["stereo_ok_ratio"],
    }
    return status


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate stereo bbox top-center depth stability from paired detection JSONL."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--recorded-width", type=int, default=1164)
    parser.add_argument("--recorded-height", type=int, default=872)
    parser.add_argument("--min-confidence", type=float, default=0.4)
    parser.add_argument("--min-depth-m", type=float, default=0.2)
    parser.add_argument("--max-depth-m", type=float, default=5.0)
    parser.add_argument("--min-box-ratio", type=float, default=0.5)
    parser.add_argument("--max-box-ratio", type=float, default=2.0)
    parser.add_argument("--max-vertical-error-px", type=float, default=None)
    parser.add_argument("--temporal-median-window", type=int, default=1)
    parser.add_argument("--temporal-outlier-max-delta-m", type=float, default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    status = evaluate_stereo_bbox_depth(
        input_path=args.input,
        out_dir=args.out_dir,
        recorded_width=args.recorded_width,
        recorded_height=args.recorded_height,
        min_confidence=args.min_confidence,
        min_depth_m=args.min_depth_m,
        max_depth_m=args.max_depth_m,
        min_box_ratio=args.min_box_ratio,
        max_box_ratio=args.max_box_ratio,
        max_vertical_error_px=args.max_vertical_error_px,
        temporal_median_window=args.temporal_median_window,
        temporal_outlier_max_delta_m=args.temporal_outlier_max_delta_m,
    )
    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    return 0 if status["frames_seen"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
