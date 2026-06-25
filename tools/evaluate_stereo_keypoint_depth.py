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

from smartxr.stereo_depth import SCENE_STEREO_28  # noqa: E402


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


def _series_summary(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "p10": _percentile(values, 0.10),
        "median": _percentile(values, 0.50),
        "p90": _percentile(values, 0.90),
    }


def _distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((float(av) - float(bv)) ** 2 for av, bv in zip(a, b, strict=True)))


def _max_drift(positions: list[list[float]]) -> float:
    if not positions:
        return 0.0
    first = positions[0]
    return max(_distance(first, position) for position in positions)


def _depth_from_anchor(
    *,
    left_px: list[float] | None,
    right_px: list[float] | None,
    score: float,
    calibration: Any,
    min_score: float | None,
    min_depth_m: float,
    max_depth_m: float,
    max_vertical_error_px: float | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "left_anchor_px": left_px,
        "right_anchor_px": right_px,
        "score": float(score),
        "stereo_ok": False,
        "rejection_reason": None,
    }
    if left_px is None or right_px is None:
        record["rejection_reason"] = "missing_anchor"
        return record
    if min_score is not None and float(score) < float(min_score):
        record["rejection_reason"] = "low_keypoint_score"
        return record

    left_x, left_y = (float(left_px[0]), float(left_px[1]))
    right_x, right_y = (float(right_px[0]), float(right_px[1]))
    disparity_px = left_x - right_x
    vertical_error_px = left_y - right_y
    record["disparity_px"] = disparity_px
    record["vertical_error_px"] = vertical_error_px
    if max_vertical_error_px is not None and abs(vertical_error_px) > float(max_vertical_error_px):
        record["rejection_reason"] = "vertical_error_too_large"
        return record
    if disparity_px <= 0.0:
        record["rejection_reason"] = "non_positive_disparity"
        return record

    depth_m = calibration.left.fx * calibration.baseline_m / disparity_px
    if depth_m < float(min_depth_m) or depth_m > float(max_depth_m):
        record["rejection_reason"] = "depth_out_of_range"
        record["depth_m"] = depth_m
        return record

    record["stereo_ok"] = True
    record["depth_m"] = depth_m
    record["position"] = calibration.left.unproject(left_x, left_y, depth_m)
    return record


def _record_to_evaluated(
    record: dict[str, Any],
    *,
    calibration: Any,
    min_keypoint_score: float,
    min_depth_m: float,
    max_depth_m: float,
    max_vertical_error_px: float | None,
) -> dict[str, Any]:
    anchor = record.get("selected_anchor") if isinstance(record.get("selected_anchor"), dict) else {}
    evaluated = {
        "schema_version": 1,
        "pair_id": record.get("pair_id"),
        "frame_id": record.get("frame_id"),
        "person_id": record.get("person_id"),
        "selected_anchor": anchor,
        "keypoint": _depth_from_anchor(
            left_px=anchor.get("left_px"),
            right_px=anchor.get("right_px"),
            score=float(anchor.get("score", 0.0)),
            calibration=calibration,
            min_score=min_keypoint_score,
            min_depth_m=min_depth_m,
            max_depth_m=max_depth_m,
            max_vertical_error_px=max_vertical_error_px,
        ),
    }
    bbox = record.get("bbox_baseline") if isinstance(record.get("bbox_baseline"), dict) else None
    if bbox is not None:
        evaluated["bbox_baseline"] = _depth_from_anchor(
            left_px=bbox.get("left_anchor_px"),
            right_px=bbox.get("right_anchor_px"),
            score=float(bbox.get("score", 1.0)),
            calibration=calibration,
            min_score=None,
            min_depth_m=min_depth_m,
            max_depth_m=max_depth_m,
            max_vertical_error_px=max_vertical_error_px,
        )
    return evaluated


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    keypoint_records = [record["keypoint"] for record in records]
    keypoint_ok = [record for record in keypoint_records if record.get("stereo_ok") is True]
    keypoint_rejected = [record for record in keypoint_records if record.get("stereo_ok") is False]
    keypoint_depths = [float(record["depth_m"]) for record in keypoint_ok if "depth_m" in record]
    keypoint_positions = [record["position"] for record in keypoint_ok if "position" in record]
    rejection_counts = Counter(
        str(record.get("rejection_reason") or "unknown")
        for record in keypoint_rejected
    )
    anchor_counts = Counter(
        str(record.get("selected_anchor", {}).get("kind", "unknown"))
        for record in records
    )

    bbox_records = [
        record["bbox_baseline"]
        for record in records
        if isinstance(record.get("bbox_baseline"), dict)
    ]
    bbox_ok = [record for record in bbox_records if record.get("stereo_ok") is True]
    bbox_depths = [float(record["depth_m"]) for record in bbox_ok if "depth_m" in record]
    bbox_positions = [record["position"] for record in bbox_ok if "position" in record]

    frames_seen = len(records)
    return {
        "frames_seen": frames_seen,
        "keypoint_ok_count": len(keypoint_ok),
        "keypoint_rejected_count": len(keypoint_rejected),
        "keypoint_ok_ratio": 0.0 if frames_seen == 0 else len(keypoint_ok) / frames_seen,
        "keypoint_depth_m": _series_summary(keypoint_depths),
        "keypoint_drift_m": _max_drift(keypoint_positions),
        "keypoint_anchor_kinds": [
            {"kind": kind, "count": count}
            for kind, count in anchor_counts.most_common()
        ],
        "top_rejection_reasons": [
            {"reason": reason, "count": count}
            for reason, count in rejection_counts.most_common()
        ],
        "bbox_baseline": {
            "frames_seen": len(bbox_records),
            "ok_count": len(bbox_ok),
            "ok_ratio": 0.0 if not bbox_records else len(bbox_ok) / len(bbox_records),
            "depth_m": _series_summary(bbox_depths),
            "drift_m": _max_drift(bbox_positions),
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def evaluate_stereo_keypoint_depth(
    *,
    input_path: Path,
    out_dir: Path,
    recorded_width: int = 1164,
    recorded_height: int = 872,
    min_keypoint_score: float = 0.5,
    min_depth_m: float = 0.2,
    max_depth_m: float = 5.0,
    max_vertical_error_px: float | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    calibration = SCENE_STEREO_28.scaled_to(recorded_width, recorded_height)
    records: list[dict[str, Any]] = []
    per_frame_path = out_dir / PER_FRAME_FILE
    with per_frame_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in _iter_jsonl(input_path):
            evaluated = _record_to_evaluated(
                record,
                calibration=calibration,
                min_keypoint_score=min_keypoint_score,
                min_depth_m=min_depth_m,
                max_depth_m=max_depth_m,
                max_vertical_error_px=max_vertical_error_px,
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
        "keypoint_ok_count": summary["keypoint_ok_count"],
        "keypoint_rejected_count": summary["keypoint_rejected_count"],
        "keypoint_ok_ratio": summary["keypoint_ok_ratio"],
    }
    return status


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate stereo keypoint anchor depth stability from paired keypoint JSONL."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--recorded-width", type=int, default=1164)
    parser.add_argument("--recorded-height", type=int, default=872)
    parser.add_argument("--min-keypoint-score", type=float, default=0.5)
    parser.add_argument("--min-depth-m", type=float, default=0.2)
    parser.add_argument("--max-depth-m", type=float, default=5.0)
    parser.add_argument("--max-vertical-error-px", type=float, default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    status = evaluate_stereo_keypoint_depth(
        input_path=args.input,
        out_dir=args.out_dir,
        recorded_width=args.recorded_width,
        recorded_height=args.recorded_height,
        min_keypoint_score=args.min_keypoint_score,
        min_depth_m=args.min_depth_m,
        max_depth_m=args.max_depth_m,
        max_vertical_error_px=args.max_vertical_error_px,
    )
    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    return 0 if status["frames_seen"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
