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

from dump_antman_vst_humantrackor_jsonl import (  # noqa: E402
    DEFAULT_ANTMAN_ROOT,
    _create_live_reader_and_tracker,
    build_frame_record,
    startup_error_status,
)
from smartxr.frames import normalize_frame  # noqa: E402
from smartxr.publisher import DEFAULT_TARGET_DEPTH_M, normalize_source_payload  # noqa: E402
from smartxr.transport import (  # noqa: E402
    drain_client_frames as _drain_client_frames,
    encode_websocket_text_frame,
    handshake as _handshake,
)


def _people_count(tracking_result: Any) -> int:
    people = getattr(tracking_result, "people", None)
    if people is None:
        return 0
    try:
        return len(people)
    except TypeError:
        return 0


def _empty_diagnostics(reason: str) -> dict[str, Any]:
    return {
        "reason": reason,
        "read_attempts": 0,
        "frames_seen": 0,
        "last_frame_id": -1,
        "tracker_people": 0,
        "source_stats": {},
    }


def format_source_diagnostics(diagnostics: dict[str, Any]) -> str:
    source_stats = diagnostics.get("source_stats") or {}
    stats_text = ",".join(f"{key}={source_stats[key]}" for key in sorted(source_stats))
    if not stats_text:
        stats_text = "-"
    return (
        "source diagnostics: reason=%s reads=%d frames=%d last_frame_id=%s tracker_people=%d source_stats=%s"
        % (
            diagnostics.get("reason", "-"),
            int(diagnostics.get("read_attempts", 0)),
            int(diagnostics.get("frames_seen", 0)),
            diagnostics.get("last_frame_id", -1),
            int(diagnostics.get("tracker_people", 0)),
            stats_text,
        )
    )


def build_proxy_targets_message_from_live_frame(
    *,
    frame: Any,
    frame_id: int,
    timestamp_ms: int,
    tracking_result: Any,
    sequence: int,
    card_id: str = "CardAnchor",
    min_confidence: float = 0.5,
    default_depth_m: float = DEFAULT_TARGET_DEPTH_M,
    source_stats: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    record = build_frame_record(
        frame=frame,
        frame_id=frame_id,
        timestamp_ms=timestamp_ms,
        tracking_result=tracking_result,
        source_stats=source_stats,
    )
    normalized = normalize_frame(record, index=int(frame_id), min_confidence=min_confidence)
    message = normalize_source_payload(
        normalized,
        sequence=sequence,
        card_id=card_id,
        default_depth_m=default_depth_m,
    )
    if not message["targets"]:
        return None
    return message


def next_live_proxy_targets_message(
    *,
    reader: Any,
    tracker: Any,
    sequence: int,
    card_id: str = "CardAnchor",
    min_confidence: float = 0.5,
    default_depth_m: float = DEFAULT_TARGET_DEPTH_M,
    max_empty_reads: int = 120,
    sleep_seconds: float = 0.005,
) -> dict[str, Any] | None:
    message, _diagnostics = next_live_proxy_targets_message_with_diagnostics(
        reader=reader,
        tracker=tracker,
        sequence=sequence,
        card_id=card_id,
        min_confidence=min_confidence,
        default_depth_m=default_depth_m,
        max_empty_reads=max_empty_reads,
        sleep_seconds=sleep_seconds,
    )
    return message


def next_live_proxy_targets_message_with_diagnostics(
    *,
    reader: Any,
    tracker: Any,
    sequence: int,
    card_id: str = "CardAnchor",
    min_confidence: float = 0.5,
    default_depth_m: float = DEFAULT_TARGET_DEPTH_M,
    max_empty_reads: int = 120,
    sleep_seconds: float = 0.005,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    diagnostics = _empty_diagnostics("no_frame")
    for _ in range(max(1, int(max_empty_reads))):
        diagnostics["read_attempts"] += 1
        ok, frame_id, frame = reader.read_latest()
        if not ok:
            diagnostics["reason"] = "read_failed"
            diagnostics["source_stats"] = reader.get_stats() if hasattr(reader, "get_stats") else {}
            return None, diagnostics
        if frame is None or int(frame_id) < 0:
            diagnostics["source_stats"] = reader.get_stats() if hasattr(reader, "get_stats") else {}
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            continue

        diagnostics["frames_seen"] += 1
        diagnostics["last_frame_id"] = int(frame_id)
        tracking_result = tracker.process_frame(frame)
        diagnostics["tracker_people"] = _people_count(tracking_result)
        source_stats = reader.get_stats() if hasattr(reader, "get_stats") else {}
        diagnostics["source_stats"] = source_stats
        message = build_proxy_targets_message_from_live_frame(
            frame=frame,
            frame_id=int(frame_id),
            timestamp_ms=int(time.time() * 1000),
            tracking_result=tracking_result,
            sequence=sequence,
            card_id=card_id,
            min_confidence=min_confidence,
            default_depth_m=default_depth_m,
            source_stats=source_stats,
        )
        if message is not None:
            diagnostics["reason"] = "target_ready"
            return message, diagnostics
        diagnostics["reason"] = "no_target"
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return None, diagnostics


def _publish_loop(
    conn: socket.socket,
    *,
    reader: Any,
    tracker: Any,
    hz: float,
    card_id: str,
    min_confidence: float,
    log_every: int,
    max_empty_reads: int,
) -> None:
    interval_s = 1.0 / max(hz, 0.1)
    sequence = 0
    empty_windows = 0
    while True:
        if not _drain_client_frames(conn):
            return
        message, diagnostics = next_live_proxy_targets_message_with_diagnostics(
            reader=reader,
            tracker=tracker,
            sequence=sequence,
            card_id=card_id,
            min_confidence=min_confidence,
            max_empty_reads=max_empty_reads,
        )
        if message is None:
            empty_windows += 1
            if log_every > 0 and empty_windows % log_every == 1:
                print("No target frames available from VST SHM + HumanTrackor", flush=True)
                print(format_source_diagnostics(diagnostics), flush=True)
            time.sleep(interval_s)
            continue

        empty_windows = 0
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        conn.sendall(encode_websocket_text_frame(payload))
        if log_every > 0 and sequence % log_every == 0:
            target = message["targets"][0]
            position = target.get("transform", {}).get("position", [0.0, 0.0, 0.0])
            print(
                "sent seq=%d source=%s target=%s pos=%.3f %.3f %.3f"
                % (sequence, target.get("source", "-"), target.get("target_id", "-"), position[0], position[1], position[2]),
                flush=True,
            )
        sequence += 1
        time.sleep(interval_s)


def serve(args: argparse.Namespace) -> int:
    try:
        reader, tracker = _create_live_reader_and_tracker(args)
    except Exception as exc:
        status, exit_code = startup_error_status(exc, Path(".tmp/antman_vst_proxy_targets_live_publisher.jsonl"))
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")), flush=True)
        return exit_code

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((args.host, args.port))
            server.listen(1)
            print(f"proxy_targets live publisher listening on ws://{args.host}:{args.port}/proxy_targets", flush=True)
            print("source: VST SHM + HumanTrackor", flush=True)
            print("waiting for WebSocket client; sent seq appears after a client connects and a target frame passes confidence gate", flush=True)
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
                            reader=reader,
                            tracker=tracker,
                            hz=args.hz,
                            card_id=args.card_id,
                            min_confidence=args.min_confidence,
                            log_every=args.log_every,
                            max_empty_reads=args.max_empty_reads,
                        )
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        print(f"client disconnected: {address}", flush=True)
    finally:
        if "reader" in locals() and hasattr(reader, "release"):
            reader.release()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish live proxy_targets from Antman VST SHM + HumanTrackor.")
    parser.add_argument("--antman-root", type=Path, default=DEFAULT_ANTMAN_ROOT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--card-id", default="CardAnchor")
    parser.add_argument("--log-every", type=int, default=20)
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--max-empty-reads", type=int, default=120)
    parser.add_argument("--shm-name", default="Antman.VST.AI.v1")
    parser.add_argument("--shm-eye", default="Right", help='VST eye suffix: "Right", "Left", or "" for legacy unsuffixed SHM')
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
