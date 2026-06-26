from __future__ import annotations

import argparse
import json
import socket
import sys
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


def _read_one_eye(reader: Any, pending: dict[int, Any], seen: set[int]) -> int:
    ok, frame_id, frame = reader.read_latest()
    if not ok:
        return 1
    if frame is None or int(frame_id) < 0:
        return 0
    frame_key = int(frame_id)
    if frame_key not in seen:
        seen.add(frame_key)
        pending[frame_key] = frame
    return 0


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
    return message


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
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    attempts = max_read_attempts if max_read_attempts is not None else max_empty_reads
    diagnostics = _empty_diagnostics("no_pair")
    pending_left: dict[int, Any] = {}
    pending_right: dict[int, Any] = {}
    seen_left: set[int] = set()
    seen_right: set[int] = set()
    for _ in range(max(1, int(attempts if attempts is not None else 120))):
        diagnostics["read_attempts"] += 1
        _read_one_eye(left_reader, pending_left, seen_left)
        _read_one_eye(right_reader, pending_right, seen_right)
        diagnostics["frames_seen_left"] = len(seen_left)
        diagnostics["frames_seen_right"] = len(seen_right)
        diagnostics["left_pending"] = len(pending_left)
        diagnostics["right_pending"] = len(pending_right)
        diagnostics["left_source_stats"] = left_reader.get_stats() if hasattr(left_reader, "get_stats") else {}
        diagnostics["right_source_stats"] = right_reader.get_stats() if hasattr(right_reader, "get_stats") else {}

        for frame_id in sorted(set(pending_left).intersection(pending_right)):
            left_frame = pending_left.pop(frame_id)
            right_frame = pending_right.pop(frame_id)
            record = build_stereo_bbox_pair_record(
                frame_id=frame_id,
                left_frame=left_frame,
                right_frame=right_frame,
                left_tracking_result=left_tracker.process_frame(left_frame),
                right_tracking_result=right_tracker.process_frame(right_frame),
                timestamp_ms=int(time.time() * 1000),
                left_source_stats=diagnostics["left_source_stats"],
                right_source_stats=diagnostics["right_source_stats"],
            )
            diagnostics["last_pair_frame_id"] = frame_id
            if record is None:
                diagnostics["reason"] = "no_target"
                continue
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


def _publish_loop(
    conn: socket.socket,
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
) -> None:
    interval_s = 1.0 / max(hz, 0.1)
    sequence = 0
    empty_windows = 0
    while True:
        if not _drain_client_frames(conn):
            return
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
        )
        if message is None:
            empty_windows += 1
            if log_every > 0 and empty_windows % log_every == 1:
                print("No stereo target frames available from Left/Right VST SHM + HumanTrackor", flush=True)
                print(format_stereo_diagnostics(diagnostics), flush=True)
            time.sleep(interval_s)
            continue

        empty_windows = 0
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        conn.sendall(encode_websocket_text_frame(payload))
        if log_every > 0 and sequence % log_every == 0:
            target = message["targets"][0]
            position = target.get("transform", {}).get("position", [0.0, 0.0, 0.0])
            print(
                "sent stereo seq=%d target=%s depth_source=%s depth_confidence=%s pos=%.3f %.3f %.3f"
                % (
                    sequence,
                    target.get("target_id", "-"),
                    target.get("depth_source", "-"),
                    target.get("depth_confidence", "-"),
                    position[0],
                    position[1],
                    position[2],
                ),
                flush=True,
            )
        sequence += 1
        time.sleep(interval_s)


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
            server.listen(1)
            print(f"stereo proxy_targets live publisher listening on ws://{args.host}:{args.port}/proxy_targets", flush=True)
            print("source: Left/Right VST SHM + HumanTrackor bbox stereo", flush=True)
            print("waiting for WebSocket client; sent seq appears after a stereo pair passes confidence/depth gates", flush=True)
            while True:
                conn, address = server.accept()
                with conn:
                    ok, first_line = _handshake(conn)
                    if not ok:
                        print(f"rejected {address}: {first_line}", flush=True)
                        continue
                    print(f"client connected from {address}: {first_line}", flush=True)
                    try:
                        _publish_loop(
                            conn,
                            left_reader=left_reader,
                            right_reader=right_reader,
                            left_tracker=left_tracker,
                            right_tracker=right_tracker,
                            hz=args.hz,
                            card_id=args.card_id,
                            min_confidence=args.min_confidence,
                            recorded_width=args.recorded_width,
                            recorded_height=args.recorded_height,
                            log_every=args.log_every,
                            max_empty_reads=args.max_empty_reads,
                            max_vertical_error_px=args.max_vertical_error_px,
                        )
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        print(f"client disconnected: {address}", flush=True)
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
