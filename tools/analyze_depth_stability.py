from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
_ROOT = TOOLS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from collect_stereo_bbox_pairs import StereoActiveTargetStabilizer  # noqa: E402
from smartxr.stereo_depth import (  # noqa: E402
    ANCHOR_KIND_BBOX_TOP_CENTER,
    SCENE_STEREO_28,
    StereoDetectionPair,
    StereoGateConfig,
    triangulate_detection_pair,
)


REPORT_FILE = "depth_stability_report.json"
DEFAULT_JUMP_THRESHOLDS_M = (0.2, 0.5, 1.0)
DEFAULT_SHIFT_WINDOW = 0


class AnalysisInput:
    def __init__(self, *, name: str, path: Path, kind: str = "auto") -> None:
        self.name = str(name)
        self.path = Path(path)
        self.kind = str(kind)


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
        "p05": _percentile(values, 0.05),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "max": max(values) if values else None,
    }


def _temporal_bucket(value_ms: float | None) -> str:
    if value_ms is None:
        return "missing"
    if value_ms < 5.0:
        return "lt_5ms"
    if value_ms < 10.0:
        return "5_to_10ms"
    return "gte_10ms"


def _counter_dict(values: Iterable[Any]) -> dict[str, int]:
    return {str(key): count for key, count in Counter(str(value) for value in values).items()}


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _raw_pair(record: dict[str, Any]) -> str | None:
    left = record.get("raw_left_track_id")
    right = record.get("raw_right_track_id")
    if left is None or right is None:
        return None
    return f"{left}-{right}"


def _count_adjacent_switches(values: list[Any]) -> int:
    filtered = [value for value in values if value is not None]
    return sum(1 for before, after in zip(filtered, filtered[1:]) if before != after)


def _jump_counts(records: list[dict[str, Any]], thresholds_m: tuple[float, ...]) -> dict[str, int]:
    depths = [record["depth_m"] for record in records if record.get("depth_m") is not None]
    counts: dict[str, int] = {}
    for threshold in thresholds_m:
        counts[f"gt_{threshold:.1f}m"] = sum(
            1 for before, after in zip(depths, depths[1:]) if abs(float(after) - float(before)) > threshold
        )
    return counts


def _point_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "sequence": record.get("sequence"),
        "frame_id": record.get("frame_id"),
        "target_id": record.get("target_id"),
        "raw_track_pair": _raw_pair(record),
        "depth_m": record.get("depth_m"),
        "disparity_px": record.get("disparity_px"),
        "vertical_error_px": record.get("vertical_error_px"),
        "depth_source": record.get("depth_source"),
        "depth_confidence": record.get("depth_confidence"),
        "pair_capture_delta_ms": record.get("pair_capture_delta_ms"),
        "pair_receive_delta_ms": record.get("pair_receive_delta_ms"),
    }


def _top_depth_jumps(records: list[dict[str, Any]], *, top_n: int) -> list[dict[str, Any]]:
    ordered_records = [record for record in records if record.get("depth_m") is not None]
    jumps: list[dict[str, Any]] = []
    for before, after in zip(ordered_records, ordered_records[1:]):
        delta = abs(float(after["depth_m"]) - float(before["depth_m"]))
        jumps.append(
            {
                "delta_m": delta,
                "from": _point_summary(before),
                "to": _point_summary(after),
            }
        )
    return sorted(jumps, key=lambda item: float(item["delta_m"]), reverse=True)[: max(0, int(top_n))]


def _temporal_summary(records: list[dict[str, Any]], thresholds_m: tuple[float, ...]) -> dict[str, Any]:
    capture_deltas = [
        float(record["pair_capture_delta_ms"])
        for record in records
        if record.get("pair_capture_delta_ms") is not None
    ]
    receive_deltas = [
        float(record["pair_receive_delta_ms"])
        for record in records
        if record.get("pair_receive_delta_ms") is not None
    ]
    frame_id_deltas = [
        float(record["frame_id_delta"])
        for record in records
        if record.get("frame_id_delta") is not None
    ]
    summary: dict[str, Any] = {
        "pair_capture_delta_ms": _series_summary(capture_deltas),
        "pair_receive_delta_ms": _series_summary(receive_deltas),
        "frame_id_delta": _series_summary(frame_id_deltas),
    }
    for threshold in thresholds_m:
        counts: Counter[str] = Counter()
        ordered_records = [record for record in records if record.get("depth_m") is not None]
        for before, after in zip(ordered_records, ordered_records[1:]):
            if abs(float(after["depth_m"]) - float(before["depth_m"])) > threshold:
                counts[_temporal_bucket(after.get("pair_capture_delta_ms"))] += 1
        summary[f"jump_gt_{threshold:.1f}m_by_capture_delta_bucket"] = dict(counts)
    return summary


def _summarize_records(
    records: list[dict[str, Any]],
    *,
    input_path: Path | None = None,
    input_kind: str | None = None,
    total_rows: int | None = None,
    rejected_count: int = 0,
    top_n: int = 10,
    thresholds_m: tuple[float, ...] = DEFAULT_JUMP_THRESHOLDS_M,
) -> dict[str, Any]:
    depths = [float(record["depth_m"]) for record in records if record.get("depth_m") is not None]
    disparities = [
        float(record["disparity_px"]) for record in records if record.get("disparity_px") is not None
    ]
    confidences = [record.get("depth_confidence") for record in records if record.get("depth_confidence") is not None]
    low_confidence_count = sum(1 for value in confidences if str(value) == "low")
    accepted_count = len(records)
    target_ids = [record.get("target_id") for record in records]
    raw_pairs = [_raw_pair(record) for record in records]
    summary: dict[str, Any] = {
        "input_path": None if input_path is None else str(input_path),
        "input_kind": input_kind,
        "rows_seen": total_rows if total_rows is not None else accepted_count + rejected_count,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "depth_m": _series_summary(depths),
        "disparity_px": _series_summary(disparities),
        "jump_counts": _jump_counts(records, thresholds_m),
        "top_depth_jumps": _top_depth_jumps(records, top_n=top_n),
        "stable_target_switch_count": _count_adjacent_switches(target_ids),
        "target_switch_count": _count_adjacent_switches(target_ids),
        "raw_track_switch_count": _count_adjacent_switches(raw_pairs),
        "raw_track_pairs": sorted({str(pair) for pair in raw_pairs if pair is not None}),
        "depth_confidence_counts": _counter_dict(confidences),
        "depth_source_counts": _counter_dict(
            record.get("depth_source") for record in records if record.get("depth_source") is not None
        ),
        "low_confidence_count": low_confidence_count,
        "low_confidence_ratio": 0.0 if accepted_count == 0 else low_confidence_count / accepted_count,
        "temporal": _temporal_summary(records, thresholds_m),
    }
    return summary


def _infer_kind(path: Path, explicit_kind: str) -> str:
    if explicit_kind != "auto":
        return explicit_kind
    for record in _iter_jsonl(path):
        if "event" in record:
            return "live_trace"
        if "bbox_candidates" in record:
            return "per_frame"
        break
    raise ValueError(f"Cannot infer input kind for {path}")


def _stereo_from_trace_row(row: dict[str, Any]) -> dict[str, Any]:
    stereo = row.get("stereo")
    return stereo if isinstance(stereo, dict) else {}


def _live_trace_records(path: Path) -> tuple[list[dict[str, Any]], int, int]:
    rows = list(_iter_jsonl(path))
    records: list[dict[str, Any]] = []
    rejected_count = 0
    for index, row in enumerate(rows):
        if row.get("event") != "accepted":
            rejected_count += 1
            continue
        stereo = _stereo_from_trace_row(row)
        depth_m = _float_or_none(row.get("depth_m"))
        if depth_m is None:
            continue
        records.append(
            {
                "sequence": row.get("sequence", index),
                "frame_id": row.get("left_frame_id", stereo.get("frame_id")),
                "target_id": row.get("target_id"),
                "depth_m": depth_m,
                "disparity_px": _float_or_none(stereo.get("disparity_px")),
                "vertical_error_px": _float_or_none(stereo.get("vertical_error_px")),
                "depth_source": row.get("depth_source"),
                "depth_confidence": row.get("depth_confidence"),
                "raw_left_track_id": row.get("raw_left_track_id"),
                "raw_right_track_id": row.get("raw_right_track_id"),
                "frame_id_delta": row.get("frame_id_delta"),
                "pair_capture_delta_ms": _float_or_none(row.get("pair_capture_delta_ms")),
                "pair_receive_delta_ms": _float_or_none(row.get("pair_receive_delta_ms")),
            }
        )
    return records, len(rows), rejected_count


def _candidate_depth_record(candidate: dict[str, Any], *, sequence: int, frame_id: Any) -> dict[str, Any] | None:
    if candidate.get("stereo_ok") is not True:
        return None
    depth_m = _float_or_none(candidate.get("depth_m"))
    if depth_m is None:
        return None
    left_id, right_id = _track_ids_from_candidate(candidate, fallback_index=sequence)
    return {
        "sequence": sequence,
        "frame_id": frame_id,
        "target_id": candidate.get("target_label", candidate.get("person_id")),
        "depth_m": depth_m,
        "disparity_px": _float_or_none(candidate.get("disparity_px")),
        "vertical_error_px": _float_or_none(candidate.get("vertical_error_px")),
        "depth_source": candidate.get("depth_source"),
        "depth_confidence": candidate.get("depth_confidence"),
        "raw_left_track_id": left_id,
        "raw_right_track_id": right_id,
    }


def _select_primary_per_frame_candidate(row: dict[str, Any], *, sequence: int) -> dict[str, Any] | None:
    candidates = [
        item for item in row.get("bbox_candidates", []) if isinstance(item, dict)
    ]
    rank_1 = [
        item for item in candidates if str(item.get("target_label")) == "rank_1_near" and item.get("stereo_ok") is True
    ]
    source = rank_1[0] if rank_1 else next((item for item in candidates if item.get("stereo_ok") is True), None)
    if source is None:
        return None
    return _candidate_depth_record(source, sequence=sequence, frame_id=row.get("frame_id"))


def _per_frame_records(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = list(_iter_jsonl(path))
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        record = _select_primary_per_frame_candidate(row, sequence=index)
        if record is not None:
            records.append(record)
    return rows, records


def _primary_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [item for item in row.get("bbox_candidates", []) if isinstance(item, dict)]
    rank_1 = [
        item for item in candidates if str(item.get("target_label")) == "rank_1_near" and item.get("stereo_ok") is True
    ]
    return rank_1[0] if rank_1 else next((item for item in candidates if item.get("stereo_ok") is True), None)


def _candidate_bbox_xyxy(candidate: dict[str, Any], eye: str) -> list[float] | None:
    key = f"{eye}_bbox_xyxy"
    bbox = candidate.get(key)
    if bbox is None:
        nested = candidate.get("bbox") if isinstance(candidate.get("bbox"), dict) else {}
        bbox = nested.get(f"{eye}_xyxy")
    if bbox is None:
        return None
    try:
        values = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    return values if len(values) == 4 else None


def _shifted_depth_record(
    *,
    left_row: dict[str, Any],
    right_row: dict[str, Any],
    sequence: int,
    shift_frames: int,
    recorded_width: int,
    recorded_height: int,
) -> dict[str, Any] | None:
    left_candidate = _primary_candidate(left_row)
    right_candidate = _primary_candidate(right_row)
    if left_candidate is None or right_candidate is None:
        return None
    left_bbox = _candidate_bbox_xyxy(left_candidate, "left")
    right_bbox = _candidate_bbox_xyxy(right_candidate, "right")
    if left_bbox is None or right_bbox is None:
        return None
    left_id, _left_right_id = _track_ids_from_candidate(left_candidate, fallback_index=sequence)
    _right_left_id, right_id = _track_ids_from_candidate(right_candidate, fallback_index=sequence)
    confidence = min(float(left_candidate.get("confidence", 1.0)), float(right_candidate.get("confidence", 1.0)))
    calibration = SCENE_STEREO_28.scaled_to(recorded_width, recorded_height)
    stereo = triangulate_detection_pair(
        StereoDetectionPair(
            pair_id=f"shift-{shift_frames:+d}-{sequence:06d}",
            frame_id=int(left_row.get("frame_id", sequence)),
            person_id=f"shift-left-{left_id}:right-{right_id}",
            left_bbox_xyxy=tuple(left_bbox),
            right_bbox_xyxy=tuple(right_bbox),
            confidence=confidence,
        ),
        calibration,
        anchor_kind=ANCHOR_KIND_BBOX_TOP_CENTER,
        gate_config=StereoGateConfig(min_confidence=0.0),
    )
    if stereo.get("stereo_ok") is not True:
        return None
    return {
        "sequence": sequence,
        "frame_id": left_row.get("frame_id", sequence),
        "target_id": f"shift-left-{left_id}:right-{right_id}",
        "depth_m": _float_or_none(stereo.get("depth_m")),
        "disparity_px": _float_or_none(stereo.get("disparity_px")),
        "vertical_error_px": _float_or_none(stereo.get("vertical_error_px")),
        "depth_source": "offline_shift_replay",
        "depth_confidence": "replayed_shift",
        "raw_left_track_id": left_id,
        "raw_right_track_id": right_id,
        "shift_frames": int(shift_frames),
        "left_frame_id": left_row.get("frame_id", sequence),
        "right_frame_id": right_row.get("frame_id", sequence + shift_frames),
        "frame_id_delta": int(left_row.get("frame_id", sequence)) - int(right_row.get("frame_id", sequence + shift_frames)),
    }


def _shift_replay_from_per_frame(
    rows: list[dict[str, Any]],
    *,
    shift_window: int,
    recorded_width: int,
    recorded_height: int,
    top_n: int,
) -> dict[str, Any]:
    shifts: dict[str, Any] = {}
    for shift in range(-max(0, int(shift_window)), max(0, int(shift_window)) + 1):
        records: list[dict[str, Any]] = []
        for index, left_row in enumerate(rows):
            right_index = index + shift
            if right_index < 0 or right_index >= len(rows):
                continue
            record = _shifted_depth_record(
                left_row=left_row,
                right_row=rows[right_index],
                sequence=index,
                shift_frames=shift,
                recorded_width=recorded_width,
                recorded_height=recorded_height,
            )
            if record is not None:
                records.append(record)
        summary = _summarize_records(records, input_kind="offline_shift_replay", top_n=top_n)
        summary["available"] = True
        summary["shift_frames"] = shift
        summary["temporal_shift"] = {
            "left_frame_offset": 0,
            "right_frame_offset": shift,
            "pairing": "left[t] vs right[t+shift]",
        }
        shifts[str(shift)] = summary
    return {
        "available": True,
        "shift_window": max(0, int(shift_window)),
        "shifts": shifts,
    }


def _track_ids_from_candidate(candidate: dict[str, Any], *, fallback_index: int) -> tuple[int, int]:
    person_id = str(candidate.get("person_id", ""))
    match = re.search(r"left-(\d+):right-(\d+)", person_id)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"person-(\d+)-(\d+)", person_id)
    if match:
        return int(match.group(1)), int(match.group(2))
    return fallback_index * 2 + 1, fallback_index * 2 + 2


def _person_from_bbox(track_id: int, bbox: list[float], confidence: Any) -> dict[str, Any]:
    return {
        "track_id": int(track_id),
        "bbox": [int(round(float(value))) for value in bbox],
        "confidence": 1.0 if confidence is None else float(confidence),
    }


def _frame_people_from_candidates(candidates: list[dict[str, Any]], *, frame_index: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    left_by_id: dict[int, dict[str, Any]] = {}
    right_by_id: dict[int, dict[str, Any]] = {}
    for candidate_index, candidate in enumerate(candidates):
        left_bbox = candidate.get("left_bbox_xyxy")
        right_bbox = candidate.get("right_bbox_xyxy")
        if left_bbox is None or right_bbox is None:
            bbox = candidate.get("bbox") if isinstance(candidate.get("bbox"), dict) else {}
            left_bbox = bbox.get("left_xyxy")
            right_bbox = bbox.get("right_xyxy")
        if left_bbox is None or right_bbox is None:
            continue
        left_id, right_id = _track_ids_from_candidate(candidate, fallback_index=frame_index * 100 + candidate_index)
        left_by_id[left_id] = _person_from_bbox(left_id, list(left_bbox), candidate.get("confidence"))
        right_by_id[right_id] = _person_from_bbox(right_id, list(right_bbox), candidate.get("confidence"))
    return list(left_by_id.values()), list(right_by_id.values())


def _candidate_for_raw_pair(
    candidates: list[dict[str, Any]],
    *,
    left_track_id: Any,
    right_track_id: Any,
) -> dict[str, Any] | None:
    try:
        expected = (int(left_track_id), int(right_track_id))
    except (TypeError, ValueError):
        return None
    for index, candidate in enumerate(candidates):
        if _track_ids_from_candidate(candidate, fallback_index=index) == expected:
            return candidate
    return None


def _replay_active_target_from_per_frame(
    rows: list[dict[str, Any]],
    *,
    recorded_width: int,
    recorded_height: int,
) -> dict[str, Any]:
    stabilizer = StereoActiveTargetStabilizer()
    records: list[dict[str, Any]] = []
    switch_reasons: list[str] = []
    candidate_counts: list[float] = []
    for index, row in enumerate(rows):
        candidates = [item for item in row.get("bbox_candidates", []) if isinstance(item, dict)]
        left_people, right_people = _frame_people_from_candidates(candidates, frame_index=index)
        selected = stabilizer.select(
            frame_id=int(row.get("frame_id", index)),
            image_width=recorded_width,
            image_height=recorded_height,
            left_people=left_people,
            right_people=right_people,
        )
        if selected is None:
            continue
        selection = selected.get("selection", {})
        matched_candidate = _candidate_for_raw_pair(
            candidates,
            left_track_id=selection.get("raw_left_track_id"),
            right_track_id=selection.get("raw_right_track_id"),
        )
        switch_reasons.append(str(selection.get("switch_reason", "unknown")))
        candidate_counts.append(float(selection.get("candidate_count", 0)))
        depth_m = _float_or_none(None if matched_candidate is None else matched_candidate.get("depth_m"))
        disparity_px = _float_or_none(None if matched_candidate is None else matched_candidate.get("disparity_px"))
        vertical_error_px = _float_or_none(None if matched_candidate is None else matched_candidate.get("vertical_error_px"))
        records.append(
            {
                "sequence": index,
                "frame_id": row.get("frame_id", index),
                "target_id": selection.get("active_target_id", selected.get("person_id")),
                "depth_m": depth_m if depth_m is not None else _float_or_none(selection.get("estimated_depth_m")),
                "disparity_px": disparity_px if disparity_px is not None else _float_or_none(selection.get("disparity_px")),
                "vertical_error_px": vertical_error_px if vertical_error_px is not None else _float_or_none(selection.get("vertical_error_px")),
                "depth_source": "active_target_replay",
                "depth_confidence": "replayed",
                "raw_left_track_id": selection.get("raw_left_track_id"),
                "raw_right_track_id": selection.get("raw_right_track_id"),
            }
        )
    summary = _summarize_records(records, input_kind="active_target_replay", top_n=10)
    summary["available"] = True
    summary["switch_reasons"] = _counter_dict(switch_reasons)
    summary["candidate_count"] = _series_summary(candidate_counts)
    return summary


def _candidate_count_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return _series_summary([float(len(row.get("bbox_candidates", []))) for row in rows])


def _analyze_one(
    item: AnalysisInput,
    *,
    top_n: int,
    recorded_width: int,
    recorded_height: int,
    shift_window: int,
) -> dict[str, Any]:
    kind = _infer_kind(item.path, item.kind)
    if kind == "live_trace":
        records, rows_seen, rejected_count = _live_trace_records(item.path)
        summary = _summarize_records(
            records,
            input_path=item.path,
            input_kind=kind,
            total_rows=rows_seen,
            rejected_count=rejected_count,
            top_n=top_n,
        )
        summary["active_replay"] = {"available": False, "reason": "live trace already contains selected active target"}
        summary["shift_replay"] = {"available": False, "reason": "shift replay requires per_frame left/right bbox candidates"}
        return summary
    if kind == "per_frame":
        rows, records = _per_frame_records(item.path)
        summary = _summarize_records(
            records,
            input_path=item.path,
            input_kind=kind,
            total_rows=len(rows),
            rejected_count=max(0, len(rows) - len(records)),
            top_n=top_n,
        )
        summary["candidate_count"] = _candidate_count_summary(rows)
        summary["active_replay"] = _replay_active_target_from_per_frame(
            rows,
            recorded_width=recorded_width,
            recorded_height=recorded_height,
        )
        summary["shift_replay"] = _shift_replay_from_per_frame(
            rows,
            shift_window=shift_window,
            recorded_width=recorded_width,
            recorded_height=recorded_height,
            top_n=top_n,
        )
        return summary
    raise ValueError(f"Unsupported input kind: {kind}")


def _comparison(datasets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    names = list(datasets)
    if len(names) < 2:
        return {}
    baseline_name = names[0]
    baseline = datasets[baseline_name]
    comparisons: dict[str, Any] = {"baseline": baseline_name, "datasets": {}}
    baseline_p95 = baseline.get("depth_m", {}).get("p95")
    baseline_jump_05 = baseline.get("jump_counts", {}).get("gt_0.5m")
    for name in names[1:]:
        current = datasets[name]
        current_p95 = current.get("depth_m", {}).get("p95")
        current_jump_05 = current.get("jump_counts", {}).get("gt_0.5m")
        comparisons["datasets"][name] = {
            "depth_p95_delta_m": None if baseline_p95 is None or current_p95 is None else current_p95 - baseline_p95,
            "jump_gt_0.5m_delta": None if baseline_jump_05 is None or current_jump_05 is None else current_jump_05 - baseline_jump_05,
        }
    return comparisons


def analyze_depth_stability(
    *,
    inputs: list[AnalysisInput],
    out_dir: Path,
    top_n: int = 10,
    recorded_width: int = 1164,
    recorded_height: int = 872,
    shift_window: int = DEFAULT_SHIFT_WINDOW,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    datasets = {
        item.name: _analyze_one(
            item,
            top_n=top_n,
            recorded_width=recorded_width,
            recorded_height=recorded_height,
            shift_window=shift_window,
        )
        for item in inputs
    }
    report = {
        "schema_version": 1,
        "generated_at_ms": int(time.time() * 1000),
        "datasets": datasets,
        "comparison": _comparison(datasets),
    }
    report_path = out_dir / REPORT_FILE
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _parse_input(value: str) -> AnalysisInput:
    kind = "auto"
    name_and_path = value
    if "::" in value:
        name_and_path, kind = value.rsplit("::", 1)
    if "=" in name_and_path:
        name, path = name_and_path.split("=", 1)
    else:
        path_obj = Path(name_and_path)
        name = path_obj.stem
        path = str(path_obj)
    return AnalysisInput(name=name, path=Path(path), kind=kind)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze live and recorded stereo depth stability JSONL traces."
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="Input JSONL as name=path or name=path::live_trace/per_frame. Repeatable.",
    )
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--recorded-width", type=int, default=1164)
    parser.add_argument("--recorded-height", type=int, default=872)
    parser.add_argument(
        "--shift-window",
        type=int,
        default=DEFAULT_SHIFT_WINDOW,
        help="For per_frame inputs, replay left[t] against right[t+shift] for shifts in [-N, N].",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    inputs = [_parse_input(value) for value in args.input]
    analyze_depth_stability(
        inputs=inputs,
        out_dir=args.out_dir,
        top_n=args.top_n,
        recorded_width=args.recorded_width,
        recorded_height=args.recorded_height,
        shift_window=args.shift_window,
    )
    status = {
        "depth_stability_report_json": str(args.out_dir / REPORT_FILE),
        "dataset_count": len(inputs),
    }
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
