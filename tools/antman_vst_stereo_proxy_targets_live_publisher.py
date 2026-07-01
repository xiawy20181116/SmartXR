from __future__ import annotations

import argparse
import copy
import json
import math
import random
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
from collect_stereo_keypoint_pairs import (  # noqa: E402
    _normalize_pose_output_for_bbox,
    build_stereo_keypoint_pair_record,
)
from dump_antman_vst_humantrackor_jsonl import DEFAULT_ANTMAN_ROOT, startup_error_status  # noqa: E402
from smartxr.publisher import normalize_source_payload  # noqa: E402
from smartxr.schema import load_card_offset_rule  # noqa: E402
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
HELD_DEPTH_SOURCE = "held_last_good_depth"
DEFAULT_POSITION_FILTER_MIN_CUTOFF = 1.0
DEFAULT_POSITION_FILTER_BETA = 0.08
DEFAULT_POSITION_FILTER_D_CUTOFF = 1.0
DEFAULT_POSE_MODEL = "yolov8n-pose.pt"
DEFAULT_POSE_IMGSZ = 640
DEFAULT_POSE_CONFIDENCE = 0.25
DEFAULT_MIN_KEYPOINT_SCORE = 0.5
DEFAULT_POSE_ASSOCIATION_MARGIN_PX = 8.0
DEFAULT_MAX_POSE_ASSOCIATION_DISTANCE_PX = 120.0
DEFAULT_KEYPOINT_MAX_HZ = 12.0
DEFAULT_KEYPOINT_REUSE_MAX_AGE_MS = 150.0
BBOX_TOP_CENTER_FALLBACK_DEPTH_SOURCE = "bbox_top_center_fallback"
KEYPOINT_DEPTH_ANCHOR_KINDS = {"shoulder_midpoint", "nose", "ear_midpoint"}
DEPTH_OVERRIDE_MODES = ("real", "fixed", "scale_offset", "noise")


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


class DepthOverrideConfig:
    def __init__(
        self,
        *,
        mode: str = "real",
        fixed_m: float | None = None,
        scale: float = 1.0,
        offset_m: float = 0.0,
        noise_std_m: float = 0.0,
        seed: int = 0,
    ) -> None:
        self.mode = mode
        self.fixed_m = fixed_m
        self.scale = scale
        self.offset_m = offset_m
        self.noise_std_m = noise_std_m
        self.seed = seed

    def normalized_mode(self) -> str:
        mode = str(self.mode).strip().lower()
        return mode if mode in DEPTH_OVERRIDE_MODES else "real"


def apply_depth_override(raw_depth_m: float, config: DepthOverrideConfig | None, *, sequence: int = 0) -> dict[str, Any]:
    raw_depth = max(float(raw_depth_m), 0.001)
    if config is None:
        config = DepthOverrideConfig()
    mode = config.normalized_mode()
    applied_depth = raw_depth
    metadata: dict[str, Any] = {
        "mode": mode,
        "raw_depth_m": raw_depth,
        "applied_depth_m": raw_depth,
    }
    if mode == "fixed":
        applied_depth = raw_depth if config.fixed_m is None else float(config.fixed_m)
        metadata["fixed_m"] = applied_depth
    elif mode == "scale_offset":
        applied_depth = raw_depth * float(config.scale) + float(config.offset_m)
        metadata["scale"] = float(config.scale)
        metadata["offset_m"] = float(config.offset_m)
    elif mode == "noise":
        rng = random.Random(f"{int(config.seed)}:{int(sequence)}")
        noise_m = rng.gauss(0.0, max(float(config.noise_std_m), 0.0))
        applied_depth = raw_depth + noise_m
        metadata["noise_std_m"] = max(float(config.noise_std_m), 0.0)
        metadata["noise_m"] = noise_m
        metadata["seed"] = int(config.seed)
    applied_depth = max(float(applied_depth), 0.001)
    metadata["applied_depth_m"] = applied_depth
    return metadata


def _one_euro_alpha(cutoff_hz: float, dt_s: float) -> float:
    cutoff = max(float(cutoff_hz), 1e-6)
    dt = max(float(dt_s), 1e-6)
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


def _low_pass(current: float, previous: float, alpha: float) -> float:
    return alpha * current + (1.0 - alpha) * previous


class OneEuroScalarFilter:
    def __init__(self, *, min_cutoff: float, beta: float, d_cutoff: float) -> None:
        self.min_cutoff = max(float(min_cutoff), 1e-6)
        self.beta = max(float(beta), 0.0)
        self.d_cutoff = max(float(d_cutoff), 1e-6)
        self._raw_prev: float | None = None
        self._filtered_prev: float | None = None
        self._derivative_prev: float | None = None

    def reset(self) -> None:
        self._raw_prev = None
        self._filtered_prev = None
        self._derivative_prev = None

    def filter(self, value: float, dt_s: float | None) -> float:
        current = float(value)
        if self._raw_prev is None or self._filtered_prev is None or dt_s is None:
            self._raw_prev = current
            self._filtered_prev = current
            self._derivative_prev = 0.0
            return current

        dt = max(float(dt_s), 1e-6)
        derivative = (current - self._raw_prev) / dt
        derivative_alpha = _one_euro_alpha(self.d_cutoff, dt)
        derivative_prev = self._derivative_prev if self._derivative_prev is not None else derivative
        filtered_derivative = _low_pass(derivative, derivative_prev, derivative_alpha)
        cutoff = self.min_cutoff + self.beta * abs(filtered_derivative)
        value_alpha = _one_euro_alpha(cutoff, dt)
        filtered = _low_pass(current, self._filtered_prev, value_alpha)

        self._raw_prev = current
        self._filtered_prev = filtered
        self._derivative_prev = filtered_derivative
        return filtered


class OneEuroVector3Filter:
    def __init__(
        self,
        *,
        min_cutoff: float = DEFAULT_POSITION_FILTER_MIN_CUTOFF,
        beta: float = DEFAULT_POSITION_FILTER_BETA,
        d_cutoff: float = DEFAULT_POSITION_FILTER_D_CUTOFF,
        fallback_hz: float = DEFAULT_SOURCE_HZ,
    ) -> None:
        self.min_cutoff = max(float(min_cutoff), 1e-6)
        self.beta = max(float(beta), 0.0)
        self.d_cutoff = max(float(d_cutoff), 1e-6)
        self.fallback_hz = max(float(fallback_hz), 0.1)
        self._axes = [
            OneEuroScalarFilter(min_cutoff=self.min_cutoff, beta=self.beta, d_cutoff=self.d_cutoff),
            OneEuroScalarFilter(min_cutoff=self.min_cutoff, beta=self.beta, d_cutoff=self.d_cutoff),
            OneEuroScalarFilter(min_cutoff=self.min_cutoff, beta=self.beta, d_cutoff=self.d_cutoff),
        ]
        self._timestamp_ms: float | None = None

    def reset(self) -> None:
        for axis in self._axes:
            axis.reset()
        self._timestamp_ms = None

    def settings(self) -> dict[str, float]:
        return {
            "min_cutoff": self.min_cutoff,
            "beta": self.beta,
            "d_cutoff": self.d_cutoff,
            "fallback_hz": self.fallback_hz,
        }

    def filter(
        self,
        position: list[float] | tuple[float, float, float],
        *,
        timestamp_ms: float | None = None,
        reset: bool = False,
    ) -> tuple[list[float], dict[str, Any]]:
        if reset:
            self.reset()
        raw = [float(position[0]), float(position[1]), float(position[2])]
        if timestamp_ms is None:
            dt_s = None if self._timestamp_ms is None else 1.0 / self.fallback_hz
        elif self._timestamp_ms is None:
            dt_s = None
        else:
            dt_s = max((float(timestamp_ms) - self._timestamp_ms) / 1000.0, 1e-6)
        filtered = [axis.filter(value, dt_s) for axis, value in zip(self._axes, raw)]
        if timestamp_ms is None:
            previous = self._timestamp_ms or 0.0
            self._timestamp_ms = previous + (1000.0 / self.fallback_hz)
        else:
            self._timestamp_ms = float(timestamp_ms)
        diagnostics = {
            "algorithm": "one_euro",
            "enabled": True,
            "dt_ms": None if dt_s is None else dt_s * 1000.0,
            "reset": bool(reset),
            **self.settings(),
        }
        return filtered, diagnostics


class LatestStereoPublishState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest_message: dict[str, Any] | None = None
        self._latest_diagnostics: dict[str, Any] | None = None
        self._latest_update_ms: float | None = None
        self._last_diagnostics: dict[str, Any] | None = None
        self._last_update_ms: float | None = None

    def update(self, *, message: dict[str, Any] | None, diagnostics: dict[str, Any]) -> None:
        now_ms = time.monotonic() * 1000.0
        diagnostics_copy = copy.deepcopy(diagnostics)
        with self._lock:
            self._last_diagnostics = diagnostics_copy
            self._last_update_ms = now_ms
            if message is not None:
                self._latest_message = copy.deepcopy(message)
                self._latest_diagnostics = diagnostics_copy
                self._latest_update_ms = now_ms

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "latest_message": copy.deepcopy(self._latest_message),
                "latest_diagnostics": copy.deepcopy(self._latest_diagnostics),
                "latest_update_ms": self._latest_update_ms,
                "last_diagnostics": copy.deepcopy(self._last_diagnostics),
                "last_update_ms": self._last_update_ms,
            }


def _empty_diagnostics(reason: str) -> dict[str, Any]:
    return {
        "reason": reason,
        "non_publish_reason": reason,
        "non_published_frames": [],
        "stage_timing_ms": {
            "frame_read_ms": 0.0,
            "pair_select_ms": 0.0,
            "left_detect_ms": 0.0,
            "right_detect_ms": 0.0,
            "pair_build_ms": 0.0,
            "stabilizer_ms": 0.0,
            "message_build_ms": 0.0,
            "position_filter_ms": 0.0,
            "publish_ms": None,
            "total_ms": 0.0,
        },
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


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _stage_timing_snapshot(stage_timing: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _copy_json_safe(value) for key, value in stage_timing.items()}


def _append_non_published_frame(
    diagnostics: dict[str, Any],
    *,
    reason: str,
    left_frame_id: int | None = None,
    right_frame_id: int | None = None,
) -> None:
    temporal = diagnostics.get("temporal") if isinstance(diagnostics.get("temporal"), dict) else {}
    stage_timing = diagnostics.get("stage_timing_ms") if isinstance(diagnostics.get("stage_timing_ms"), dict) else {}
    diagnostics.setdefault("non_published_frames", []).append(
        {
            "reason": reason,
            "left_frame_id": left_frame_id if left_frame_id is not None else temporal.get("left_frame_id"),
            "right_frame_id": right_frame_id if right_frame_id is not None else temporal.get("right_frame_id"),
            "left_capture_timestamp_us": temporal.get("left_capture_timestamp_us"),
            "right_capture_timestamp_us": temporal.get("right_capture_timestamp_us"),
            "pair_capture_delta_ms": temporal.get("pair_capture_delta_ms"),
            "pair_receive_delta_ms": temporal.get("pair_receive_delta_ms"),
            "stage_timing_ms": _stage_timing_snapshot(stage_timing),
        }
    )


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
    timestamp_us, _source = _frame_timestamp_info(frame)
    return timestamp_us


def _frame_timestamp_info(frame: Any) -> tuple[int | None, str | None]:
    exposure_timestamp = _numeric_attr_or_key(
        frame,
        ("exposure_timestamp", "exposureTimestamp", "exposure_timestamp_us", "exposureTimestampUs"),
    )
    if exposure_timestamp is not None:
        return int(round(exposure_timestamp)), "frame_exposure_timestamp"
    exposure_us = _numeric_attr_or_key(frame, ("exposure_us", "exposureUsec", "exposure_usec"))
    if exposure_us is not None:
        return int(round(exposure_us)), "frame_exposure_us"
    timestamp_us = _numeric_attr_or_key(
        frame,
        ("timestamp_us", "capture_timestamp_us", "ts_us", "timestampUsec", "timestamp_usec"),
    )
    if timestamp_us is not None:
        return int(round(timestamp_us)), "frame_timestamp_us"
    timestamp_ms = _numeric_attr_or_key(
        frame,
        ("timestamp_ms", "capture_timestamp_ms", "ts_ms", "timestampMillis"),
    )
    if timestamp_ms is not None:
        return int(round(timestamp_ms * 1000.0)), "frame_timestamp_ms"
    return None, None


def _attr_or_key(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    if hasattr(value, name):
        return getattr(value, name)
    return None


def _copy_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _copy_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _frame_header_timestamp_debug(frame: Any) -> dict[str, Any]:
    debug: dict[str, Any] = {}
    available_keys = _attr_or_key(frame, "available_timestamp_keys")
    if available_keys is not None:
        debug["available_timestamp_keys"] = _copy_json_safe(available_keys)
    header_debug = _attr_or_key(frame, "header_timestamp_debug")
    if header_debug is not None:
        debug["header_timestamp_debug"] = _copy_json_safe(header_debug)
    return debug


def _frame_for_tracker(frame: Any) -> Any:
    if not isinstance(frame, dict):
        return frame
    payload = frame.get("payload", frame.get("nv12_payload"))
    if isinstance(payload, bytearray):
        payload = bytes(payload)
    if not isinstance(payload, bytes):
        return frame
    if not all(key in frame for key in ("width", "height", "stride")):
        return frame
    try:
        width = int(frame["width"])
        height = int(frame["height"])
        stride = int(frame["stride"])
    except (TypeError, ValueError):
        return frame

    try:
        import cv2
        import numpy as np
    except Exception as exc:
        raise RuntimeError("VST AI SHM NV12 frames need numpy and opencv-python-headless before tracking") from exc

    yuv = np.frombuffer(payload, dtype=np.uint8).reshape((height * 3 // 2, stride))
    bgr = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_NV12)
    return bgr[:, :width]


def _pair_runtime_timestamp_ms(left_frame: Any, right_frame: Any) -> int:
    left_timestamp_us = _frame_timestamp_us(left_frame)
    right_timestamp_us = _frame_timestamp_us(right_frame)
    timestamps = [value for value in (left_timestamp_us, right_timestamp_us) if value is not None]
    if timestamps:
        return int(min(timestamps) // 1000)
    return int(time.time() * 1000)


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
        diagnostics["non_publish_reason"] = "temporal_mismatch"
        diagnostics["stereo_rejection_reason"] = "temporal_mismatch"
        _append_non_published_frame(
            diagnostics,
            reason="temporal_mismatch",
            left_frame_id=left_id,
            right_frame_id=right_id,
        )
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
    left_timestamp_us, left_timestamp_source = _frame_timestamp_info(left_frame)
    right_timestamp_us, right_timestamp_source = _frame_timestamp_info(right_frame)
    temporal: dict[str, Any] = {
        "left_frame_id": int(left_frame_id),
        "right_frame_id": int(right_frame_id),
        "frame_id_delta": int(left_frame_id) - int(right_frame_id),
        "left_capture_timestamp_us": left_timestamp_us,
        "right_capture_timestamp_us": right_timestamp_us,
        "left_capture_timestamp_source": left_timestamp_source,
        "right_capture_timestamp_source": right_timestamp_source,
        "left_receive_monotonic_ms": left_received_at_ms,
        "right_receive_monotonic_ms": right_received_at_ms,
        "left_tracker_latency_ms": _tracking_latency_ms(left_tracking_result),
        "right_tracker_latency_ms": _tracking_latency_ms(right_tracking_result),
    }
    left_header_debug = _frame_header_timestamp_debug(left_frame)
    if left_header_debug:
        temporal["left_available_timestamp_keys"] = left_header_debug.get("available_timestamp_keys", [])
        temporal["left_header_timestamp_debug"] = left_header_debug.get("header_timestamp_debug", {})
    right_header_debug = _frame_header_timestamp_debug(right_frame)
    if right_header_debug:
        temporal["right_available_timestamp_keys"] = right_header_debug.get("available_timestamp_keys", [])
        temporal["right_header_timestamp_debug"] = right_header_debug.get("header_timestamp_debug", {})
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


def _bbox_top_center_from_xyxy(bbox_xyxy: list[float] | tuple[float, float, float, float]) -> list[float]:
    x1, y1, x2, _y2 = (float(value) for value in bbox_xyxy)
    return [(x1 + x2) * 0.5, y1]


def _positive_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0.0:
        return None
    return parsed


def _record_to_pair(record: dict[str, Any]) -> StereoDetectionPair:
    return StereoDetectionPair(
        pair_id=str(record["pair_id"]),
        frame_id=int(record["frame_id"]),
        person_id=str(record["person_id"]),
        left_bbox_xyxy=tuple(float(value) for value in record["left_bbox_xyxy"]),
        right_bbox_xyxy=tuple(float(value) for value in record["right_bbox_xyxy"]),
        confidence=float(record.get("confidence", 1.0)),
    )


def _xy_pair_or_none(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        return [float(value[0]), float(value[1])]
    except (TypeError, ValueError):
        return None


def _fallback_keypoint_anchor(anchor: dict[str, Any], reason: str) -> dict[str, Any]:
    payload = copy.deepcopy(anchor)
    payload["fallback_reason"] = reason
    payload["depth_source"] = BBOX_TOP_CENTER_FALLBACK_DEPTH_SOURCE
    return payload


def _selected_anchor_plan(record: dict[str, Any]) -> dict[str, Any]:
    left_bbox = list(record["left_bbox_xyxy"])
    right_bbox = list(record["right_bbox_xyxy"])
    bbox_left_anchor = _bbox_top_center_from_xyxy(left_bbox)
    bbox_right_anchor = _bbox_top_center_from_xyxy(right_bbox)
    anchor = record.get("selected_anchor")
    if not isinstance(anchor, dict):
        return {
            "source": "bbox_default",
            "anchor_kind": ANCHOR_KIND_BBOX_TOP_CENTER,
            "left_anchor_px": bbox_left_anchor,
            "right_anchor_px": bbox_right_anchor,
            "depth_source": None,
            "depth_confidence": "high",
            "keypoint_anchor": None,
        }

    kind = str(anchor.get("kind", ""))
    left_kind = str(anchor.get("left_kind", kind))
    right_kind = str(anchor.get("right_kind", kind))
    left_px = _xy_pair_or_none(anchor.get("left_px"))
    right_px = _xy_pair_or_none(anchor.get("right_px"))

    fallback_reason = None
    if kind not in KEYPOINT_DEPTH_ANCHOR_KINDS:
        fallback_reason = "no_keypoint_anchor" if kind in {"bbox_top_center", "missing", ""} else "anchor_kind_mismatch"
    elif left_kind != kind or right_kind != kind:
        fallback_reason = "anchor_kind_mismatch"
    elif left_px is None or right_px is None:
        fallback_reason = "missing_anchor_px"

    if fallback_reason is not None:
        return {
            "source": "keypoint_fallback",
            "anchor_kind": ANCHOR_KIND_BBOX_TOP_CENTER,
            "left_anchor_px": bbox_left_anchor,
            "right_anchor_px": bbox_right_anchor,
            "depth_source": BBOX_TOP_CENTER_FALLBACK_DEPTH_SOURCE,
            "depth_confidence": "low",
            "keypoint_anchor": _fallback_keypoint_anchor(anchor, fallback_reason),
        }

    return {
        "source": "keypoint",
        "anchor_kind": kind,
        "left_anchor_px": left_px,
        "right_anchor_px": right_px,
        "depth_source": kind,
        "depth_confidence": "high",
        "keypoint_anchor": copy.deepcopy(anchor),
    }


def _held_stereo_record(
    record: dict[str, Any],
    calibration: Any,
    *,
    depth_m: float,
    gate_config: StereoGateConfig,
) -> dict[str, Any]:
    left_bbox = list(record["left_bbox_xyxy"])
    right_bbox = list(record["right_bbox_xyxy"])
    anchor_plan = _selected_anchor_plan(record)
    left_anchor = anchor_plan["left_anchor_px"]
    right_anchor = anchor_plan["right_anchor_px"]
    left_size = _bbox_dict_from_xyxy(left_bbox)
    right_size = _bbox_dict_from_xyxy(right_bbox)
    disparity_px = float(left_anchor[0] - right_anchor[0])
    vertical_error_px = float(left_anchor[1] - right_anchor[1])
    box_width_ratio = left_size["w"] / max(right_size["w"], 1.0)
    box_height_ratio = left_size["h"] / max(right_size["h"], 1.0)
    stereo_record = {
        "schema_version": 1,
        "pair_id": str(record["pair_id"]),
        "frame_id": int(record["frame_id"]),
        "frame_provenance": calibration.frame_provenance,
        "person_id": str(record["person_id"]),
        "bbox": {
            "left_xyxy": left_bbox,
            "right_xyxy": right_bbox,
        },
        "confidence": float(record.get("confidence", 1.0)),
        "anchor_kind": anchor_plan["anchor_kind"],
        "left_anchor_px": left_anchor,
        "right_anchor_px": right_anchor,
        "disparity_px": disparity_px,
        "vertical_error_px": vertical_error_px,
        "box_width_ratio": box_width_ratio,
        "box_height_ratio": box_height_ratio,
        "depth_m": float(depth_m),
        "position": calibration.left.unproject(left_anchor[0], left_anchor[1], depth_m),
        "depth_source": HELD_DEPTH_SOURCE,
        "is_ground_truth": False,
        "pose_quality": "stereo",
        "calibration_ref": calibration.calibration_id,
        "stereo_ok": False,
        "rejection_reason": "depth_update_gated",
        "gates": gate_config.to_dict(),
        "depth_update_allowed": False,
        "held_reason": record.get("selection", {}).get("held_reason"),
    }
    if anchor_plan.get("keypoint_anchor") is not None:
        stereo_record["keypoint_anchor"] = anchor_plan["keypoint_anchor"]
    pose_association = record.get("pose_association")
    if isinstance(pose_association, dict):
        stereo_record["pose_association"] = copy.deepcopy(pose_association)
    return stereo_record


def build_proxy_targets_message_from_stereo_bbox_record(
    record: dict[str, Any],
    *,
    sequence: int,
    card_id: str = "CardAnchor",
    offset_rule: dict[str, Any] | None = None,
    recorded_width: int = 880,
    recorded_height: int = 660,
    min_confidence: float = 0.5,
    min_depth_m: float = 0.2,
    max_depth_m: float = 5.0,
    min_box_ratio: float = 0.5,
    max_box_ratio: float = 2.0,
    max_vertical_error_px: float | None = None,
    depth_override: DepthOverrideConfig | None = None,
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
    selection = record.get("selection", {})
    if not isinstance(selection, dict):
        selection = {}
    depth_update_allowed = selection.get("depth_update_allowed", True) is not False
    anchor_plan = _selected_anchor_plan(record)
    if depth_update_allowed:
        triangulate_kwargs: dict[str, Any] = {
            "anchor_kind": anchor_plan["anchor_kind"],
            "gate_config": gate_config,
        }
        if anchor_plan.get("source") != "bbox_default":
            triangulate_kwargs["left_anchor_px"] = anchor_plan["left_anchor_px"]
            triangulate_kwargs["right_anchor_px"] = anchor_plan["right_anchor_px"]
            triangulate_kwargs["depth_source"] = anchor_plan["depth_source"]
        stereo_record = triangulate_detection_pair(_record_to_pair(record), calibration, **triangulate_kwargs)
        if stereo_record.get("stereo_ok") is not True:
            return None
        depth_m = float(stereo_record["depth_m"])
        depth_source = anchor_plan["depth_source"] or stereo_record["depth_source"]
        depth_confidence = str(anchor_plan["depth_confidence"])
    else:
        depth_m = _positive_float_or_none(selection.get("last_good_depth"))
        if depth_m is None:
            depth_m = _positive_float_or_none(selection.get("estimated_depth_m"))
        if depth_m is None:
            return None
        stereo_record = _held_stereo_record(
            record,
            calibration,
            depth_m=depth_m,
            gate_config=gate_config,
        )
        depth_source = HELD_DEPTH_SOURCE
        depth_confidence = "low"

    keypoint_anchor = anchor_plan.get("keypoint_anchor")
    if keypoint_anchor is not None:
        stereo_record["keypoint_anchor"] = copy.deepcopy(keypoint_anchor)
    pose_association = record.get("pose_association")
    if isinstance(pose_association, dict):
        stereo_record["pose_association"] = copy.deepcopy(pose_association)

    raw_depth_m = float(depth_m)
    depth_override_context = apply_depth_override(raw_depth_m, depth_override, sequence=sequence)
    depth_override_mode = str(depth_override_context.get("mode", "real"))
    if depth_override_mode != "real":
        depth_m = float(depth_override_context["applied_depth_m"])
        depth_source = f"depth_override_{depth_override_mode}"
        stereo_record["depth_m_raw"] = raw_depth_m
        stereo_record["depth_m"] = depth_m
        stereo_record["depth_source_raw"] = stereo_record.get("depth_source")
        stereo_record["depth_source"] = depth_source
        stereo_record["position"] = calibration.left.unproject(
            stereo_record["left_anchor_px"][0],
            stereo_record["left_anchor_px"][1],
            depth_m,
        )

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
                "depth_m": float(depth_m),
                "depth_source": depth_source,
                "depth_confidence": depth_confidence,
                "stereo": {
                    "pair_id": stereo_record["pair_id"],
                    "frame_id": stereo_record["frame_id"],
                    "depth_source": depth_source,
                    "depth_confidence": depth_confidence,
                    "anchor_kind": stereo_record["anchor_kind"],
                    "left_anchor_px": stereo_record["left_anchor_px"],
                    "right_anchor_px": stereo_record["right_anchor_px"],
                    "disparity_px": stereo_record["disparity_px"],
                    "vertical_error_px": stereo_record["vertical_error_px"],
                    "calibration_ref": stereo_record["calibration_ref"],
                    "depth_update_allowed": bool(depth_update_allowed),
                    "stereo_ok": stereo_record.get("stereo_ok"),
                    "rejection_reason": stereo_record.get("rejection_reason"),
                },
            }
        ],
    }
    if depth_override_mode != "real":
        source_payload["detections"][0]["depth_override"] = copy.deepcopy(depth_override_context)
        source_payload["detections"][0]["stereo"]["depth_m_raw"] = raw_depth_m
        source_payload["detections"][0]["stereo"]["depth_m"] = float(depth_m)
        source_payload["detections"][0]["stereo"]["depth_source_raw"] = stereo_record.get("depth_source_raw")
    if keypoint_anchor is not None:
        source_payload["detections"][0]["stereo"]["keypoint_anchor"] = copy.deepcopy(keypoint_anchor)
    if isinstance(pose_association, dict):
        source_payload["detections"][0]["stereo"]["pose_association"] = copy.deepcopy(pose_association)
    message = normalize_source_payload(source_payload, sequence=sequence, card_id=card_id, offset_rule=offset_rule)
    message["timestamp_ms"] = source_payload["timestamp_ms"]
    if not message["targets"]:
        return None
    detection = source_payload["detections"][0]
    message["targets"][0]["stereo"] = copy.deepcopy(detection["stereo"])
    if depth_override_mode != "real":
        message["targets"][0]["depth_override"] = copy.deepcopy(depth_override_context)
        source_coordinate = message["targets"][0].get("source_coordinate")
        if isinstance(source_coordinate, dict):
            source_coordinate["depth_override"] = copy.deepcopy(depth_override_context)
    _DEPTH_TRACE_CONTEXT[id(message)] = {
        "bbox": detection["bbox"],
        "stereo": detection["stereo"],
        "depth_override": copy.deepcopy(depth_override_context) if depth_override_mode != "real" else None,
        "keypoint_anchor": copy.deepcopy(keypoint_anchor) if keypoint_anchor is not None else None,
        "pose_association": copy.deepcopy(pose_association) if isinstance(pose_association, dict) else None,
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


def _message_target_timestamp_ms(message: dict[str, Any], target: dict[str, Any]) -> float | None:
    for value in (target.get("timestamp_ms"), message.get("timestamp_ms")):
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _position_filter_reset_requested(selection: dict[str, Any] | None) -> bool:
    if not isinstance(selection, dict):
        return False
    return str(selection.get("switch_reason", "")) in {"initial", "active_missing_switch", "switch_confirmed"}


def apply_position_one_euro_filter(
    message: dict[str, Any],
    filter_state: OneEuroVector3Filter,
    *,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    targets = message.get("targets")
    if not isinstance(targets, list) or not targets:
        return message
    target = targets[0]
    if not isinstance(target, dict):
        return message
    transform = target.get("transform")
    if not isinstance(transform, dict):
        return message
    raw_position = _vector3_from_mapping(transform.get("position"))
    if raw_position is None:
        return message

    timestamp_ms = _message_target_timestamp_ms(message, target)
    reset = _position_filter_reset_requested(selection)
    filtered_position, diagnostics = filter_state.filter(raw_position, timestamp_ms=timestamp_ms, reset=reset)
    filter_context = {
        **diagnostics,
        "raw_position_m": raw_position,
        "filtered_position_m": filtered_position,
    }
    transform["position"] = filtered_position
    target["position_filter"] = copy.deepcopy(filter_context)
    source_coordinate = target.get("source_coordinate")
    if isinstance(source_coordinate, dict):
        source_coordinate["raw_head_position_m"] = raw_position
        source_coordinate["filtered_head_position_m"] = filtered_position
        source_coordinate["position_filter"] = copy.deepcopy(filter_context)
    return message


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
        "non_publish_reason": diagnostics.get("non_publish_reason"),
        "non_published_frames": diagnostics.get("non_published_frames", []),
        "stage_timing_ms": diagnostics.get("stage_timing_ms", {}),
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
    keypoint_runtime = diagnostics.get("keypoint_runtime")
    if isinstance(keypoint_runtime, dict):
        event["keypoint_runtime"] = copy.deepcopy(keypoint_runtime)
    left_source_stats = event["left_source_stats"] if isinstance(event["left_source_stats"], dict) else {}
    right_source_stats = event["right_source_stats"] if isinstance(event["right_source_stats"], dict) else {}
    replay_stat_keys = (
        "source_frame_index_gap",
        "replay_clock_lag_ms",
        "detector_backlog",
    )
    for key in replay_stat_keys:
        left_key = f"left_{key}"
        right_key = f"right_{key}"
        left_value = left_source_stats.get(key)
        right_value = right_source_stats.get(key)
        if left_value is not None:
            event[left_key] = left_value
        if right_value is not None:
            event[right_key] = right_value
        values = [value for value in (left_value, right_value) if isinstance(value, (int, float))]
        if values:
            event[key] = max(values)
    clients = diagnostics.get("clients")
    if isinstance(clients, dict):
        event["clients"] = dict(clients)
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
            "published_position_m": _vector3_from_mapping(target.get("transform", {}).get("position")),
            "bbox": trace_context.get("bbox", target.get("bbox", {})),
            "stereo": stereo,
        }
    )
    depth_override = trace_context.get("depth_override") or target.get("depth_override")
    if isinstance(depth_override, dict):
        event["depth_override"] = copy.deepcopy(depth_override)
        event["depth_raw_m"] = depth_override.get("raw_depth_m")
    keypoint_anchor = trace_context.get("keypoint_anchor")
    if keypoint_anchor is None and isinstance(stereo, dict):
        keypoint_anchor = stereo.get("keypoint_anchor")
    if isinstance(keypoint_anchor, dict):
        event["keypoint_anchor"] = copy.deepcopy(keypoint_anchor)
    pose_association = trace_context.get("pose_association")
    if pose_association is None and isinstance(stereo, dict):
        pose_association = stereo.get("pose_association")
    if isinstance(pose_association, dict):
        event["pose_association"] = copy.deepcopy(pose_association)
    position_filter = target.get("position_filter") or source_coordinate.get("position_filter")
    if isinstance(position_filter, dict):
        event["position_filter"] = copy.deepcopy(position_filter)
        event["raw_head_position_m"] = _vector3_from_mapping(position_filter.get("raw_position_m"))
        event["filtered_head_position_m"] = _vector3_from_mapping(position_filter.get("filtered_position_m"))
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
        "active_state",
        "left_active_seen",
        "right_active_seen",
        "mono_missing_frames",
        "both_missing_frames",
        "held_reason",
        "depth_update_allowed",
        "depth_gate_reason",
        "last_good_depth",
        "reacquire_candidate_age",
        "switch_block_reason",
    ):
        if key in selection:
            event[key] = selection[key]
    return event


def _freshness_state(
    *,
    latest_update_ms: float | None,
    last_diagnostics: dict[str, Any] | None,
    now_ms: float,
    stale_after_ms: float,
) -> dict[str, Any]:
    age_ms = None if latest_update_ms is None else max(0.0, now_ms - latest_update_ms)
    last_reason = None
    if isinstance(last_diagnostics, dict):
        last_reason = last_diagnostics.get("non_publish_reason") or last_diagnostics.get("reason")
    state = "fresh"
    if last_reason and last_reason != "target_ready":
        state = "held"
    if age_ms is not None and age_ms > stale_after_ms:
        state = "stale"
    return {
        "state": state,
        "age_ms": age_ms,
        "reason": last_reason,
        "stale_after_ms": float(stale_after_ms),
    }


def _message_with_publish_freshness(
    message: dict[str, Any],
    *,
    sequence: int,
    freshness: dict[str, Any],
) -> dict[str, Any]:
    published = copy.deepcopy(message)
    published["sequence"] = int(sequence)
    published["publish_freshness"] = dict(freshness)
    held = freshness.get("state") in ("held", "stale")
    for target in published.get("targets", []):
        if isinstance(target, dict):
            target["freshness"] = dict(freshness)
            target["held"] = bool(held)
            target["tracking_confidence"] = freshness.get("state")
    for card in published.get("cards", []):
        if isinstance(card, dict):
            card["target_freshness"] = dict(freshness)
    return published


def publish_latest_stereo_state_once(
    *,
    hub: BroadcastHub,
    state: LatestStereoPublishState,
    sequence: int,
    depth_trace: Path | None,
    stale_after_ms: float = 250.0,
) -> dict[str, Any] | None:
    if hub.client_count() == 0:
        return None
    snapshot = state.snapshot()
    latest_message = snapshot.get("latest_message")
    latest_diagnostics = snapshot.get("latest_diagnostics")
    last_diagnostics = snapshot.get("last_diagnostics")
    now_ms = time.monotonic() * 1000.0
    clients = hub.status_summary()
    if latest_message is None:
        diagnostics = copy.deepcopy(last_diagnostics) if isinstance(last_diagnostics, dict) else _empty_diagnostics("no_target")
        diagnostics["clients"] = clients
        diagnostics["freshness"] = {
            "state": "empty",
            "age_ms": None,
            "reason": diagnostics.get("non_publish_reason") or diagnostics.get("reason"),
            "stale_after_ms": float(stale_after_ms),
        }
        event = build_depth_trace_event(message=None, diagnostics=diagnostics, sequence=sequence)
        event["freshness"] = dict(diagnostics["freshness"])
        write_depth_trace_event(depth_trace, event)
        return event

    freshness = _freshness_state(
        latest_update_ms=snapshot.get("latest_update_ms"),
        last_diagnostics=last_diagnostics if isinstance(last_diagnostics, dict) else None,
        now_ms=now_ms,
        stale_after_ms=stale_after_ms,
    )
    message = _message_with_publish_freshness(latest_message, sequence=sequence, freshness=freshness)
    publish_started = time.perf_counter()
    delivered = hub.broadcast(message)
    diagnostics = copy.deepcopy(latest_diagnostics) if isinstance(latest_diagnostics, dict) else _empty_diagnostics("target_ready")
    diagnostics.setdefault("stage_timing_ms", {})["publish_ms"] = _elapsed_ms(publish_started)
    diagnostics["clients"] = clients
    diagnostics["freshness"] = dict(freshness)
    event = build_depth_trace_event(message=message, diagnostics=diagnostics, delivered_clients=delivered)
    event["freshness"] = dict(freshness)
    write_depth_trace_event(depth_trace, event)
    return event


def write_depth_trace_event(trace_path: Path | None, event: dict[str, Any]) -> None:
    if trace_path is None:
        return
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def _bbox_fraction_from_xy(
    xy: list[float] | tuple[float, float],
    bbox_xyxy: list[float] | tuple[float, float, float, float],
) -> list[float]:
    x1, y1, x2, y2 = (float(value) for value in bbox_xyxy)
    width = max(x2 - x1, 1e-6)
    height = max(y2 - y1, 1e-6)
    return [(float(xy[0]) - x1) / width, (float(xy[1]) - y1) / height]


def _xy_from_bbox_fraction(
    fraction: list[float] | tuple[float, float],
    bbox_xyxy: list[float] | tuple[float, float, float, float],
) -> list[float]:
    x1, y1, x2, y2 = (float(value) for value in bbox_xyxy)
    return [
        x1 + float(fraction[0]) * (x2 - x1),
        y1 + float(fraction[1]) * (y2 - y1),
    ]


def _cache_from_keypoint_record(
    record: dict[str, Any],
    *,
    completed_at_s: float,
    inference_ms: float,
) -> dict[str, Any] | None:
    anchor = record.get("selected_anchor")
    if not isinstance(anchor, dict) or str(anchor.get("kind", "")) not in KEYPOINT_DEPTH_ANCHOR_KINDS:
        return None
    left_px = _xy_pair_or_none(anchor.get("left_px"))
    right_px = _xy_pair_or_none(anchor.get("right_px"))
    if left_px is None or right_px is None:
        return None
    left_bbox = record.get("left_bbox_xyxy")
    right_bbox = record.get("right_bbox_xyxy")
    if not isinstance(left_bbox, (list, tuple)) or not isinstance(right_bbox, (list, tuple)):
        return None
    if len(left_bbox) != 4 or len(right_bbox) != 4:
        return None
    return {
        "completed_at_s": float(completed_at_s),
        "inference_ms": float(inference_ms),
        "selected_anchor": copy.deepcopy(anchor),
        "left_fraction": _bbox_fraction_from_xy(left_px, left_bbox),
        "right_fraction": _bbox_fraction_from_xy(right_px, right_bbox),
        "keypoints": copy.deepcopy(record.get("keypoints", {})),
        "pose_association": copy.deepcopy(record.get("pose_association", {})),
    }


def _apply_cached_keypoint_anchor(record: dict[str, Any], cache: dict[str, Any]) -> dict[str, Any]:
    anchor = copy.deepcopy(cache["selected_anchor"])
    anchor["left_px"] = _xy_from_bbox_fraction(cache["left_fraction"], record["left_bbox_xyxy"])
    anchor["right_px"] = _xy_from_bbox_fraction(cache["right_fraction"], record["right_bbox_xyxy"])
    anchor["cache_reused"] = True
    record["source"] = "vst_stereo_keypoint"
    record["selected_anchor"] = anchor
    record["keypoints"] = copy.deepcopy(cache.get("keypoints", {}))
    record["pose_association"] = copy.deepcopy(cache.get("pose_association", {}))
    return {
        "keypoint_anchor": copy.deepcopy(anchor),
        "pose_association": copy.deepcopy(record["pose_association"]),
    }


def _attach_keypoint_anchor_to_record(
    record: dict[str, Any],
    *,
    left_frame: Any,
    right_frame: Any,
    left_pose_estimator: Any,
    right_pose_estimator: Any,
    min_keypoint_score: float,
    pose_association_margin_px: float,
    max_pose_association_distance_px: float,
) -> dict[str, Any]:
    left_keypoints, left_scores = left_pose_estimator(left_frame)
    right_keypoints, right_scores = right_pose_estimator(right_frame)
    left_normalized, left_association = _normalize_pose_output_for_bbox(
        left_keypoints,
        left_scores,
        target_bbox_xyxy=record.get("left_bbox_xyxy"),
        association_margin_px=pose_association_margin_px,
        max_association_distance_px=max_pose_association_distance_px,
    )
    right_normalized, right_association = _normalize_pose_output_for_bbox(
        right_keypoints,
        right_scores,
        target_bbox_xyxy=record.get("right_bbox_xyxy"),
        association_margin_px=pose_association_margin_px,
        max_association_distance_px=max_pose_association_distance_px,
    )
    keypoint_record = build_stereo_keypoint_pair_record(
        frame_id=int(record["frame_id"]),
        timestamp_ms=int(record.get("timestamp_ms", int(time.time() * 1000))),
        left_keypoints=left_normalized,
        right_keypoints=right_normalized,
        bbox_pair=record,
        min_score=min_keypoint_score,
        left_pose_association=left_association,
        right_pose_association=right_association,
    )
    record["source"] = "vst_stereo_keypoint"
    record["selected_anchor"] = copy.deepcopy(keypoint_record["selected_anchor"])
    record["keypoints"] = copy.deepcopy(keypoint_record["keypoints"])
    record["pose_association"] = copy.deepcopy(keypoint_record.get("pose_association", {}))
    return {
        "keypoint_anchor": copy.deepcopy(record["selected_anchor"]),
        "pose_association": copy.deepcopy(record["pose_association"]),
    }


class KeypointAnchorScheduler:
    def __init__(
        self,
        *,
        left_pose_estimator: Any,
        right_pose_estimator: Any,
        min_keypoint_score: float,
        pose_association_margin_px: float,
        max_pose_association_distance_px: float,
        max_hz: float = DEFAULT_KEYPOINT_MAX_HZ,
        reuse_max_age_ms: float = DEFAULT_KEYPOINT_REUSE_MAX_AGE_MS,
        now_fn: Any = time.monotonic,
        async_enabled: bool = False,
    ) -> None:
        self.left_pose_estimator = left_pose_estimator
        self.right_pose_estimator = right_pose_estimator
        self.min_keypoint_score = float(min_keypoint_score)
        self.pose_association_margin_px = float(pose_association_margin_px)
        self.max_pose_association_distance_px = float(max_pose_association_distance_px)
        self.max_hz = float(max_hz)
        self.reuse_max_age_ms = float(reuse_max_age_ms)
        self.now_fn = now_fn
        self.async_enabled = bool(async_enabled)
        self._lock = threading.Lock()
        self._pending = False
        self._completed: dict[str, Any] | None = None
        self._cache: dict[str, Any] | None = None
        self._last_submitted_s: float | None = None
        self._last_error: str | None = None

    def attach_or_reuse(
        self,
        record: dict[str, Any],
        *,
        left_frame: Any,
        right_frame: Any,
    ) -> dict[str, Any]:
        now_s = float(self.now_fn())
        self._consume_completed(now_s)
        cache = self._valid_cache(now_s)
        if cache is not None:
            applied = _apply_cached_keypoint_anchor(record, cache)
            scheduled = self._maybe_schedule(record, left_frame=left_frame, right_frame=right_frame, now_s=now_s)
            applied["keypoint_runtime"] = self._runtime_payload(
                mode="reuse",
                now_s=now_s,
                cache=cache,
                cache_hit=True,
                scheduled=scheduled,
            )
            return applied

        if self.async_enabled:
            scheduled = self._maybe_schedule(record, left_frame=left_frame, right_frame=right_frame, now_s=now_s)
            return {
                "keypoint_anchor": {
                    "kind": "disabled",
                    "fallback_reason": "async_pending" if self._is_pending() else "no_cached_keypoint_anchor",
                },
                "keypoint_runtime": self._runtime_payload(
                    mode="fallback",
                    now_s=now_s,
                    cache=None,
                    cache_hit=False,
                    scheduled=scheduled,
                    fallback_reason="async_pending" if self._is_pending() else "no_cached_keypoint_anchor",
                ),
            }

        if not self._rate_limit_allows(now_s):
            return {
                "keypoint_anchor": {
                    "kind": "disabled",
                    "fallback_reason": "keypoint_rate_limited",
                },
                "keypoint_runtime": self._runtime_payload(
                    mode="fallback",
                    now_s=now_s,
                    cache=None,
                    cache_hit=False,
                    scheduled=False,
                    fallback_reason="keypoint_rate_limited",
                ),
            }

        return self._run_inline(record, left_frame=left_frame, right_frame=right_frame, now_s=now_s)

    def _run_inline(
        self,
        record: dict[str, Any],
        *,
        left_frame: Any,
        right_frame: Any,
        now_s: float,
    ) -> dict[str, Any]:
        self._last_submitted_s = now_s
        started = time.perf_counter()
        diagnostics = _attach_keypoint_anchor_to_record(
            record,
            left_frame=left_frame,
            right_frame=right_frame,
            left_pose_estimator=self.left_pose_estimator,
            right_pose_estimator=self.right_pose_estimator,
            min_keypoint_score=self.min_keypoint_score,
            pose_association_margin_px=self.pose_association_margin_px,
            max_pose_association_distance_px=self.max_pose_association_distance_px,
        )
        inference_ms = _elapsed_ms(started)
        self._cache = _cache_from_keypoint_record(record, completed_at_s=now_s, inference_ms=inference_ms)
        self._last_error = None
        diagnostics["keypoint_runtime"] = self._runtime_payload(
            mode="run",
            now_s=now_s,
            cache=self._cache,
            cache_hit=False,
            scheduled=False,
            inference_ms=inference_ms,
        )
        return diagnostics

    def _maybe_schedule(self, record: dict[str, Any], *, left_frame: Any, right_frame: Any, now_s: float) -> bool:
        if not self.async_enabled or not self._rate_limit_allows(now_s) or self._is_pending():
            return False
        self._last_submitted_s = now_s
        with self._lock:
            self._pending = True
        job_record = copy.deepcopy(record)
        thread = threading.Thread(
            target=self._run_async_job,
            kwargs={
                "record": job_record,
                "left_frame": left_frame,
                "right_frame": right_frame,
            },
            daemon=True,
        )
        thread.start()
        return True

    def _run_async_job(self, *, record: dict[str, Any], left_frame: Any, right_frame: Any) -> None:
        started = time.perf_counter()
        try:
            diagnostics = _attach_keypoint_anchor_to_record(
                record,
                left_frame=left_frame,
                right_frame=right_frame,
                left_pose_estimator=self.left_pose_estimator,
                right_pose_estimator=self.right_pose_estimator,
                min_keypoint_score=self.min_keypoint_score,
                pose_association_margin_px=self.pose_association_margin_px,
                max_pose_association_distance_px=self.max_pose_association_distance_px,
            )
            result = {
                "record": record,
                "diagnostics": diagnostics,
                "inference_ms": _elapsed_ms(started),
                "completed_at_s": time.monotonic(),
            }
        except Exception as exc:
            result = {
                "error": str(exc),
                "inference_ms": _elapsed_ms(started),
                "completed_at_s": time.monotonic(),
            }
        with self._lock:
            self._completed = result
            self._pending = False

    def _consume_completed(self, now_s: float) -> None:
        with self._lock:
            completed = self._completed
            self._completed = None
        if completed is None:
            return
        if completed.get("error") is not None:
            self._last_error = str(completed["error"])
            return
        record = completed.get("record")
        if isinstance(record, dict):
            self._cache = _cache_from_keypoint_record(
                record,
                completed_at_s=now_s,
                inference_ms=float(completed.get("inference_ms", 0.0)),
            )
            self._last_error = None

    def _valid_cache(self, now_s: float) -> dict[str, Any] | None:
        cache = self._cache
        if cache is None:
            return None
        if self.reuse_max_age_ms <= 0.0:
            return None
        age_ms = (now_s - float(cache.get("completed_at_s", now_s))) * 1000.0
        return cache if age_ms <= self.reuse_max_age_ms else None

    def _rate_limit_allows(self, now_s: float) -> bool:
        if self.max_hz <= 0.0 or self._last_submitted_s is None:
            return True
        return (now_s - self._last_submitted_s) >= (1.0 / self.max_hz)

    def _is_pending(self) -> bool:
        with self._lock:
            return self._pending

    def _runtime_payload(
        self,
        *,
        mode: str,
        now_s: float,
        cache: dict[str, Any] | None,
        cache_hit: bool,
        scheduled: bool,
        inference_ms: float | None = None,
        fallback_reason: str | None = None,
    ) -> dict[str, Any]:
        age_ms = None
        if cache is not None:
            age_ms = max(0.0, (now_s - float(cache.get("completed_at_s", now_s))) * 1000.0)
        payload: dict[str, Any] = {
            "mode": mode,
            "cache_hit": bool(cache_hit),
            "pending": self._is_pending(),
            "scheduled": bool(scheduled),
            "age_ms": age_ms,
            "max_hz": self.max_hz,
            "reuse_max_age_ms": self.reuse_max_age_ms,
        }
        if inference_ms is not None:
            payload["inference_ms"] = float(inference_ms)
        elif cache is not None and cache.get("inference_ms") is not None:
            payload["inference_ms"] = float(cache["inference_ms"])
        if fallback_reason is not None:
            payload["fallback_reason"] = fallback_reason
        if self._last_error is not None:
            payload["last_error"] = self._last_error
        return payload


class UltralyticsPoseEstimator:
    def __init__(
        self,
        *,
        model: str | Path,
        imgsz: int,
        conf: float,
        device: str | None,
    ) -> None:
        try:
            from ultralytics import YOLO
        except Exception as exc:
            raise RuntimeError("ultralytics is required for --enable-keypoint-anchor") from exc

        self.model_path = str(model)
        self.imgsz = int(imgsz)
        self.conf = float(conf)
        self.device = device
        self.model = YOLO(self.model_path)

    def __call__(self, frame: Any) -> tuple[Any, Any]:
        kwargs: dict[str, Any] = {
            "imgsz": self.imgsz,
            "conf": self.conf,
            "verbose": False,
        }
        if self.device is not None:
            kwargs["device"] = self.device
        results = self.model.predict(frame, **kwargs)
        if not results:
            return [], []
        keypoints = getattr(results[0], "keypoints", None)
        if keypoints is None:
            return [], []
        xy = getattr(keypoints, "xy", None)
        scores = getattr(keypoints, "conf", None)
        xy_list = xy.cpu().numpy().tolist() if hasattr(xy, "cpu") else []
        if scores is None:
            score_list = [[1.0] * len(person) for person in xy_list]
        else:
            score_list = scores.cpu().numpy().tolist() if hasattr(scores, "cpu") else []
        return xy_list, score_list


def create_pose_estimators(args: argparse.Namespace) -> tuple[Any | None, Any | None]:
    if not getattr(args, "enable_keypoint_anchor", False):
        return None, None
    device = getattr(args, "pose_device", None)
    if device is None:
        device = getattr(args, "device", None)
    estimator = UltralyticsPoseEstimator(
        model=getattr(args, "pose_model", DEFAULT_POSE_MODEL),
        imgsz=getattr(args, "pose_imgsz", DEFAULT_POSE_IMGSZ),
        conf=getattr(args, "pose_conf", DEFAULT_POSE_CONFIDENCE),
        device=device,
    )
    return estimator, estimator


def next_live_stereo_proxy_targets_message_with_diagnostics(
    *,
    left_reader: Any,
    right_reader: Any,
    left_tracker: Any,
    right_tracker: Any,
    left_pose_estimator: Any | None = None,
    right_pose_estimator: Any | None = None,
    sequence: int,
    card_id: str = "CardAnchor",
    offset_rule: dict[str, Any] | None = None,
    recorded_width: int = 880,
    recorded_height: int = 660,
    min_confidence: float = 0.5,
    min_keypoint_score: float = DEFAULT_MIN_KEYPOINT_SCORE,
    pose_association_margin_px: float = DEFAULT_POSE_ASSOCIATION_MARGIN_PX,
    max_pose_association_distance_px: float = DEFAULT_MAX_POSE_ASSOCIATION_DISTANCE_PX,
    max_empty_reads: int | None = None,
    max_read_attempts: int | None = None,
    sleep_seconds: float = 0.005,
    max_vertical_error_px: float | None = None,
    target_stabilizer: StereoActiveTargetStabilizer | None = None,
    position_filter: OneEuroVector3Filter | None = None,
    keypoint_scheduler: KeypointAnchorScheduler | None = None,
    max_pair_capture_delta_ms: float | None = DEFAULT_MAX_PAIR_CAPTURE_DELTA_MS,
    target_source_hz: float = DEFAULT_SOURCE_HZ,
    depth_override: DepthOverrideConfig | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    attempts = max_read_attempts if max_read_attempts is not None else max_empty_reads
    diagnostics = _empty_diagnostics("no_pair")
    total_started = time.perf_counter()
    stage_timing = diagnostics["stage_timing_ms"]
    pending_left: dict[int, Any] = {}
    pending_right: dict[int, Any] = {}
    pending_left_received_at_ms: dict[int, float] = {}
    pending_right_received_at_ms: dict[int, float] = {}
    seen_left: set[int] = set()
    seen_right: set[int] = set()
    diagnostics["sync"]["max_pair_capture_delta_ms"] = max_pair_capture_delta_ms
    for _ in range(max(1, int(attempts if attempts is not None else 120))):
        diagnostics["read_attempts"] += 1
        frame_read_started = time.perf_counter()
        _read_one_eye(left_reader, pending_left, seen_left, pending_left_received_at_ms)
        _read_one_eye(right_reader, pending_right, seen_right, pending_right_received_at_ms)
        stage_timing["frame_read_ms"] = float(stage_timing.get("frame_read_ms", 0.0)) + _elapsed_ms(frame_read_started)
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

        pair_select_started = time.perf_counter()
        pair_ids = _select_next_pair_by_sync(
            pending_left=pending_left,
            pending_right=pending_right,
            pending_left_received_at_ms=pending_left_received_at_ms,
            pending_right_received_at_ms=pending_right_received_at_ms,
            max_pair_capture_delta_ms=max_pair_capture_delta_ms,
            diagnostics=diagnostics,
        )
        stage_timing["pair_select_ms"] = float(stage_timing.get("pair_select_ms", 0.0)) + _elapsed_ms(pair_select_started)
        if pair_ids is not None:
            left_frame_id, right_frame_id = pair_ids
            left_frame = pending_left.pop(left_frame_id)
            right_frame = pending_right.pop(right_frame_id)
            left_received_at_ms = pending_left_received_at_ms.pop(left_frame_id, None)
            right_received_at_ms = pending_right_received_at_ms.pop(right_frame_id, None)
            left_tracker_frame = _frame_for_tracker(left_frame)
            right_tracker_frame = _frame_for_tracker(right_frame)
            left_detect_started = time.perf_counter()
            left_tracking_result = left_tracker.process_frame(left_tracker_frame)
            stage_timing["left_detect_ms"] = float(stage_timing.get("left_detect_ms", 0.0)) + _elapsed_ms(left_detect_started)
            right_detect_started = time.perf_counter()
            right_tracking_result = right_tracker.process_frame(right_tracker_frame)
            stage_timing["right_detect_ms"] = float(stage_timing.get("right_detect_ms", 0.0)) + _elapsed_ms(right_detect_started)
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
            pair_build_started = time.perf_counter()
            record = build_stereo_bbox_pair_record(
                frame_id=left_frame_id,
                left_frame=left_frame,
                right_frame=right_frame,
                left_tracking_result=left_tracking_result,
                right_tracking_result=right_tracking_result,
                timestamp_ms=_pair_runtime_timestamp_ms(left_frame, right_frame),
                left_source_stats=diagnostics["left_source_stats"],
                right_source_stats=diagnostics["right_source_stats"],
                target_stabilizer=target_stabilizer,
                timing_ms=stage_timing,
            )
            stage_timing["pair_build_ms"] = float(stage_timing.get("pair_build_ms", 0.0)) + _elapsed_ms(pair_build_started)
            diagnostics["last_pair_frame_id"] = left_frame_id
            if record is None:
                diagnostics["reason"] = "no_target"
                diagnostics["non_publish_reason"] = "no_target"
                _append_non_published_frame(
                    diagnostics,
                    reason="no_target",
                    left_frame_id=left_frame_id,
                    right_frame_id=right_frame_id,
                )
                continue
            if keypoint_scheduler is not None:
                keypoint_anchor_started = time.perf_counter()
                try:
                    keypoint_diagnostics = keypoint_scheduler.attach_or_reuse(
                        record,
                        left_frame=left_tracker_frame,
                        right_frame=right_tracker_frame,
                    )
                    diagnostics.update(keypoint_diagnostics)
                except Exception as exc:
                    diagnostics["keypoint_anchor"] = {
                        "kind": "disabled",
                        "fallback_reason": "keypoint_scheduler_failed",
                        "error": str(exc),
                    }
                    diagnostics["keypoint_runtime"] = {
                        "mode": "fallback",
                        "cache_hit": False,
                        "pending": False,
                        "scheduled": False,
                        "fallback_reason": "keypoint_scheduler_failed",
                        "error": str(exc),
                    }
                finally:
                    stage_timing["keypoint_anchor_ms"] = (
                        float(stage_timing.get("keypoint_anchor_ms", 0.0)) + _elapsed_ms(keypoint_anchor_started)
                    )
            elif left_pose_estimator is not None and right_pose_estimator is not None:
                keypoint_anchor_started = time.perf_counter()
                try:
                    keypoint_diagnostics = _attach_keypoint_anchor_to_record(
                        record,
                        left_frame=left_tracker_frame,
                        right_frame=right_tracker_frame,
                        left_pose_estimator=left_pose_estimator,
                        right_pose_estimator=right_pose_estimator,
                        min_keypoint_score=min_keypoint_score,
                        pose_association_margin_px=pose_association_margin_px,
                        max_pose_association_distance_px=max_pose_association_distance_px,
                    )
                    diagnostics.update(keypoint_diagnostics)
                except Exception as exc:
                    diagnostics["keypoint_anchor"] = {
                        "kind": "disabled",
                        "fallback_reason": "pose_estimation_failed",
                        "error": str(exc),
                    }
                finally:
                    stage_timing["keypoint_anchor_ms"] = (
                        float(stage_timing.get("keypoint_anchor_ms", 0.0)) + _elapsed_ms(keypoint_anchor_started)
                    )
            elif left_pose_estimator is not None or right_pose_estimator is not None:
                diagnostics["keypoint_anchor"] = {
                    "kind": "disabled",
                    "fallback_reason": "one_eye_pose_estimator_missing",
                }
                diagnostics["keypoint_runtime"] = {
                    "mode": "fallback",
                    "cache_hit": False,
                    "pending": False,
                    "scheduled": False,
                    "fallback_reason": "one_eye_pose_estimator_missing",
                }
            diagnostics.update(record.get("selection", {}))
            message_build_started = time.perf_counter()
            message = build_proxy_targets_message_from_stereo_bbox_record(
                record,
                sequence=sequence,
                card_id=card_id,
                offset_rule=offset_rule,
                recorded_width=recorded_width,
                recorded_height=recorded_height,
                min_confidence=min_confidence,
                max_vertical_error_px=max_vertical_error_px,
                depth_override=depth_override,
            )
            stage_timing["message_build_ms"] = float(stage_timing.get("message_build_ms", 0.0)) + _elapsed_ms(message_build_started)
            if message is None:
                diagnostics["reason"] = "stereo_rejected"
                diagnostics["stereo_rejection_reason"] = "gated"
                diagnostics["non_publish_reason"] = "gated"
                _append_non_published_frame(
                    diagnostics,
                    reason="gated",
                    left_frame_id=left_frame_id,
                    right_frame_id=right_frame_id,
                )
                continue
            if position_filter is not None:
                position_filter_started = time.perf_counter()
                message = apply_position_one_euro_filter(
                    message,
                    position_filter,
                    selection=record.get("selection") if isinstance(record.get("selection"), dict) else None,
                )
                target_filter = message["targets"][0].get("position_filter", {}) if message.get("targets") else {}
                if isinstance(target_filter, dict):
                    diagnostics["position_filter"] = copy.deepcopy(target_filter)
                stage_timing["position_filter_ms"] = (
                    float(stage_timing.get("position_filter_ms", 0.0)) + _elapsed_ms(position_filter_started)
                )
            diagnostics["reason"] = "target_ready"
            diagnostics["non_publish_reason"] = None
            stage_timing["total_ms"] = _elapsed_ms(total_started)
            return message, diagnostics
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    diagnostics["non_publish_reason"] = diagnostics.get("reason") or "no_pair"
    stage_timing["total_ms"] = _elapsed_ms(total_started)
    return None, diagnostics


def _detector_loop(
    state: LatestStereoPublishState,
    hub: BroadcastHub,
    *,
    left_reader: Any,
    right_reader: Any,
    left_tracker: Any,
    right_tracker: Any,
    left_pose_estimator: Any | None = None,
    right_pose_estimator: Any | None = None,
    card_id: str,
    min_confidence: float,
    min_keypoint_score: float,
    pose_association_margin_px: float,
    max_pose_association_distance_px: float,
    recorded_width: int,
    recorded_height: int,
    log_every: int,
    max_empty_reads: int,
    max_vertical_error_px: float | None,
    max_pair_capture_delta_ms: float | None,
    target_source_hz: float,
    position_filter_enabled: bool = True,
    position_filter_min_cutoff: float = DEFAULT_POSITION_FILTER_MIN_CUTOFF,
    position_filter_beta: float = DEFAULT_POSITION_FILTER_BETA,
    position_filter_d_cutoff: float = DEFAULT_POSITION_FILTER_D_CUTOFF,
    keypoint_max_hz: float = DEFAULT_KEYPOINT_MAX_HZ,
    keypoint_reuse_max_age_ms: float = DEFAULT_KEYPOINT_REUSE_MAX_AGE_MS,
    offset_rule: dict[str, Any] | None = None,
    depth_override: DepthOverrideConfig | None = None,
) -> None:
    detector_sequence = 0
    empty_windows = 0
    target_stabilizer = StereoActiveTargetStabilizer()
    position_filter = (
        OneEuroVector3Filter(
            min_cutoff=position_filter_min_cutoff,
            beta=position_filter_beta,
            d_cutoff=position_filter_d_cutoff,
            fallback_hz=target_source_hz,
        )
        if position_filter_enabled
        else None
    )
    keypoint_scheduler = None
    if left_pose_estimator is not None and right_pose_estimator is not None:
        keypoint_scheduler = KeypointAnchorScheduler(
            left_pose_estimator=left_pose_estimator,
            right_pose_estimator=right_pose_estimator,
            min_keypoint_score=min_keypoint_score,
            pose_association_margin_px=pose_association_margin_px,
            max_pose_association_distance_px=max_pose_association_distance_px,
            max_hz=keypoint_max_hz,
            reuse_max_age_ms=keypoint_reuse_max_age_ms,
            async_enabled=True,
        )
    while True:
        if hub.client_count() == 0:
            time.sleep(0.05)
            continue
        message, diagnostics = next_live_stereo_proxy_targets_message_with_diagnostics(
            left_reader=left_reader,
            right_reader=right_reader,
            left_tracker=left_tracker,
            right_tracker=right_tracker,
            left_pose_estimator=left_pose_estimator,
            right_pose_estimator=right_pose_estimator,
            sequence=detector_sequence,
            card_id=card_id,
            offset_rule=offset_rule,
            recorded_width=recorded_width,
            recorded_height=recorded_height,
            min_confidence=min_confidence,
            min_keypoint_score=min_keypoint_score,
            pose_association_margin_px=pose_association_margin_px,
            max_pose_association_distance_px=max_pose_association_distance_px,
            max_empty_reads=max_empty_reads,
            max_vertical_error_px=max_vertical_error_px,
            target_stabilizer=target_stabilizer,
            position_filter=position_filter,
            keypoint_scheduler=keypoint_scheduler,
            max_pair_capture_delta_ms=max_pair_capture_delta_ms,
            target_source_hz=target_source_hz,
            depth_override=depth_override,
        )
        diagnostics["detector_sequence"] = detector_sequence
        state.update(message=message, diagnostics=diagnostics)
        if message is None:
            empty_windows += 1
            if log_every > 0 and empty_windows % log_every == 1:
                print("No stereo target frames available from Left/Right VST SHM + HumanTrackor", flush=True)
                print(format_stereo_diagnostics(diagnostics), flush=True)
            continue

        empty_windows = 0
        if log_every > 0 and detector_sequence % log_every == 0:
            target = message["targets"][0]
            position = target.get("transform", {}).get("position", [0.0, 0.0, 0.0])
            print(
                "updated stereo detector seq=%d target=%s depth_source=%s depth_confidence=%s clients=%d pos=%.3f %.3f %.3f"
                % (
                    detector_sequence,
                    target.get("target_id", "-"),
                    target.get("depth_source", "-"),
                    target.get("depth_confidence", "-"),
                    hub.client_count(),
                    position[0],
                    position[1],
                    position[2],
                ),
                flush=True,
            )
        detector_sequence += 1


def _broadcast_loop(
    hub: BroadcastHub,
    *,
    left_reader: Any,
    right_reader: Any,
    left_tracker: Any,
    right_tracker: Any,
    left_pose_estimator: Any | None = None,
    right_pose_estimator: Any | None = None,
    hz: float,
    card_id: str,
    min_confidence: float,
    min_keypoint_score: float = DEFAULT_MIN_KEYPOINT_SCORE,
    pose_association_margin_px: float = DEFAULT_POSE_ASSOCIATION_MARGIN_PX,
    max_pose_association_distance_px: float = DEFAULT_MAX_POSE_ASSOCIATION_DISTANCE_PX,
    recorded_width: int,
    recorded_height: int,
    log_every: int,
    max_empty_reads: int,
    max_vertical_error_px: float | None,
    depth_trace: Path | None,
    max_pair_capture_delta_ms: float | None,
    target_source_hz: float,
    position_filter_enabled: bool = True,
    position_filter_min_cutoff: float = DEFAULT_POSITION_FILTER_MIN_CUTOFF,
    position_filter_beta: float = DEFAULT_POSITION_FILTER_BETA,
    position_filter_d_cutoff: float = DEFAULT_POSITION_FILTER_D_CUTOFF,
    keypoint_max_hz: float = DEFAULT_KEYPOINT_MAX_HZ,
    keypoint_reuse_max_age_ms: float = DEFAULT_KEYPOINT_REUSE_MAX_AGE_MS,
    offset_rule: dict[str, Any] | None = None,
    depth_override: DepthOverrideConfig | None = None,
) -> None:
    interval_s = 1.0 / max(hz, 0.1)
    sequence = 0
    empty_windows = 0
    state = LatestStereoPublishState()
    threading.Thread(
        target=_detector_loop,
        kwargs={
            "state": state,
            "hub": hub,
            "left_reader": left_reader,
            "right_reader": right_reader,
            "left_tracker": left_tracker,
            "right_tracker": right_tracker,
            "left_pose_estimator": left_pose_estimator,
            "right_pose_estimator": right_pose_estimator,
            "card_id": card_id,
            "offset_rule": offset_rule,
            "min_confidence": min_confidence,
            "min_keypoint_score": min_keypoint_score,
            "pose_association_margin_px": pose_association_margin_px,
            "max_pose_association_distance_px": max_pose_association_distance_px,
            "recorded_width": recorded_width,
            "recorded_height": recorded_height,
            "log_every": log_every,
            "max_empty_reads": max_empty_reads,
            "max_vertical_error_px": max_vertical_error_px,
            "max_pair_capture_delta_ms": max_pair_capture_delta_ms,
            "target_source_hz": target_source_hz,
            "position_filter_enabled": position_filter_enabled,
            "position_filter_min_cutoff": position_filter_min_cutoff,
            "position_filter_beta": position_filter_beta,
            "position_filter_d_cutoff": position_filter_d_cutoff,
            "keypoint_max_hz": keypoint_max_hz,
            "keypoint_reuse_max_age_ms": keypoint_reuse_max_age_ms,
            "depth_override": depth_override,
        },
        daemon=True,
    ).start()
    while True:
        started = time.perf_counter()
        event = publish_latest_stereo_state_once(
            hub=hub,
            state=state,
            sequence=sequence,
            depth_trace=depth_trace,
            stale_after_ms=max(interval_s * 1000.0 * 2.0, 100.0),
        )
        if event is None:
            time.sleep(interval_s)
            continue
        if event.get("event") == "accepted":
            empty_windows = 0
            if log_every > 0 and sequence % log_every == 0:
                print(
                    "published stereo seq=%d target=%s freshness=%s depth_source=%s depth_confidence=%s clients=%d"
                    % (
                        sequence,
                        event.get("target_id", "-"),
                        (event.get("freshness") or {}).get("state", "-"),
                        event.get("depth_source", "-"),
                        event.get("depth_confidence", "-"),
                        int(event.get("delivered_clients") or 0),
                    ),
                    flush=True,
                )
        else:
            empty_windows += 1
            if log_every > 0 and empty_windows % log_every == 1:
                print("No latest stereo target available to publish", flush=True)
        sequence += 1
        elapsed_s = time.perf_counter() - started
        time.sleep(max(0.0, interval_s - elapsed_s))


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
        left_pose_estimator, right_pose_estimator = create_pose_estimators(args)
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
            source_label = "Left/Right VST SHM + HumanTrackor bbox stereo"
            if args.enable_keypoint_anchor:
                source_label += " + YOLO pose keypoint anchor"
            print(f"source: {source_label}", flush=True)
            if args.enable_keypoint_anchor:
                print(
                    "keypoint_anchor_runtime=max_hz=%.3f reuse_max_age_ms=%.1f"
                    % (args.keypoint_max_hz, args.keypoint_reuse_max_age_ms),
                    flush=True,
                )
            print("waiting for WebSocket client; sent seq appears after a stereo pair passes confidence/depth gates", flush=True)
            offset_rule = load_card_offset_rule(args.smartxr_options)
            print(
                "card_offset_rule=%s"
                % json.dumps(offset_rule, ensure_ascii=False, separators=(",", ":")),
                flush=True,
            )
            depth_override = depth_override_config_from_args(args)
            if depth_override.normalized_mode() != "real":
                print(
                    "depth_override=%s"
                    % json.dumps(
                        apply_depth_override(1.0, depth_override, sequence=0),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    flush=True,
                )
            hub = BroadcastHub()
            threading.Thread(
                target=_broadcast_loop,
                kwargs={
                    "hub": hub,
                    "left_reader": left_reader,
                    "right_reader": right_reader,
                    "left_tracker": left_tracker,
                    "right_tracker": right_tracker,
                    "left_pose_estimator": left_pose_estimator,
                    "right_pose_estimator": right_pose_estimator,
                    "hz": args.hz,
                    "card_id": args.card_id,
                    "offset_rule": offset_rule,
                    "min_confidence": args.min_confidence,
                    "min_keypoint_score": args.min_keypoint_score,
                    "pose_association_margin_px": args.pose_association_margin_px,
                    "max_pose_association_distance_px": args.max_pose_association_distance_px,
                    "recorded_width": args.recorded_width,
                    "recorded_height": args.recorded_height,
                    "log_every": args.log_every,
                    "max_empty_reads": args.max_empty_reads,
                    "max_vertical_error_px": args.max_vertical_error_px,
                    "depth_trace": args.depth_trace,
                    "max_pair_capture_delta_ms": args.max_pair_capture_delta_ms,
                    "target_source_hz": args.target_source_hz,
                    "position_filter_enabled": not args.disable_position_one_euro_filter,
                    "position_filter_min_cutoff": args.position_filter_min_cutoff,
                    "position_filter_beta": args.position_filter_beta,
                    "position_filter_d_cutoff": args.position_filter_d_cutoff,
                    "keypoint_max_hz": args.keypoint_max_hz,
                    "keypoint_reuse_max_age_ms": args.keypoint_reuse_max_age_ms,
                    "depth_override": depth_override,
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


def depth_override_config_from_args(args: argparse.Namespace) -> DepthOverrideConfig:
    return DepthOverrideConfig(
        mode=getattr(args, "depth_override_mode", "real"),
        fixed_m=getattr(args, "depth_override_fixed_m", None),
        scale=getattr(args, "depth_override_scale", 1.0),
        offset_m=getattr(args, "depth_override_offset_m", 0.0),
        noise_std_m=getattr(args, "depth_override_noise_std_m", 0.0),
        seed=getattr(args, "depth_override_seed", 0),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish live proxy_targets from Antman Left/Right VST SHM stereo depth.")
    parser.add_argument("--antman-root", type=Path, default=DEFAULT_ANTMAN_ROOT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--card-id", default="CardAnchor")
    parser.add_argument("--smartxr-options", type=Path, default=None)
    parser.add_argument("--log-every", type=int, default=20)
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--max-empty-reads", type=int, default=120)
    parser.add_argument("--max-vertical-error-px", type=float, default=None)
    parser.add_argument("--max-pair-capture-delta-ms", type=float, default=DEFAULT_MAX_PAIR_CAPTURE_DELTA_MS)
    parser.add_argument("--target-source-hz", type=float, default=DEFAULT_SOURCE_HZ)
    parser.add_argument("--depth-trace", type=Path, default=None)
    parser.add_argument("--disable-position-one-euro-filter", action="store_true")
    parser.add_argument("--position-filter-min-cutoff", type=float, default=DEFAULT_POSITION_FILTER_MIN_CUTOFF)
    parser.add_argument("--position-filter-beta", type=float, default=DEFAULT_POSITION_FILTER_BETA)
    parser.add_argument("--position-filter-d-cutoff", type=float, default=DEFAULT_POSITION_FILTER_D_CUTOFF)
    parser.add_argument("--depth-override-mode", choices=DEPTH_OVERRIDE_MODES, default="real")
    parser.add_argument("--depth-override-fixed-m", type=float, default=None)
    parser.add_argument("--depth-override-scale", type=float, default=1.0)
    parser.add_argument("--depth-override-offset-m", type=float, default=0.0)
    parser.add_argument("--depth-override-noise-std-m", type=float, default=0.0)
    parser.add_argument("--depth-override-seed", type=int, default=0)
    parser.add_argument("--recorded-width", type=int, default=880)
    parser.add_argument("--recorded-height", type=int, default=660)
    parser.add_argument("--vst-reader", choices=("vst_ai_shm", "legacy"), default="vst_ai_shm")
    parser.add_argument("--vst-ai-shm-root", type=Path, default=Path("E:/xia/Antman/0422/0527/P1/vst_ai_shm"))
    parser.add_argument("--shm-name", default="Antman.VST.AI.v1")
    parser.add_argument("--shm-namespace", default=None)
    parser.add_argument("--wait-timeout-ms", type=int, default=1000)
    parser.add_argument("--wait-for-producer-seconds", type=float, default=10.0)
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--backend", default="ultralytics")
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--device", default=None)
    parser.add_argument("--enable-keypoint-anchor", action="store_true")
    parser.add_argument("--pose-model", default=DEFAULT_POSE_MODEL)
    parser.add_argument("--pose-imgsz", type=int, default=DEFAULT_POSE_IMGSZ)
    parser.add_argument("--pose-conf", type=float, default=DEFAULT_POSE_CONFIDENCE)
    parser.add_argument("--pose-device", default=None)
    parser.add_argument("--min-keypoint-score", type=float, default=DEFAULT_MIN_KEYPOINT_SCORE)
    parser.add_argument("--pose-association-margin-px", type=float, default=DEFAULT_POSE_ASSOCIATION_MARGIN_PX)
    parser.add_argument("--max-pose-association-distance-px", type=float, default=DEFAULT_MAX_POSE_ASSOCIATION_DISTANCE_PX)
    parser.add_argument("--keypoint-max-hz", type=float, default=DEFAULT_KEYPOINT_MAX_HZ)
    parser.add_argument("--keypoint-reuse-max-age-ms", type=float, default=DEFAULT_KEYPOINT_REUSE_MAX_AGE_MS)
    return parser.parse_args(argv)


def _parse_args() -> argparse.Namespace:
    return parse_args()


def main() -> int:
    return serve(_parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
