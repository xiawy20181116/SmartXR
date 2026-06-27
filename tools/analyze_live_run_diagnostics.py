from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


REPORT_FILE = "live_run_diagnostics.json"


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must be a JSON object")
            yield value


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _decode_log_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig", errors="replace")
    if b"\x00" in data[:256]:
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8", errors="replace")


def _read_log(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return _decode_log_text(path.read_bytes())


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


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


def _stage_timing_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    keys: set[str] = set()
    for event in events:
        timing = event.get("stage_timing_ms")
        if isinstance(timing, dict):
            keys.update(str(key) for key in timing)
    summary: dict[str, Any] = {}
    for key in sorted(keys):
        values: list[float] = []
        for event in events:
            timing = event.get("stage_timing_ms")
            if not isinstance(timing, dict):
                continue
            value = _float_or_none(timing.get(key))
            if value is not None:
                values.append(value)
        summary[key] = _series_summary(values)
    return summary


def _interval_summary(values: list[float]) -> dict[str, Any]:
    intervals = [current - previous for previous, current in zip(values, values[1:]) if current >= previous]
    hz = None
    if intervals:
        mean_interval = sum(intervals) / len(intervals)
        hz = 1000.0 / mean_interval if mean_interval > 0 else None
    return {
        **_series_summary(intervals),
        "observed_hz": hz,
    }


def _counter_dict(values: Iterable[Any]) -> dict[str, int]:
    return {str(key): count for key, count in sorted(Counter(str(value) for value in values).items())}


def _nested(row: dict[str, Any], section: str, key: str) -> Any:
    value = row.get(section)
    if isinstance(value, dict) and key in value:
        return value[key]
    return row.get(key)


def _raw_pair(row: dict[str, Any]) -> str | None:
    left = row.get("raw_left_track_id")
    right = row.get("raw_right_track_id")
    if left is None or right is None:
        return None
    return f"{left}-{right}"


def _event_position(row: dict[str, Any]) -> Any:
    transform = row.get("transform")
    if isinstance(transform, dict) and "position" in transform:
        return transform["position"]
    target = row.get("target")
    if isinstance(target, dict):
        target_transform = target.get("transform")
        if isinstance(target_transform, dict):
            return target_transform.get("position")
    return row.get("position")


def _normalize_event(row: dict[str, Any], index: int) -> dict[str, Any]:
    temporal = row.get("temporal") if isinstance(row.get("temporal"), dict) else {}
    sync = row.get("sync") if isinstance(row.get("sync"), dict) else {}
    clients = row.get("clients") if isinstance(row.get("clients"), dict) else {}
    left_frame_id = _nested(row, "temporal", "left_frame_id")
    right_frame_id = _nested(row, "temporal", "right_frame_id")
    left_capture_timestamp_us = _nested(row, "temporal", "left_capture_timestamp_us")
    right_capture_timestamp_us = _nested(row, "temporal", "right_capture_timestamp_us")
    return {
        "index": index,
        "event": row.get("event", "accepted"),
        "sequence": row.get("sequence"),
        "timestamp_ms": _float_or_none(row.get("timestamp_ms")),
        "reason": row.get("reason") or row.get("switch_reason"),
        "non_publish_reason": row.get("non_publish_reason"),
        "non_published_frames": row.get("non_published_frames") if isinstance(row.get("non_published_frames"), list) else [],
        "stage_timing_ms": row.get("stage_timing_ms") if isinstance(row.get("stage_timing_ms"), dict) else {},
        "freshness": row.get("freshness") if isinstance(row.get("freshness"), dict) else {},
        "target_id": row.get("target_id"),
        "active_target_id": row.get("active_target_id"),
        "left_frame_id": left_frame_id,
        "right_frame_id": right_frame_id,
        "frame_id": row.get("frame_id") or left_frame_id or temporal.get("frame_id"),
        "left_capture_timestamp_us": left_capture_timestamp_us,
        "right_capture_timestamp_us": right_capture_timestamp_us,
        "left_capture_timestamp_source": temporal.get("left_capture_timestamp_source"),
        "right_capture_timestamp_source": temporal.get("right_capture_timestamp_source"),
        "pair_capture_delta_ms": _float_or_none(_nested(row, "temporal", "pair_capture_delta_ms")),
        "pair_receive_delta_ms": _float_or_none(_nested(row, "temporal", "pair_receive_delta_ms")),
        "raw_left_track_id": row.get("raw_left_track_id"),
        "raw_right_track_id": row.get("raw_right_track_id"),
        "raw_track_pair": _raw_pair(row),
        "depth_m": _float_or_none(row.get("depth_m")),
        "position": _event_position(row),
        "depth_source": row.get("depth_source"),
        "depth_confidence": row.get("depth_confidence"),
        "switch_reason": row.get("switch_reason"),
        "held_last_pose": _truthy(row.get("held_last_pose")),
        "active_age_frames": row.get("active_age_frames"),
        "candidate_count": row.get("candidate_count"),
        "selected_score": row.get("selected_score"),
        "client_count": clients.get("active_client_count"),
        "active_clients": clients.get("active_clients"),
        "last_disconnect": clients.get("last_disconnect"),
        "sync_pairing_strategy": sync.get("pairing_strategy"),
        "temporal_mismatch_count": sync.get("temporal_mismatch_count"),
        "dropped_left_frames": sync.get("dropped_left_frames"),
        "dropped_right_frames": sync.get("dropped_right_frames"),
    }


def _context(events: list[dict[str, Any]], center_index: int, radius: int, pcmr_status: dict[str, Any]) -> list[dict[str, Any]]:
    start = max(0, center_index - max(0, radius))
    end = min(len(events), center_index + max(0, radius) + 1)
    return [_context_item(event, pcmr_status) for event in events[start:end]]


def _context_item(event: dict[str, Any], pcmr_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": event.get("event"),
        "sequence": event.get("sequence"),
        "timestamp_ms": event.get("timestamp_ms"),
        "reason": event.get("reason"),
        "non_publish_reason": event.get("non_publish_reason"),
        "non_published_frames": event.get("non_published_frames", []),
        "stage_timing_ms": event.get("stage_timing_ms"),
        "freshness": event.get("freshness"),
        "target_id": event.get("target_id"),
        "active_target_id": event.get("active_target_id"),
        "left_frame_id": event.get("left_frame_id"),
        "right_frame_id": event.get("right_frame_id"),
        "left_capture_timestamp_us": event.get("left_capture_timestamp_us"),
        "right_capture_timestamp_us": event.get("right_capture_timestamp_us"),
        "pair_capture_delta_ms": event.get("pair_capture_delta_ms"),
        "raw_left_track_id": event.get("raw_left_track_id"),
        "raw_right_track_id": event.get("raw_right_track_id"),
        "raw_track_pair": event.get("raw_track_pair"),
        "depth_m": event.get("depth_m"),
        "position": event.get("position"),
        "switch_reason": event.get("switch_reason"),
        "held_last_pose": event.get("held_last_pose"),
        "client_count": event.get("client_count"),
        "godot_sequence": pcmr_status.get("sequence"),
        "godot_card_position": pcmr_status.get("card_resolved_position") or pcmr_status.get("card_node_position"),
        "godot_card_target_id": pcmr_status.get("card_target_id"),
    }


def _parse_sender_clients(sender_log_text: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    last_disconnect: dict[str, Any] | None = None
    active: dict[str, dict[str, Any]] = {}
    connect_re = re.compile(r"client connected: id=(?P<id>\S+)\s+label=(?P<label>\S+)\s+address=(?P<address>\S+)")
    disconnect_re = re.compile(r"client disconnected: id=(?P<id>\S+)\s+label=(?P<label>\S+)\s+address=(?P<address>\S+)\s+reason=(?P<reason>\S+)")
    for line in sender_log_text.splitlines():
        connect = connect_re.search(line)
        if connect:
            item = {
                "event": "connected",
                "client_id": connect.group("id"),
                "label": connect.group("label"),
                "address": connect.group("address"),
            }
            events.append(item)
            active[item["client_id"]] = item
            continue
        disconnect = disconnect_re.search(line)
        if disconnect:
            item = {
                "event": "disconnected",
                "client_id": disconnect.group("id"),
                "label": disconnect.group("label"),
                "address": disconnect.group("address"),
                "reason": disconnect.group("reason"),
            }
            events.append(item)
            last_disconnect = item
            active.pop(item["client_id"], None)
            continue
        if "client text:" in line:
            events.append({"event": "client_text", "text": line.split("client text:", 1)[1].strip()})
    return {
        "events": events,
        "active_clients": list(active.values()),
        "last_disconnect": last_disconnect,
    }


def _trace_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [event for event in events if event.get("event") == "accepted"]
    rejected = [event for event in events if event.get("event") != "accepted"]
    depths = [event["depth_m"] for event in accepted if event.get("depth_m") is not None]
    capture_deltas = [event["pair_capture_delta_ms"] for event in events if event.get("pair_capture_delta_ms") is not None]
    raw_pairs = [event.get("raw_track_pair") for event in accepted if event.get("raw_track_pair") is not None]
    target_ids = [event.get("target_id") for event in accepted if event.get("target_id") is not None]
    held = sum(1 for event in accepted if event.get("held_last_pose"))
    non_published_frame_reasons = []
    for event in events:
        for frame in event.get("non_published_frames", []):
            if isinstance(frame, dict) and frame.get("reason") is not None:
                non_published_frame_reasons.append(frame.get("reason"))
    return {
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "depth_m": _series_summary(depths),
        "pair_capture_delta_ms": _series_summary(capture_deltas),
        "depth_confidences": _counter_dict(event.get("depth_confidence") for event in accepted if event.get("depth_confidence") is not None),
        "depth_sources": _counter_dict(event.get("depth_source") for event in accepted if event.get("depth_source") is not None),
        "held_last_pose_count": held,
        "held_last_pose_ratio": 0.0 if not accepted else held / len(accepted),
        "raw_track_switch_count": _adjacent_switch_count(raw_pairs),
        "target_switch_count": _adjacent_switch_count(target_ids),
        "rejected_reasons": _counter_dict(event.get("reason") for event in rejected if event.get("reason") is not None),
        "non_publish_reasons": _counter_dict(
            event.get("non_publish_reason") or event.get("reason")
            for event in rejected
            if (event.get("non_publish_reason") or event.get("reason")) is not None
        ),
        "non_published_frame_reasons": _counter_dict(non_published_frame_reasons),
        "freshness_states": _counter_dict(
            event.get("freshness", {}).get("state")
            for event in accepted
            if isinstance(event.get("freshness"), dict) and event.get("freshness", {}).get("state") is not None
        ),
        "stage_timing_ms": _stage_timing_summary(events),
    }


def _adjacent_switch_count(values: list[Any]) -> int:
    return sum(1 for before, after in zip(values, values[1:]) if before != after)


def _source_timestamp_ms(event: dict[str, Any]) -> float | None:
    left = _float_or_none(event.get("left_capture_timestamp_us"))
    right = _float_or_none(event.get("right_capture_timestamp_us"))
    values = [value for value in (left, right) if value is not None]
    if not values:
        return None
    return min(values) / 1000.0


def _event_timestamp_ms(event: dict[str, Any]) -> float | None:
    timestamp_ms = _float_or_none(event.get("timestamp_ms"))
    if timestamp_ms is not None:
        return timestamp_ms
    return _source_timestamp_ms(event)


def _timeline(events: list[dict[str, Any]], raw_status: dict[str, Any], pcmr_status: dict[str, Any]) -> dict[str, Any]:
    accepted = [event for event in events if event.get("event") == "accepted"]
    accepted_times = [value for value in (_event_timestamp_ms(event) for event in accepted) if value is not None]
    source_times = [value for value in (_source_timestamp_ms(event) for event in accepted) if value is not None]
    accepted_hz = None
    if len(accepted_times) >= 2:
        span_s = (max(accepted_times) - min(accepted_times)) / 1000.0
        accepted_hz = len(accepted_times) / span_s if span_s > 0 else None
    left_frame_ids = [_int_or_none(event.get("left_frame_id")) for event in events]
    left_frame_ids = [value for value in left_frame_ids if value is not None]
    right_frame_ids = [_int_or_none(event.get("right_frame_id")) for event in events]
    right_frame_ids = [value for value in right_frame_ids if value is not None]
    source_frame_hz = None
    if len(source_times) >= 2 and left_frame_ids:
        span_s = (max(source_times) - min(source_times)) / 1000.0
        source_frame_hz = (max(left_frame_ids) - min(left_frame_ids)) / span_s if span_s > 0 else None
    raw_realtime = raw_status.get("realtime") if isinstance(raw_status.get("realtime"), dict) else {}
    trace_sequence_gaps = 0
    accepted_sequences = [_int_or_none(event.get("sequence")) for event in accepted]
    accepted_sequences = [value for value in accepted_sequences if value is not None]
    for before, after in zip(accepted_sequences, accepted_sequences[1:]):
        if after > before + 1:
            trace_sequence_gaps += 1
    return {
        "source_frame_hz": source_frame_hz,
        "accepted_hz": accepted_hz,
        "publish_interval_ms": _interval_summary(accepted_times),
        "source_update_interval_ms": _interval_summary(source_times),
        "raw_stream": {
            "observed_packet_hz": raw_realtime.get("observed_packet_hz"),
            "expected_source_hz": raw_realtime.get("expected_source_hz"),
            "mean_interval_ms": raw_realtime.get("mean_interval_ms"),
            "late_interval_count": raw_realtime.get("late_interval_count"),
            "packet_drop_count": raw_realtime.get("packet_drop_count"),
        },
        "packet_gap": {
            "trace_sequence_gap_count": trace_sequence_gaps,
            "raw_sequence_gap_count": raw_realtime.get("sequence_gap_count"),
            "raw_packet_drop_count": raw_realtime.get("packet_drop_count"),
        },
        "godot_card": {
            "packets": pcmr_status.get("packets"),
            "live": pcmr_status.get("live"),
            "sequence": pcmr_status.get("sequence"),
            "card_apply_count": pcmr_status.get("card_apply_count"),
            "card_target_id": pcmr_status.get("card_target_id"),
            "card_attach_target_id": pcmr_status.get("card_attach_target_id"),
            "card_node_position": pcmr_status.get("card_node_position"),
            "card_resolved_position": pcmr_status.get("card_resolved_position"),
            "apply_hz": None,
            "card_pose_update_hz": None,
            "rate_note": "single Godot status snapshot cannot compute apply/card pose update hz",
        },
    }


def _depth_jump_segments(events: list[dict[str, Any]], pcmr_status: dict[str, Any], *, top_n: int, context_radius: int) -> list[dict[str, Any]]:
    accepted = [event for event in events if event.get("event") == "accepted" and event.get("depth_m") is not None]
    jumps: list[dict[str, Any]] = []
    for before, after in zip(accepted, accepted[1:]):
        delta = abs(float(after["depth_m"]) - float(before["depth_m"]))
        jumps.append(
            {
                "type": "depth_jump",
                "sequence": after.get("sequence"),
                "delta_m": delta,
                "from_depth_m": before.get("depth_m"),
                "to_depth_m": after.get("depth_m"),
                "context": _context(events, int(after["index"]), context_radius, pcmr_status),
            }
        )
    return sorted(jumps, key=lambda item: float(item["delta_m"]), reverse=True)[:top_n]


def _publish_stall_segments(
    events: list[dict[str, Any]],
    pcmr_status: dict[str, Any],
    *,
    top_n: int,
    context_radius: int,
    expected_source_hz: float,
) -> list[dict[str, Any]]:
    accepted = [event for event in events if event.get("event") == "accepted"]
    threshold_ms = (1000.0 / max(0.1, expected_source_hz)) * 1.5
    stalls: list[dict[str, Any]] = []
    for before, after in zip(accepted, accepted[1:]):
        before_ms = _event_timestamp_ms(before)
        after_ms = _event_timestamp_ms(after)
        if before_ms is None or after_ms is None:
            continue
        interval = after_ms - before_ms
        if interval > threshold_ms:
            stalls.append(
                {
                    "type": "publish_stall",
                    "sequence": after.get("sequence"),
                    "interval_ms": interval,
                    "threshold_ms": threshold_ms,
                    "context": _context(events, int(after["index"]), context_radius, pcmr_status),
                }
            )
    return sorted(stalls, key=lambda item: float(item["interval_ms"]), reverse=True)[:top_n]


def _reason_segments(
    events: list[dict[str, Any]],
    pcmr_status: dict[str, Any],
    *,
    reason: str,
    top_n: int,
    context_radius: int,
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for event in events:
        if event.get("reason") == reason or event.get("switch_reason") == reason:
            segments.append(
                {
                    "type": reason,
                    "sequence": event.get("sequence"),
                    "reason": reason,
                    "context": _context(events, int(event["index"]), context_radius, pcmr_status),
                }
            )
    return segments[:top_n]


def _temporal_mismatch_segments(
    events: list[dict[str, Any]],
    pcmr_status: dict[str, Any],
    *,
    top_n: int,
    context_radius: int,
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    previous_count = 0
    for event in events:
        count = _int_or_none(event.get("temporal_mismatch_count")) or previous_count
        if event.get("reason") == "temporal_mismatch" or count > previous_count:
            segments.append(
                {
                    "type": "temporal_mismatch",
                    "sequence": event.get("sequence"),
                    "reason": "temporal_mismatch",
                    "temporal_mismatch_count": count,
                    "previous_temporal_mismatch_count": previous_count,
                    "pair_capture_delta_ms": event.get("pair_capture_delta_ms"),
                    "context": _context(events, int(event["index"]), context_radius, pcmr_status),
                }
            )
        previous_count = max(previous_count, count)
    return segments[:top_n]


def _raw_pair_switch_segments(events: list[dict[str, Any]], pcmr_status: dict[str, Any], *, top_n: int, context_radius: int) -> list[dict[str, Any]]:
    accepted = [event for event in events if event.get("event") == "accepted"]
    switches: list[dict[str, Any]] = []
    for before, after in zip(accepted, accepted[1:]):
        if before.get("raw_track_pair") and after.get("raw_track_pair") and before.get("raw_track_pair") != after.get("raw_track_pair"):
            switches.append(
                {
                    "type": "raw_pair_switch",
                    "sequence": after.get("sequence"),
                    "from_raw_track_pair": before.get("raw_track_pair"),
                    "to_raw_track_pair": after.get("raw_track_pair"),
                    "context": _context(events, int(after["index"]), context_radius, pcmr_status),
                }
            )
    return switches[:top_n]


def _segments(events: list[dict[str, Any]], raw_status: dict[str, Any], pcmr_status: dict[str, Any], *, top_n: int, context_radius: int) -> dict[str, Any]:
    raw_realtime = raw_status.get("realtime") if isinstance(raw_status.get("realtime"), dict) else {}
    expected_hz = _float_or_none(raw_realtime.get("expected_source_hz")) or 45.0
    return {
        "depth_jump": _depth_jump_segments(events, pcmr_status, top_n=top_n, context_radius=context_radius),
        "publish_stall": _publish_stall_segments(
            events,
            pcmr_status,
            top_n=top_n,
            context_radius=context_radius,
            expected_source_hz=expected_hz,
        ),
        "held_missing": _reason_segments(events, pcmr_status, reason="held_missing", top_n=top_n, context_radius=context_radius),
        "raw_pair_switch": _raw_pair_switch_segments(events, pcmr_status, top_n=top_n, context_radius=context_radius),
        "no_target": _reason_segments(events, pcmr_status, reason="no_target", top_n=top_n, context_radius=context_radius),
        "temporal_mismatch": _temporal_mismatch_segments(events, pcmr_status, top_n=top_n, context_radius=context_radius),
    }


def _verdicts(
    trace_summary: dict[str, Any],
    timeline: dict[str, Any],
    raw_status: dict[str, Any],
    pcmr_status: dict[str, Any],
    sender_clients: dict[str, Any],
) -> list[str]:
    verdicts: list[str] = []
    pair_summary = trace_summary.get("pair_capture_delta_ms", {})
    if pair_summary.get("count", 0) and (pair_summary.get("p95") or 0) <= 10.0:
        verdicts.append("TIMESTAMP_SYNC_OK")
    raw_realtime = raw_status.get("realtime") if isinstance(raw_status.get("realtime"), dict) else {}
    expected_hz = _float_or_none(raw_realtime.get("expected_source_hz")) or 45.0
    accepted_hz = _float_or_none(timeline.get("accepted_hz"))
    raw_hz = _float_or_none(raw_realtime.get("observed_packet_hz"))
    if (accepted_hz is not None and accepted_hz < expected_hz * 0.5) or (raw_hz is not None and raw_hz < expected_hz * 0.5):
        verdicts.append("PUBLISH_RATE_LOW")
    confidences = trace_summary.get("depth_confidences", {})
    raw_confidences = raw_status.get("depth_confidences", {})
    if confidences == {"low": trace_summary.get("accepted_count")} or raw_confidences == {"low": raw_status.get("packets")}:
        verdicts.append("LOW_CONFIDENCE_DEPTH_ONLY")
    if _float_or_none(trace_summary.get("held_last_pose_ratio")) and float(trace_summary["held_last_pose_ratio"]) >= 0.2:
        verdicts.append("HELD_POSE_TOO_MUCH")
    if int(trace_summary.get("raw_track_switch_count", 0)) > 0:
        verdicts.append("RAW_PAIR_SWITCHING")
    last_disconnect = sender_clients.get("last_disconnect")
    active_clients = sender_clients.get("active_clients", [])
    has_active_godot = any(str(client.get("label", "")).lower() == "godot" for client in active_clients if isinstance(client, dict))
    if (isinstance(last_disconnect, dict) and str(last_disconnect.get("label", "")).lower() == "godot") or not has_active_godot:
        verdicts.append("GODOT_CLIENT_DISCONNECTED_OR_LABEL_AMBIGUOUS")
    card_target_id = str(pcmr_status.get("card_target_id", ""))
    if not card_target_id.startswith("vst_stereo-") or pcmr_status.get("card_resolved_position") in {None, "0.50 0.25 -1.20"}:
        verdicts.append("CARD_POSE_STALE")
    return verdicts


def analyze_live_run_diagnostics(
    *,
    depth_trace_path: Path,
    raw_status_path: Path | None,
    pcmr_status_path: Path | None,
    sender_log_path: Path | None,
    output_path: Path,
    top_n: int = 10,
    context_radius: int = 5,
) -> dict[str, Any]:
    raw_status = _load_json(raw_status_path)
    pcmr_status = _load_json(pcmr_status_path)
    sender_clients = _parse_sender_clients(_read_log(sender_log_path))
    events = [_normalize_event(row, index) for index, row in enumerate(_iter_jsonl(depth_trace_path))]
    trace_summary = _trace_summary(events)
    timeline = _timeline(events, raw_status, pcmr_status)
    report = {
        "schema_version": 1,
        "generated_at_ms": int(time.time() * 1000),
        "inputs": {
            "depth_trace": str(depth_trace_path),
            "raw_status": None if raw_status_path is None else str(raw_status_path),
            "pcmr_status": None if pcmr_status_path is None else str(pcmr_status_path),
            "sender_log": None if sender_log_path is None else str(sender_log_path),
        },
        "verdicts": _verdicts(trace_summary, timeline, raw_status, pcmr_status, sender_clients),
        "trace": trace_summary,
        "timeline": timeline,
        "segments": _segments(events, raw_status, pcmr_status, top_n=max(1, top_n), context_radius=max(0, context_radius)),
        "sender_clients": sender_clients,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate run-level diagnostics for a stereo proxy_targets live run.")
    parser.add_argument("--depth-trace", type=Path, required=True)
    parser.add_argument("--raw-status", type=Path, default=None)
    parser.add_argument("--pcmr-status", type=Path, default=None)
    parser.add_argument("--sender-log", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--context-radius", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    analyze_live_run_diagnostics(
        depth_trace_path=args.depth_trace,
        raw_status_path=args.raw_status,
        pcmr_status_path=args.pcmr_status,
        sender_log_path=args.sender_log,
        output_path=args.output,
        top_n=args.top_n,
        context_radius=args.context_radius,
    )
    print(json.dumps({"live_run_diagnostics_json": str(args.output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
