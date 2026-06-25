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


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    frames_seen = len(records)
    ok_records = [record for record in records if record.get("stereo_ok") is True]
    rejected_records = [record for record in records if record.get("stereo_ok") is False]
    depths = [float(record["depth_m"]) for record in ok_records if "depth_m" in record]
    positions = [record["position"] for record in ok_records if "position" in record]
    rejection_counts = Counter(
        str(record.get("rejection_reason") or "unknown")
        for record in rejected_records
    )
    first_position = positions[0] if positions else None
    position_drift_m = 0.0
    if first_position is not None:
        position_drift_m = max(_distance(first_position, position) for position in positions)

    return {
        "frames_seen": frames_seen,
        "stereo_ok_count": len(ok_records),
        "stereo_rejected_count": len(rejected_records),
        "stereo_ok_ratio": 0.0 if frames_seen == 0 else len(ok_records) / frames_seen,
        "depth_m": {
            "count": len(depths),
            "min": min(depths) if depths else None,
            "max": max(depths) if depths else None,
            "p10": _percentile(depths, 0.10),
            "median": _percentile(depths, 0.50),
            "p90": _percentile(depths, 0.90),
        },
        "position_drift_m": position_drift_m,
        "target_head_point_drift_m": position_drift_m,
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

    summary = _summarize(records)
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
    )
    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    return 0 if status["frames_seen"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
