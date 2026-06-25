from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from evaluate_stereo_keypoint_depth import evaluate_keypoint_anchor_depth  # noqa: E402
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
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return tuple(float(item) for item in value)  # type: ignore[return-value]
    if isinstance(value, dict) and {"x1", "y1", "x2", "y2"}.issubset(value):
        return (float(value["x1"]), float(value["y1"]), float(value["x2"]), float(value["y2"]))
    raise ValueError(f"bbox must be xyxy, got {value!r}")


def _detections(eye: Any) -> list[dict[str, Any]]:
    if not isinstance(eye, dict):
        return []
    for key in ("people", "detections"):
        values = eye.get(key)
        if isinstance(values, list):
            return [item for item in values if isinstance(item, dict) and item.get("bbox") is not None]
    return []


def _center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) * 0.5, (y1 + y2) * 0.5)


def _size(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (max(0.0, x2 - x1), max(0.0, y2 - y1))


def _contains(bbox: tuple[float, float, float, float], point: list[float], *, margin_px: float) -> bool:
    x1, y1, x2, y2 = bbox
    return (
        x1 - margin_px <= float(point[0]) <= x2 + margin_px
        and y1 - margin_px <= float(point[1]) <= y2 + margin_px
    )


def _bbox_distance(
    left_bbox: tuple[float, float, float, float],
    right_bbox: tuple[float, float, float, float],
) -> float:
    _lx, left_cy = _center(left_bbox)
    _rx, right_cy = _center(right_bbox)
    left_w, left_h = _size(left_bbox)
    right_w, right_h = _size(right_bbox)
    return abs(left_cy - right_cy) + 0.25 * abs(left_w - right_w) + 0.25 * abs(left_h - right_h)


def _match_bbox_candidates(
    record: dict[str, Any],
    *,
    max_center_y_delta_px: float,
) -> list[tuple[dict[str, Any], dict[str, Any], tuple[float, float, float, float], tuple[float, float, float, float]]]:
    left_items = [(det, _bbox_xyxy(det["bbox"])) for det in _detections(record.get("left"))]
    right_items = [(det, _bbox_xyxy(det["bbox"])) for det in _detections(record.get("right"))]
    scored: list[tuple[float, int, int]] = []
    for left_index, (_left_det, left_bbox) in enumerate(left_items):
        left_cx, left_cy = _center(left_bbox)
        for right_index, (_right_det, right_bbox) in enumerate(right_items):
            right_cx, right_cy = _center(right_bbox)
            if left_cx - right_cx <= 0.0:
                continue
            if abs(left_cy - right_cy) > float(max_center_y_delta_px):
                continue
            scored.append((_bbox_distance(left_bbox, right_bbox), left_index, right_index))

    matched: list[
        tuple[dict[str, Any], dict[str, Any], tuple[float, float, float, float], tuple[float, float, float, float]]
    ] = []
    used_left: set[int] = set()
    used_right: set[int] = set()
    for _score, left_index, right_index in sorted(scored):
        if left_index in used_left or right_index in used_right:
            continue
        left_det, left_bbox = left_items[left_index]
        right_det, right_bbox = right_items[right_index]
        matched.append((left_det, right_det, left_bbox, right_bbox))
        used_left.add(left_index)
        used_right.add(right_index)
    return matched


def _same_bbox(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    *,
    tolerance_px: float = 1.0,
) -> bool:
    return all(abs(left - right) <= tolerance_px for left, right in zip(first, second))


def _selected_bbox_fallback_candidate(
    record: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], tuple[float, float, float, float], tuple[float, float, float, float]] | None:
    left_value = record.get("left_bbox_xyxy")
    right_value = record.get("right_bbox_xyxy")
    if left_value is None or right_value is None:
        return None
    left_bbox = _bbox_xyxy(left_value)
    right_bbox = _bbox_xyxy(right_value)
    left_det = {
        "track_id": record.get("person_id", "selected"),
        "bbox": list(left_bbox),
        "confidence": record.get("confidence", 1.0),
    }
    right_det = {
        "track_id": record.get("person_id", "selected"),
        "bbox": list(right_bbox),
        "confidence": record.get("confidence", 1.0),
    }
    return left_det, right_det, left_bbox, right_bbox


def _match_bbox_candidates_with_selected_fallback(
    record: dict[str, Any],
    *,
    max_center_y_delta_px: float,
) -> list[
    tuple[
        dict[str, Any],
        dict[str, Any],
        tuple[float, float, float, float],
        tuple[float, float, float, float],
        str,
    ]
]:
    matched = [
        (*candidate, "matched_bbox")
        for candidate in _match_bbox_candidates(record, max_center_y_delta_px=max_center_y_delta_px)
    ]
    fallback = _selected_bbox_fallback_candidate(record)
    if fallback is None:
        return matched
    _left_det, _right_det, fallback_left_bbox, fallback_right_bbox = fallback
    for _left_det, _right_det, left_bbox, right_bbox, _source in matched:
        if _same_bbox(left_bbox, fallback_left_bbox) and _same_bbox(right_bbox, fallback_right_bbox):
            return matched
    matched.append((*fallback, "selected_bbox_fallback"))
    return matched


def _candidate_pair(
    source: dict[str, Any],
    index: int,
    left_det: dict[str, Any],
    right_det: dict[str, Any],
    left_bbox: tuple[float, float, float, float],
    right_bbox: tuple[float, float, float, float],
) -> StereoDetectionPair:
    confidence_values = [
        value
        for value in (left_det.get("confidence"), right_det.get("confidence"), source.get("confidence"))
        if value is not None
    ]
    confidence = min(float(value) for value in confidence_values) if confidence_values else 1.0
    frame_id = int(source.get("frame_id", source.get("sequence", index)))
    left_track = left_det.get("track_id", left_det.get("id", "left"))
    right_track = right_det.get("track_id", right_det.get("id", "right"))
    return StereoDetectionPair(
        pair_id=str(source.get("pair_id", f"pair-{frame_id:06d}")),
        frame_id=frame_id,
        person_id=f"left-{left_track}:right-{right_track}",
        left_bbox_xyxy=left_bbox,
        right_bbox_xyxy=right_bbox,
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


def _empty_metric() -> dict[str, Any]:
    return {
        "frames_seen": 0,
        "ok_count": 0,
        "rejected_count": 0,
        "ok_ratio": 0.0,
        "depth_m": _series_summary([]),
        "drift_m": 0.0,
        "top_rejection_reasons": [],
    }


def _summarize_metric(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return _empty_metric()
    ok_records = [record for record in records if record.get("stereo_ok") is True]
    rejected_records = [record for record in records if record.get("stereo_ok") is False]
    depths = [float(record["depth_m"]) for record in ok_records if "depth_m" in record]
    positions = [record["position"] for record in ok_records if "position" in record]
    rejection_counts = Counter(str(record.get("rejection_reason") or "unknown") for record in rejected_records)
    return {
        "frames_seen": len(records),
        "ok_count": len(ok_records),
        "rejected_count": len(rejected_records),
        "ok_ratio": len(ok_records) / len(records),
        "depth_m": _series_summary(depths),
        "drift_m": _max_drift(positions),
        "top_rejection_reasons": [
            {"reason": reason, "count": count}
            for reason, count in rejection_counts.most_common()
        ],
    }


def _target_label(rank: int, count: int) -> str:
    if rank == 1:
        return "rank_1_near"
    if rank == count:
        return f"rank_{rank}_far"
    return f"rank_{rank}_mid"


def _same_bbox(a: Any, b: tuple[float, float, float, float]) -> bool:
    if a is None:
        return False
    try:
        av = _bbox_xyxy(a)
    except ValueError:
        return False
    return all(abs(float(left) - float(right)) < 1e-6 for left, right in zip(av, b, strict=True))


def _find_selected_bbox_label(source: dict[str, Any], candidates: list[dict[str, Any]]) -> str | None:
    left_bbox = source.get("left_bbox_xyxy")
    right_bbox = source.get("right_bbox_xyxy")
    for candidate in candidates:
        if _same_bbox(left_bbox, candidate["left_bbox_xyxy"]) and _same_bbox(
            right_bbox, candidate["right_bbox_xyxy"]
        ):
            return str(candidate["target_label"])
    return None


def _find_keypoint_candidate_label(
    *,
    keypoint_record: dict[str, Any],
    candidates: list[dict[str, Any]],
    margin_px: float,
    max_distance_px: float | None,
) -> str | None:
    anchor = keypoint_record.get("selected_anchor")
    if not isinstance(anchor, dict):
        return None
    left_px = anchor.get("left_px")
    right_px = anchor.get("right_px")
    if not (isinstance(left_px, list) and len(left_px) == 2 and isinstance(right_px, list) and len(right_px) == 2):
        return None

    containing = [
        candidate
        for candidate in candidates
        if _contains(candidate["left_bbox_xyxy"], left_px, margin_px=margin_px)
        and _contains(candidate["right_bbox_xyxy"], right_px, margin_px=margin_px)
    ]
    if containing:
        return str(containing[0]["target_label"])

    if not candidates:
        return None
    distances = [
        (
            _distance(
                [*_center(candidate["left_bbox_xyxy"]), 0.0],
                [float(left_px[0]), float(left_px[1]), 0.0],
            ),
            candidate,
        )
        for candidate in candidates
    ]
    best_distance, best = min(distances, key=lambda item: item[0])
    if max_distance_px is not None and best_distance > float(max_distance_px):
        return None
    return str(best["target_label"])


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_keypoint_records(
    keypoint_input_path: Path | None,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]], dict[str, dict[str, Any]]]:
    if keypoint_input_path is None:
        return [], {}, {}
    records = list(_iter_jsonl(keypoint_input_path))
    by_target: dict[tuple[str, str], dict[str, Any]] = {}
    legacy_by_pair_id: dict[str, dict[str, Any]] = {}
    for record in records:
        target_label = record.get("target_label")
        if target_label is not None:
            source_pair_id = str(record.get("source_pair_id", record.get("pair_id")))
            by_target[(source_pair_id, str(target_label))] = record
        else:
            legacy_by_pair_id[str(record.get("pair_id"))] = record
    return records, by_target, legacy_by_pair_id


def evaluate_stereo_multitarget_depth(
    *,
    bbox_input_path: Path,
    keypoint_input_path: Path | None,
    out_dir: Path,
    recorded_width: int = 1164,
    recorded_height: int = 872,
    min_confidence: float = 0.4,
    min_depth_m: float = 0.2,
    max_depth_m: float = 5.0,
    min_box_ratio: float = 0.5,
    max_box_ratio: float = 2.0,
    max_vertical_error_px: float | None = None,
    max_center_y_delta_px: float = 80.0,
    association_margin_px: float = 8.0,
    max_association_distance_px: float | None = 120.0,
    min_keypoint_score: float = 0.5,
    require_anchor_kind: str | None = None,
    anchor_mismatch_policy: str = "reject",
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
    keypoint_records, keypoint_by_target, legacy_keypoint_by_pair_id = _load_keypoint_records(keypoint_input_path)

    per_frame_path = out_dir / PER_FRAME_FILE
    frame_records: list[dict[str, Any]] = []
    target_bbox_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    target_keypoint_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    association_counts = Counter()
    mismatch_count = 0
    bbox_candidate_count = 0

    with per_frame_path.open("w", encoding="utf-8", newline="\n") as handle:
        for index, source in enumerate(_iter_jsonl(bbox_input_path), start=1):
            raw_candidates = []
            for left_det, right_det, left_bbox, right_bbox, candidate_source in _match_bbox_candidates_with_selected_fallback(
                source,
                max_center_y_delta_px=max_center_y_delta_px,
            ):
                pair = _candidate_pair(source, index, left_det, right_det, left_bbox, right_bbox)
                evaluated = triangulate_detection_pair(
                    pair,
                    calibration,
                    anchor_kind=ANCHOR_KIND_BBOX_TOP_CENTER,
                    gate_config=gate_config,
                )
                evaluated["left_bbox_xyxy"] = list(left_bbox)
                evaluated["right_bbox_xyxy"] = list(right_bbox)
                evaluated["candidate_source"] = candidate_source
                raw_candidates.append(evaluated)

            ok_for_rank = [candidate for candidate in raw_candidates if candidate.get("stereo_ok") is True]
            ranked = sorted(ok_for_rank, key=lambda candidate: float(candidate["depth_m"]))
            if not ranked:
                ranked.extend([
                    candidate
                    for candidate in raw_candidates
                    if candidate.get("candidate_source") == "selected_bbox_fallback"
                ][:1])
            for rank_index, candidate in enumerate(ranked, start=1):
                label = _target_label(rank_index, len(ranked))
                candidate["target_label"] = label
                target_bbox_records[label].append(candidate)

            for candidate in raw_candidates:
                if "target_label" not in candidate:
                    candidate["target_label"] = "unranked_rejected"
                    target_bbox_records["unranked_rejected"].append(candidate)
            bbox_candidate_count += len(raw_candidates)

            source_pair_id = str(source.get("pair_id"))
            keypoint_eval = None
            target_keypoint_records_for_frame = [
                (str(candidate["target_label"]), keypoint_by_target[(source_pair_id, str(candidate["target_label"]))])
                for candidate in raw_candidates
                if (source_pair_id, str(candidate["target_label"])) in keypoint_by_target
            ]
            if target_keypoint_records_for_frame:
                for selected_bbox_label, keypoint_record in target_keypoint_records_for_frame:
                    effective_anchor, candidate_keypoint_eval = evaluate_keypoint_anchor_depth(
                        keypoint_record,
                        calibration=calibration,
                        min_keypoint_score=min_keypoint_score,
                        min_depth_m=min_depth_m,
                        max_depth_m=max_depth_m,
                        max_vertical_error_px=max_vertical_error_px,
                        require_anchor_kind=require_anchor_kind,
                        anchor_mismatch_policy=anchor_mismatch_policy,
                    )
                    association_record = dict(keypoint_record)
                    association_record["selected_anchor"] = effective_anchor
                    associated_label = _find_keypoint_candidate_label(
                        keypoint_record=association_record,
                        candidates=raw_candidates,
                        margin_px=association_margin_px,
                        max_distance_px=max_association_distance_px,
                    )
                    if associated_label is None:
                        association_counts["unassociated"] += 1
                        continue
                    association_counts["associated"] += 1
                    if associated_label != selected_bbox_label:
                        mismatch_count += 1
                    candidate_keypoint_eval["target_label"] = associated_label
                    candidate_keypoint_eval["selected_bbox_target_label"] = selected_bbox_label
                    target_keypoint_records[associated_label].append(candidate_keypoint_eval)
                    if keypoint_eval is None:
                        keypoint_eval = candidate_keypoint_eval
            elif str(source.get("pair_id")) in legacy_keypoint_by_pair_id:
                keypoint_record = legacy_keypoint_by_pair_id[str(source.get("pair_id"))]
                selected_bbox_label = _find_selected_bbox_label(keypoint_record, raw_candidates)
                effective_anchor, candidate_keypoint_eval = evaluate_keypoint_anchor_depth(
                    keypoint_record,
                    calibration=calibration,
                    min_keypoint_score=min_keypoint_score,
                    min_depth_m=min_depth_m,
                    max_depth_m=max_depth_m,
                    max_vertical_error_px=max_vertical_error_px,
                    require_anchor_kind=require_anchor_kind,
                    anchor_mismatch_policy=anchor_mismatch_policy,
                )
                association_record = dict(keypoint_record)
                association_record["selected_anchor"] = effective_anchor
                associated_label = _find_keypoint_candidate_label(
                    keypoint_record=association_record,
                    candidates=raw_candidates,
                    margin_px=association_margin_px,
                    max_distance_px=max_association_distance_px,
                )
                if associated_label is None:
                    association_counts["unassociated"] += 1
                else:
                    association_counts["associated"] += 1
                    if selected_bbox_label is not None and associated_label != selected_bbox_label:
                        mismatch_count += 1
                    keypoint_eval = candidate_keypoint_eval
                    keypoint_eval["target_label"] = associated_label
                    keypoint_eval["selected_bbox_target_label"] = selected_bbox_label
                    target_keypoint_records[associated_label].append(keypoint_eval)

            frame_record = {
                "schema_version": 1,
                "pair_id": source.get("pair_id"),
                "frame_id": source.get("frame_id"),
                "bbox_candidates": raw_candidates,
            }
            if keypoint_eval is not None:
                frame_record["keypoint"] = keypoint_eval
            frame_records.append(frame_record)
            handle.write(json.dumps(frame_record, ensure_ascii=False, separators=(",", ":")) + "\n")

    target_labels = sorted(
        set(target_bbox_records) | set(target_keypoint_records),
        key=lambda label: (label == "unranked_rejected", label),
    )
    targets = {
        label: {
            "bbox": _summarize_metric(target_bbox_records.get(label, [])),
            "keypoint": _summarize_metric(target_keypoint_records.get(label, [])),
        }
        for label in target_labels
    }
    input_frames = len(frame_records)
    frames_with_candidate = sum(1 for record in frame_records if record["bbox_candidates"])
    summary = {
        "input_frames": input_frames,
        "matched_candidate_count": bbox_candidate_count,
        "frames_with_candidate": frames_with_candidate,
        "target_coverage_ratio": 0.0 if input_frames == 0 else frames_with_candidate / input_frames,
        "frames_seen": input_frames,
        "bbox_candidate_count": bbox_candidate_count,
        "targets": targets,
        "keypoint_association": {
            "input_count": len(keypoint_records),
            "associated_count": association_counts["associated"],
            "unassociated_count": association_counts["unassociated"],
            "bbox_target_mismatch_count": mismatch_count,
        },
    }
    summary_path = out_dir / SUMMARY_FILE
    _write_json(summary_path, summary)
    return {
        "bbox_input_jsonl": str(bbox_input_path),
        "keypoint_input_jsonl": None if keypoint_input_path is None else str(keypoint_input_path),
        "per_frame_jsonl": str(per_frame_path),
        "summary_json": str(summary_path),
        "frames_seen": summary["frames_seen"],
        "bbox_candidate_count": bbox_candidate_count,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate multi-target stereo depth candidates and keypoint association."
    )
    parser.add_argument("--bbox-input", required=True, type=Path)
    parser.add_argument("--keypoint-input", type=Path, default=None)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--recorded-width", type=int, default=1164)
    parser.add_argument("--recorded-height", type=int, default=872)
    parser.add_argument("--min-confidence", type=float, default=0.4)
    parser.add_argument("--min-depth-m", type=float, default=0.2)
    parser.add_argument("--max-depth-m", type=float, default=5.0)
    parser.add_argument("--min-box-ratio", type=float, default=0.5)
    parser.add_argument("--max-box-ratio", type=float, default=2.0)
    parser.add_argument("--max-vertical-error-px", type=float, default=None)
    parser.add_argument("--max-center-y-delta-px", type=float, default=80.0)
    parser.add_argument("--association-margin-px", type=float, default=8.0)
    parser.add_argument("--max-association-distance-px", type=float, default=120.0)
    parser.add_argument("--min-keypoint-score", type=float, default=0.5)
    parser.add_argument("--require-anchor-kind", default=None)
    parser.add_argument("--anchor-mismatch-policy", choices=["reject", "fallback_bbox"], default="reject")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    status = evaluate_stereo_multitarget_depth(
        bbox_input_path=args.bbox_input,
        keypoint_input_path=args.keypoint_input,
        out_dir=args.out_dir,
        recorded_width=args.recorded_width,
        recorded_height=args.recorded_height,
        min_confidence=args.min_confidence,
        min_depth_m=args.min_depth_m,
        max_depth_m=args.max_depth_m,
        min_box_ratio=args.min_box_ratio,
        max_box_ratio=args.max_box_ratio,
        max_vertical_error_px=args.max_vertical_error_px,
        max_center_y_delta_px=args.max_center_y_delta_px,
        association_margin_px=args.association_margin_px,
        max_association_distance_px=args.max_association_distance_px,
        min_keypoint_score=args.min_keypoint_score,
        require_anchor_kind=args.require_anchor_kind,
        anchor_mismatch_policy=args.anchor_mismatch_policy,
    )
    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    return 0 if status["frames_seen"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
