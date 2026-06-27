from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
_ROOT = TOOLS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from collect_stereo_bbox_pairs import (  # noqa: E402
    StereoActiveTargetStabilizer,
    _create_stereo_readers_and_trackers,
    build_stereo_bbox_pair_record,
)
from dump_antman_vst_humantrackor_jsonl import DEFAULT_ANTMAN_ROOT, startup_error_status  # noqa: E402
from smartxr.publisher import normalize_source_payload  # noqa: E402
from smartxr.stereo_depth import (  # noqa: E402
    ANCHOR_KIND_BBOX_TOP_CENTER,
    SCENE_STEREO_28,
    StereoDetectionPair,
    StereoGateConfig,
    triangulate_detection_pair,
)
from smartxr.transport import (  # noqa: E402
    drain_client_frames as _drain_client_frames,
    encode_websocket_text_frame,
    handshake as _handshake,
)


_DEPTH_TRACE_CONTEXT: dict[int, dict[str, Any]] = {}
DEFAULT_MAX_PAIR_CAPTURE_DELTA_MS = 10.0
DEFAULT_SOURCE_HZ = 45.0


def is_proxy_targets_request(first_line: str) -> bool:
    parts = first_line.split()
    if len(parts) < 2:
        return False
    return parts[1].split("?", 1)[0] == "/proxy_targets"


class ClientInfo:
    def __init__(self, conn: Any, address: Any, client_id: str, label: str) -> None:
        self.conn = conn
        self.address = address
        self.client_id = client_id
        self.label = label


def _format_address(address: Any) -> str:
    if isinstance(address, tuple) and len(address) >= 2:
        return f"{address[0]}:{address[1]}"
    return str(address)


def _disconnect_reason(exc: BaseException | None) -> str:
    if exc is None:
        return "client_closed"
    if isinstance(exc, ConnectionResetError):
        return "connection_reset"
    if isinstance(exc, BrokenPipeError):
        return "broken_pipe"
    return type(exc).__name__


class BroadcastHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: list[ClientInfo] = []
        self._next_client_index = 1
        self._last_disconnect: dict[str, Any] | None = None

    def add_client(self, conn: Any, address: Any, label: str = "unknown") -> str:
        with self._lock:
            client_id = f"client-{self._next_client_index}"
            self._next_client_index += 1
            self._clients.append(ClientInfo(conn=conn, address=address, client_id=client_id, label=label))
            return client_id

    def remove_client(self, conn: Any, reason: str = "client_closed") -> dict[str, Any] | None:
        with self._lock:
            removed = next((client for client in self._clients if client.conn is conn), None)
            self._clients = [client for client in self._clients if client.conn is not conn]
            if removed is None:
                return None
            self._last_disconnect = {
                "client_id": removed.client_id,
                "label": removed.label,
                "address": _format_address(removed.address),
                "reason": reason,
            }
            return dict(self._last_disconnect)

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def status_summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active_client_count": len(self._clients),
                "active_clients": [
                    f"{client.client_id}={client.label}@{_format_address(client.address)}" for client in self._clients
                ],
                "last_disconnect": dict(self._last_disconnect) if self._last_disconnect else None,
            }

    def broadcast(self, message: dict[str, Any]) -> int:
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        frame = encode_websocket_text_frame(payload)
        stale: list[tuple[Any, str]] = []
        delivered = 0
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.conn.sendall(frame)
                delivered += 1
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                stale.append((client.conn, _disconnect_reason(exc)))
        for conn, reason in stale:
            self.remove_client(conn, reason=reason)
        return delivered


def _empty_diagnostics(reason: str) -> dict[str, Any]:
    return {
        "reason": reason,
        "read_attempts": 0,
        "frames_seen_left": 0,
        "frames_seen_right": 0,
        "last_pair_frame_id": -1,
        "left_pending": 0,
        "right_pending": 0,
        "stereo_rejection_reason": None,
        "left_source_stats": {},
        "right_source_stats": {},
        "sync": {
            "pairing_strategy": "none",
            "max_pair_capture_delta_ms": DEFAULT_MAX_PAIR_CAPTURE_DELTA_MS,
            "temporal_mismatch_count": 0,
            "dropped_left_frames": 0,
            "dropped_right_frames": 0,
        },
        "realtime": {
            "target_source_hz": DEFAULT_SOURCE_HZ,
            "expected_frame_interval_ms": 1000.0 / DEFAULT_SOURCE_HZ,
            "frames_seen_left": 0,
            "frames_seen_right": 0,
            "estimated_left_dropped_frames": 0,
            "estimated_right_dropped_frames": 0,
        },
    }


def format_stereo_diagnostics(diagnostics: dict[str, Any]) -> str:
    return (
        "stereo diagnostics: reason=%s reads=%d left_frames=%d right_frames=%d "
        "last_pair_frame_id=%s left_pending=%d right_pending=%d stereo_rejection=%s"
        % (
            diagnostics.get("reason", "-"),
            int(diagnostics.get("read_attempts", 0)),
            int(diagnostics.get("frames_seen_left", 0)),
            int(diagnostics.get("frames_seen_right", 0)),
            diagnostics.get("last_pair_frame_id", -1),
            int(diagnostics.get("left_pending", 0)),
            int(diagnostics.get("right_pending", 0)),
            diagnostics.get("stereo_rejection_reason") or "-",
        )
    )


def _read_one_eye(
    reader: Any,
    pending: dict[int, Any],
    seen: set[int],
    received_at_ms: dict[int, float] | None = None,
) -> int:
    ok, frame_id, frame = reader.read_latest()
    if not ok:
        return 1
    if frame is None or int(frame_id) < 0:
        return 0
    frame_key = int(frame_id)
    if frame_key not in seen:
        seen.add(frame_key)
        pending[frame_key] = frame
        if received_at_ms is not None:
            received_at_ms[frame_key] = time.monotonic() * 1000.0
    return 0


def _numeric_attr_or_key(value: Any, names: tuple[str, ...]) -> float | None:
    for name in names:
        source = None
        if isinstance(value, dict):
            source = value.get(name)
        elif hasattr(value, name):
            source = getattr(value, name)
        try:
            if source is not None:
                return float(source)
        except (TypeError, ValueError):
            continue
    return None


def _frame_timestamp_us(frame: Any) -> int | None:
    timestamp_us = _numeric_attr_or_key(
        frame,
        ("timestamp_us", "capture_timestamp_us", "ts_us", "timestampUsec", "timestamp_usec"),
    )
    if timestamp_us is not None:
        return int(round(timestamp_us))
    timestamp_ms = _numeric_attr_or_key(
        frame,
        ("timestamp_ms", "capture_timestamp_ms", "ts_ms", "timestampMillis"),
    )
    if timestamp_ms is not None:
        return int(round(timestamp_ms * 1000.0))
    return None


def _tracking_latency_ms(result: Any) -> float | None:
    return _numeric_attr_or_key(result, ("frame_latency_ms", "latency_ms", "processing_latency_ms"))


def _frame_id_drop_count(seen: set[int]) -> int:
    if not seen:
        return 0
    return max(0, max(seen) - min(seen) + 1 - len(seen))


def _update_realtime_diagnostics(
    diagnostics: dict[str, Any],
    *,
    seen_left: set[int],
    seen_right: set[int],
    target_source_hz: float = DEFAULT_SOURCE_HZ,
) -> None:
    diagnostics["realtime"] = {
        "target_source_hz": float(target_source_hz),
        "expected_frame_interval_ms": 1000.0 / max(float(target_source_hz), 0.1),
        "frames_seen_left": len(seen_left),
        "frames_seen_right": len(seen_right),
        "left_frame_min": min(seen_left) if seen_left else None,
        "left_frame_max": max(seen_left) if seen_left else None,
        "right_frame_min": min(seen_right) if seen_right else None,
        "right_frame_max": max(seen_right) if seen_right else None,
        "estimated_left_dropped_frames": _frame_id_drop_count(seen_left),
        "estimated_right_dropped_frames": _frame_id_drop_count(seen_right),
    }


def _select_next_pair_by_sync(
    *,
    pending_left: dict[int, Any],
    pending_right: dict[int, Any],
    pending_left_received_at_ms: dict[int, float] | None = None,
    pending_right_received_at_ms: dict[int, float] | None = None,
    max_pair_capture_delta_ms: float | None,
    diagnostics: dict[str, Any],
) -> tuple[int, int] | None:
    if not pending_left or not pending_right:
        return None

    timestamped_pairs: list[tuple[float, int, int]] = []
    for left_id, left_frame in pending_left.items():
        left_ts = _frame_timestamp_us(left_frame)
        if left_ts is None:
            continue
        for right_id, right_frame in pending_right.items():
            right_ts = _frame_timestamp_us(right_frame)
            if right_ts is None:
                continue
            timestamped_pairs.append((abs(float(left_ts) - float(right_ts)) / 1000.0, left_id, right_id))

    if timestamped_pairs:
        best_delta_ms, left_id, right_id = min(timestamped_pairs, key=lambda item: item[0])
        sync = diagnostics.setdefault("sync", {})
        sync["pairing_strategy"] = "capture_timestamp"
        sync["best_pair_capture_delta_ms"] = best_delta_ms
        sync["max_pair_capture_delta_ms"] = max_pair_capture_delta_ms
        if max_pair_capture_delta_ms is None or best_delta_ms <= float(max_pair_capture_delta_ms):
            return left_id, right_id
        left_ts = _frame_timestamp_us(pending_left[left_id])
        right_ts = _frame_timestamp_us(pending_right[right_id])
        if left_ts is not None and right_ts is not None and left_ts <= right_ts:
            pending_left.pop(left_id, None)
            if pending_left_received_at_ms is not None:
                pending_left_received_at_ms.pop(left_id, None)
            sync["dropped_left_frames"] = int(sync.get("dropped_left_frames", 0)) + 1
        else:
            pending_right.pop(right_id, None)
            if pending_right_received_at_ms is not None:
                pending_right_received_at_ms.pop(right_id, None)
            sync["dropped_right_frames"] = int(sync.get("dropped_right_frames", 0)) + 1
        sync["temporal_mismatch_count"] = int(sync.get("temporal_mismatch_count", 0)) + 1
        diagnostics["reason"] = "temporal_mismatch"
        diagnostics["stereo_rejection_reason"] = "temporal_mismatch"
        return None

    common_frame_ids = sorted(set(pending_left).intersection(pending_right))
    if common_frame_ids:
        diagnostics.setdefault("sync", {})["pairing_strategy"] = "frame_id"
        frame_id = common_frame_ids[0]
        return frame_id, frame_id
    return None


def _pair_temporal_diagnostics(
    *,
    left_frame_id: int,
    right_frame_id: int,
    left_frame: Any,
    right_frame: Any,
    left_received_at_ms: float | None,
    right_received_at_ms: float | None,
    left_tracking_result: Any,
    right_tracking_result: Any,
) -> dict[str, Any]:
    left_timestamp_us = _frame_timestamp_us(left_frame)
    right_timestamp_us = _frame_timestamp_us(right_frame)
    temporal: dict[str, Any] = {
        "left_frame_id": int(left_frame_id),
        "right_frame_id": int(right_frame_id),
        "frame_id_delta": int(left_frame_id) - int(right_frame_id),
        "left_capture_timestamp_us": left_timestamp_us,
        "right_capture_timestamp_us": right_timestamp_us,
        "left_receive_monotonic_ms": left_received_at_ms,
        "right_receive_monotonic_ms": right_received_at_ms,
        "left_tracker_latency_ms": _tracking_latency_ms(left_tracking_result),
        "right_tracker_latency_ms": _tracking_latency_ms(right_tracking_result),
    }
    if left_timestamp_us is not None and right_timestamp_us is not None:
        temporal["pair_capture_delta_ms"] = abs(float(left_timestamp_us) - float(right_timestamp_us)) / 1000.0
    else:
        temporal["pair_capture_delta_ms"] = None
    if left_received_at_ms is not None and right_received_at_ms is not None:
        temporal["pair_receive_delta_ms"] = abs(float(left_received_at_ms) - float(right_received_at_ms))
    else:
        temporal["pair_receive_delta_ms"] = None
    return temporal


def _bbox_dict_from_xyxy(bbox_xyxy: list[float] | tuple[float, float, float, float]) -> dict[str, float]:
    x1, y1, x2, y2 = (float(value) for value in bbox_xyxy)
    return {
        "cx": (x1 + x2) * 0.5,
        "cy": (y1 + y2) * 0.5,
        "w": x2 - x1,
        "h": y2 - y1,
    }


def _record_to_pair(record: dict[str, Any]) -> StereoDetectionPair:
    return StereoDetectionPair(
        pair_id=str(record["pair_id"]),
        frame_id=int(record["frame_id"]),
        person_id=str(record["person_id"]),
        left_bbox_xyxy=tuple(float(value) for value in record["left_bbox_xyxy"]),
        right_bbox_xyxy=tuple(float(value) for value in record["right_bbox_xyxy"]),
        confidence=float(record.get("confidence", 1.0)),
    )


def build_proxy_targets_message_from_stereo_bbox_record(
    record: dict[str, Any],
    *,
    sequence: int,
    card_id: str = "CardAnchor",
    recorded_width: int = 880,
    recorded_height: int = 660,
    min_confidence: float = 0.5,
    min_depth_m: float = 0.2,
    max_depth_m: float = 5.0,
    min_box_ratio: float = 0.5,
    max_box_ratio: float = 2.0,
    max_vertical_error_px: float | None = None,
) -> dict[str, Any] | None:
    calibration = SCENE_STEREO_28.scaled_to(recorded_width, recorded_height)
    gate_config = StereoGateConfig(
        min_confidence=min_confidence,
        min_depth_m=min_depth_m,
        max_depth_m=max_depth_m,
        min_box_ratio=min_box_ratio,
        max_box_ratio=max_box_ratio,
        max_vertical_error_px=max_vertical_error_px,
    )
    stereo_record = triangulate_detection_pair(
        _record_to_pair(record),
        calibration,
        anchor_kind=ANCHOR_KIND_BBOX_TOP_CENTER,
        gate_config=gate_config,
    )
    if stereo_record.get("stereo_ok") is not True:
        return None

    left_bbox = list(record["left_bbox_xyxy"])
    source_payload = {
        "source": "vst_stereo",
        "timestamp_ms": int(record.get("timestamp_ms", time.time() * 1000)),
        "image": {
            "w": int(recorded_width),
            "h": int(recorded_height),
            "camera": {
                "coordinate_space": "vst_camera_left",
                "fx": calibration.left.fx,
                "fy": calibration.left.fy,
                "cx": calibration.left.cx,
                "cy": calibration.left.cy,
                "horizontal_fov_deg": calibration.left.horizontal_fov_deg,
                "vertical_fov_deg": calibration.left.vertical_fov_deg,
            },
        },
        "detections": [
            {
                "target_id": str(record["person_id"]),
                "track_id": str(record["person_id"]),
                "confidence": float(record.get("confidence", 1.0)),
                "bbox": _bbox_dict_from_xyxy(left_bbox),
                "depth_m": float(stereo_record["depth_m"]),
                "depth_source": "bbox_top_center_fallback",
                "depth_confidence": "low",
                "stereo": {
                    "pair_id": stereo_record["pair_id"],
                    "frame_id": stereo_record["frame_id"],
                    "depth_source": stereo_record["depth_source"],
                    "anchor_kind": stereo_record["anchor_kind"],
                    "left_anchor_px": stereo_record["left_anchor_px"],
                    "right_anchor_px": stereo_record["right_anchor_px"],
                    "disparity_px": stereo_record["disparity_px"],
                    "vertical_error_px": stereo_record["vertical_error_px"],
                    "calibration_ref": stereo_record["calibration_ref"],
                },
            }
        ],
    }
    message = normalize_source_payload(source_payload, sequence=sequence, card_id=card_id)
    if not message["targets"]:
        return None
    detection = source_payload["detections"][0]
    _DEPTH_TRACE_CONTEXT[id(message)] = {
        "bbox": detection["bbox"],
        "stereo": detection["stereo"],
        "selection": dict(record.get("selection", {})),
    }
    return message


def _vector3_from_mapping(value: Any) -> list[float] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return [float(value[0]), float(value[1]), float(value[2])]
        except (TypeError, ValueError):
            return None
    if not isinstance(value, dict):
        return None
    try:
        return [float(value["x"]), float(value["y"]), float(value["z"])]
    except (KeyError, TypeError, ValueError):
        return None


def build_depth_trace_event(
    *,
    message: dict[str, Any] | None,
    diagnostics: dict[str, Any],
    sequence: int | None = None,
    delivered_clients: int | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "timestamp_ms": int(time.time() * 1000),
        "reason": diagnostics.get("reason", "-"),
        "read_attempts": diagnostics.get("read_attempts", 0),
        "frames_seen_left": diagnostics.get("frames_seen_left", 0),
        "frames_seen_right": diagnostics.get("frames_seen_right", 0),
        "left_pending": diagnostics.get("left_pending", 0),
        "right_pending": diagnostics.get("right_pending", 0),
        "stereo_rejection_reason": diagnostics.get("stereo_rejection_reason"),
        "left_source_stats": diagnostics.get("left_source_stats", {}),
        "right_source_stats": diagnostics.get("right_source_stats", {}),
        "sync": diagnostics.get("sync", {}),
        "realtime": diagnostics.get("realtime", {}),
    }
    if delivered_clients is not None:
        event["delivered_clients"] = delivered_clients
    temporal = diagnostics.get("temporal")
    if isinstance(temporal, dict):
        event["temporal"] = dict(temporal)
        for key in (
            "left_capture_timestamp_us",
            "right_capture_timestamp_us",
            "left_receive_monotonic_ms",
            "right_receive_monotonic_ms",
            "pair_capture_delta_ms",
            "pair_receive_delta_ms",
            "frame_id_delta",
            "left_tracker_latency_ms",
            "right_tracker_latency_ms",
        ):
            if key in temporal:
                event[key] = temporal[key]

    if message is None or not message.get("targets"):
        frame_id = diagnostics.get("last_pair_frame_id")
        left_frame_id = temporal.get("left_frame_id") if isinstance(temporal, dict) else frame_id
        right_frame_id = temporal.get("right_frame_id") if isinstance(temporal, dict) else frame_id
        event.update(
            {
                "event": "rejected",
                "sequence": sequence,
                "left_frame_id": left_frame_id,
                "right_frame_id": right_frame_id,
            }
        )
        return event

    target = message["targets"][0]
    trace_context = _DEPTH_TRACE_CONTEXT.pop(id(message), {})
    source_coordinate = target.get("source_coordinate", {})
    source_frame = source_coordinate.get("source_frame", {})
    stereo = trace_context.get("stereo", target.get("stereo", {}))
    stereo_frame_id = stereo.get("frame_id", diagnostics.get("last_pair_frame_id"))
    left_frame_id = temporal.get("left_frame_id") if isinstance(temporal, dict) else stereo_frame_id
    right_frame_id = temporal.get("right_frame_id") if isinstance(temporal, dict) else stereo_frame_id
    depth_m = source_frame.get("anchor_depth")
    if depth_m is None:
        depth_m = source_coordinate.get("depth_m")
    try:
        depth_m = float(depth_m)
    except (TypeError, ValueError):
        depth_m = None

    event.update(
        {
            "event": "accepted",
            "sequence": message.get("sequence"),
            "target_id": target.get("target_id"),
            "card_id": message.get("cards", [{}])[0].get("card_id"),
            "left_frame_id": left_frame_id,
            "right_frame_id": right_frame_id,
            "depth_m": depth_m,
            "depth_source": target.get("depth_source") or source_coordinate.get("depth_source"),
            "depth_confidence": target.get("depth_confidence") or source_coordinate.get("depth_confidence"),
            "source_frame": source_frame,
            "camera_point_m": _vector3_from_mapping(source_coordinate.get("camera_point_m")),
            "head_position_m": _vector3_from_mapping(source_coordinate.get("head_position_m")),
            "bbox": trace_context.get("bbox", target.get("bbox", {})),
            "stereo": stereo,
        }
    )
    selection = trace_context.get("selection") or diagnostics
    for key in (
        "active_target_id",
        "raw_left_track_id",
        "raw_right_track_id",
        "raw_person_id",
        "candidate_count",
        "selected_score",
        "switch_count",
        "switch_reason",
        "active_age_frames",
        "held_last_pose",
    ):
        if key in selection:
            event[key] = selection[key]
    return event


def write_depth_trace_event(trace_path: Path | None, event: dict[str, Any]) -> None:
    if trace_path is None:
        return
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def next_live_stereo_proxy_targets_message_with_diagnostics(
    *,
    left_reader: Any,
    right_reader: Any,
    left_tracker: Any,
    right_tracker: Any,
    sequence: int,
    card_id: str = "CardAnchor",
    recorded_width: int = 880,
    recorded_height: int = 660,
    min_confidence: float = 0.5,
    max_empty_reads: int | None = None,
    max_read_attempts: int | None = None,
    sleep_seconds: float = 0.005,
    max_vertical_error_px: float | None = None,
    target_stabilizer: StereoActiveTargetStabilizer | None = None,
    max_pair_capture_delta_ms: float | None = DEFAULT_MAX_PAIR_CAPTURE_DELTA_MS,
    target_source_hz: float = DEFAULT_SOURCE_HZ,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    attempts = max_read_attempts if max_read_attempts is not None else max_empty_reads
    diagnostics = _empty_diagnostics("no_pair")
    pending_left: dict[int, Any] = {}
    pending_right: dict[int, Any] = {}
    pending_left_received_at_ms: dict[int, float] = {}
    pending_right_received_at_ms: dict[int, float] = {}
    seen_left: set[int] = set()
    seen_right: set[int] = set()
    diagnostics["sync"]["max_pair_capture_delta_ms"] = max_pair_capture_delta_ms
    for _ in range(max(1, int(attempts if attempts is not None else 120))):
        diagnostics["read_attempts"] += 1
        _read_one_eye(left_reader, pending_left, seen_left, pending_left_received_at_ms)
        _read_one_eye(right_reader, pending_right, seen_right, pending_right_received_at_ms)
        diagnostics["frames_seen_left"] = len(seen_left)
        diagnostics["frames_seen_right"] = len(seen_right)
        diagnostics["left_pending"] = len(pending_left)
        diagnostics["right_pending"] = len(pending_right)
        diagnostics["left_source_stats"] = left_reader.get_stats() if hasattr(left_reader, "get_stats") else {}
        diagnostics["right_source_stats"] = right_reader.get_stats() if hasattr(right_reader, "get_stats") else {}
        _update_realtime_diagnostics(
            diagnostics,
            seen_left=seen_left,
            seen_right=seen_right,
            target_source_hz=target_source_hz,
        )

        pair_ids = _select_next_pair_by_sync(
            pending_left=pending_left,
            pending_right=pending_right,
            pending_left_received_at_ms=pending_left_received_at_ms,
            pending_right_received_at_ms=pending_right_received_at_ms,
            max_pair_capture_delta_ms=max_pair_capture_delta_ms,
            diagnostics=diagnostics,
        )
        if pair_ids is not None:
            left_frame_id, right_frame_id = pair_ids
            left_frame = pending_left.pop(left_frame_id)
            right_frame = pending_right.pop(right_frame_id)
            left_received_at_ms = pending_left_received_at_ms.pop(left_frame_id, None)
            right_received_at_ms = pending_right_received_at_ms.pop(right_frame_id, None)
            left_tracking_result = left_tracker.process_frame(left_frame)
            right_tracking_result = right_tracker.process_frame(right_frame)
            diagnostics["temporal"] = _pair_temporal_diagnostics(
                left_frame_id=left_frame_id,
                right_frame_id=right_frame_id,
                left_frame=left_frame,
                right_frame=right_frame,
                left_received_at_ms=left_received_at_ms,
                right_received_at_ms=right_received_at_ms,
                left_tracking_result=left_tracking_result,
                right_tracking_result=right_tracking_result,
            )
            record = build_stereo_bbox_pair_record(
                frame_id=left_frame_id,
                left_frame=left_frame,
                right_frame=right_frame,
                left_tracking_result=left_tracking_result,
                right_tracking_result=right_tracking_result,
                timestamp_ms=int(time.time() * 1000),
                left_source_stats=diagnostics["left_source_stats"],
                right_source_stats=diagnostics["right_source_stats"],
                target_stabilizer=target_stabilizer,
            )
            diagnostics["last_pair_frame_id"] = left_frame_id
            if record is None:
                diagnostics["reason"] = "no_target"
                continue
            diagnostics.update(record.get("selection", {}))
            message = build_proxy_targets_message_from_stereo_bbox_record(
                record,
                sequence=sequence,
                card_id=card_id,
                recorded_width=recorded_width,
                recorded_height=recorded_height,
                min_confidence=min_confidence,
                max_vertical_error_px=max_vertical_error_px,
            )
            if message is None:
                diagnostics["reason"] = "stereo_rejected"
                diagnostics["stereo_rejection_reason"] = "gated"
                continue
            diagnostics["reason"] = "target_ready"
            return message, diagnostics
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return None, diagnostics


def _broadcast_loop(
    hub: BroadcastHub,
    *,
    left_reader: Any,
    right_reader: Any,
    left_tracker: Any,
    right_tracker: Any,
    hz: float,
    card_id: str,
    min_confidence: float,
    recorded_width: int,
    recorded_height: int,
    log_every: int,
    max_empty_reads: int,
    max_vertical_error_px: float | None,
    depth_trace: Path | None,
    max_pair_capture_delta_ms: float | None,
    target_source_hz: float,
) -> None:
    interval_s = 1.0 / max(hz, 0.1)
    sequence = 0
    empty_windows = 0
    target_stabilizer = StereoActiveTargetStabilizer()
    while True:
        if hub.client_count() == 0:
            time.sleep(interval_s)
            continue
        message, diagnostics = next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=left_reader,
            right_reader=right_reader,
            left_tracker=left_tracker,
            right_tracker=right_tracker,
            sequence=sequence,
            card_id=card_id,
            recorded_width=recorded_width,
            recorded_height=recorded_height,
            min_confidence=min_confidence,
            max_empty_reads=max_empty_reads,
            max_vertical_error_px=max_vertical_error_px,
            target_stabilizer=target_stabilizer,
            max_pair_capture_delta_ms=max_pair_capture_delta_ms,
            target_source_hz=target_source_hz,
        )
        if message is None:
            empty_windows += 1
            write_depth_trace_event(
                depth_trace,
                build_depth_trace_event(message=None, diagnostics=diagnostics, sequence=sequence),
            )
            if log_every > 0 and empty_windows % log_every == 1:
                print("No stereo target frames available from Left/Right VST SHM + HumanTrackor", flush=True)
                print(format_stereo_diagnostics(diagnostics), flush=True)
            time.sleep(interval_s)
            continue

        empty_windows = 0
        delivered = hub.broadcast(message)
        write_depth_trace_event(
            depth_trace,
            build_depth_trace_event(message=message, diagnostics=diagnostics, delivered_clients=delivered),
        )
        if log_every > 0 and sequence % log_every == 0:
            target = message["targets"][0]
            position = target.get("transform", {}).get("position", [0.0, 0.0, 0.0])
            print(
                "sent stereo seq=%d target=%s depth_source=%s depth_confidence=%s clients=%d pos=%.3f %.3f %.3f"
                % (
                    sequence,
                    target.get("target_id", "-"),
                    target.get("depth_source", "-"),
                    target.get("depth_confidence", "-"),
                    delivered,
                    position[0],
                    position[1],
                    position[2],
                ),
                flush=True,
            )
        sequence += 1
        time.sleep(interval_s)


def _client_loop(conn: socket.socket, address: Any, hub: BroadcastHub) -> None:
    disconnect_reason = "client_closed"
    try:
        while True:
            try:
                if not _drain_client_frames(conn):
                    return
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                disconnect_reason = _disconnect_reason(exc)
                return
            time.sleep(0.05)
    finally:
        disconnect = hub.remove_client(conn, reason=disconnect_reason)
        try:
            conn.close()
        except OSError:
            pass
        if disconnect:
            print(
                "client disconnected: id=%s label=%s address=%s reason=%s"
                % (
                    disconnect["client_id"],
                    disconnect["label"],
                    disconnect["address"],
                    disconnect["reason"],
                ),
                flush=True,
            )
        else:
            print(f"client disconnected: {address}", flush=True)


def serve(args: argparse.Namespace) -> int:
    try:
        left_reader, right_reader, left_tracker, right_tracker = _create_stereo_readers_and_trackers(args)
    except Exception as exc:
        status, exit_code = startup_error_status(exc, Path(".tmp/antman_vst_stereo_proxy_targets_live_publisher.jsonl"))
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")), flush=True)
        return exit_code

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((args.host, args.port))
            server.listen(8)
            print(f"stereo proxy_targets live publisher listening on ws://{args.host}:{args.port}/proxy_targets", flush=True)
            print("source: Left/Right VST SHM + HumanTrackor bbox stereo", flush=True)
            print("waiting for WebSocket client; sent seq appears after a stereo pair passes confidence/depth gates", flush=True)
            hub = BroadcastHub()
            threading.Thread(
                target=_broadcast_loop,
                kwargs={
                    "hub": hub,
                    "left_reader": left_reader,
                    "right_reader": right_reader,
                    "left_tracker": left_tracker,
                    "right_tracker": right_tracker,
                    "hz": args.hz,
                    "card_id": args.card_id,
                    "min_confidence": args.min_confidence,
                    "recorded_width": args.recorded_width,
                    "recorded_height": args.recorded_height,
                    "log_every": args.log_every,
                    "max_empty_reads": args.max_empty_reads,
                    "max_vertical_error_px": args.max_vertical_error_px,
                    "depth_trace": args.depth_trace,
                    "max_pair_capture_delta_ms": args.max_pair_capture_delta_ms,
                    "target_source_hz": args.target_source_hz,
                },
                daemon=True,
            ).start()
            while True:
                conn, address = server.accept()
                ok, first_line = _handshake(conn, allow_request=is_proxy_targets_request)
                if not ok:
                    print(f"rejected {address}: {first_line}", flush=True)
                    conn.close()
                    continue
                label = "godot" if hub.client_count() == 0 else "monitor"
                client_id = hub.add_client(conn, address, label=label)
                print(f"client connected: id={client_id} label={label} address={_format_address(address)} request={first_line}", flush=True)
                threading.Thread(target=_client_loop, args=(conn, address, hub), daemon=True).start()
    finally:
        for reader_name in ("left_reader", "right_reader"):
            reader = locals().get(reader_name)
            if reader is not None and hasattr(reader, "release"):
                reader.release()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish live proxy_targets from Antman Left/Right VST SHM stereo depth.")
    parser.add_argument("--antman-root", type=Path, default=DEFAULT_ANTMAN_ROOT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--card-id", default="CardAnchor")
    parser.add_argument("--log-every", type=int, default=20)
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--max-empty-reads", type=int, default=120)
    parser.add_argument("--max-vertical-error-px", type=float, default=None)
    parser.add_argument("--max-pair-capture-delta-ms", type=float, default=DEFAULT_MAX_PAIR_CAPTURE_DELTA_MS)
    parser.add_argument("--target-source-hz", type=float, default=DEFAULT_SOURCE_HZ)
    parser.add_argument("--depth-trace", type=Path, default=None)
    parser.add_argument("--recorded-width", type=int, default=880)
    parser.add_argument("--recorded-height", type=int, default=660)
    parser.add_argument("--shm-name", default="Antman.VST.AI.v1")
    parser.add_argument("--shm-namespace", default=None)
    parser.add_argument("--wait-timeout-ms", type=int, default=1000)
    parser.add_argument("--wait-for-producer-seconds", type=float, default=10.0)
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--backend", default="ultralytics")
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--device", default=None)
    return parser.parse_args()


def main() -> int:
    return serve(_parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
