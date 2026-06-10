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

from fake_proxy_targets_publisher import (  # noqa: E402
    _drain_client_frames,
    _handshake,
    encode_websocket_text_frame,
)
from capture_vst_target_sample_session import normalize_frame  # noqa: E402


def _as_float(value: Any, fallback: float) -> float:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    return fallback


def _target_id(source: str, raw_id: Any, index: int) -> str:
    value = str(raw_id or f"target-{index}")
    if value.startswith(f"{source}-"):
        return value
    return f"{source}-{value}"


def _canonical_state(raw_state: Any) -> str:
    state = str(raw_state or "tracked").strip().lower()
    if state in {"tracked", "predicted", "stale", "lost"}:
        return state
    if state in {"new", "active", "confirmed"}:
        return "tracked"
    if state in {"missing", "occluded"}:
        return "predicted"
    if state in {"removed", "deleted"}:
        return "lost"
    return "tracked"


def _bbox_position(detection: dict[str, Any], root_image: dict[str, Any], default_depth_m: float) -> list[float]:
    bbox = detection.get("bbox", {})
    image = detection.get("image", root_image)
    depth_m = _as_float(detection.get("depth_m"), default_depth_m)
    if not isinstance(bbox, dict) or not isinstance(image, dict):
        return [0.0, 0.0, -depth_m]

    image_w = max(_as_float(image.get("w"), 1.0), 1.0)
    image_h = max(_as_float(image.get("h"), 1.0), 1.0)
    cx = _as_float(bbox.get("cx"), image_w * 0.5)
    cy = _as_float(bbox.get("cy"), image_h * 0.5)

    nx = (cx / image_w - 0.5) * 2.0
    ny = (0.5 - cy / image_h) * 2.0
    return [nx * depth_m * 0.5, ny * depth_m * 0.5, -depth_m]


def _transform_from_detection(
    detection: dict[str, Any],
    root_image: dict[str, Any],
    default_depth_m: float,
) -> dict[str, list[float]]:
    transform = detection.get("transform")
    if isinstance(transform, dict):
        return {
            "position": list(transform.get("position", [0.0, 0.0, -default_depth_m])),
            "rotation_xyzw": list(transform.get("rotation_xyzw", [0.0, 0.0, 0.0, 1.0])),
            "scale": list(transform.get("scale", [1.0, 1.0, 1.0])),
        }
    position = detection.get("position")
    if isinstance(position, list) and len(position) >= 3:
        parsed_position = [float(position[0]), float(position[1]), float(position[2])]
    else:
        parsed_position = _bbox_position(detection, root_image, default_depth_m)
    return {
        "position": parsed_position,
        "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
        "scale": [1.0, 1.0, 1.0],
    }


def normalize_source_payload(
    source_payload: dict[str, Any],
    sequence: int | None = None,
    card_id: str = "CardAnchor",
    default_depth_m: float = 1.2,
) -> dict[str, Any]:
    if source_payload.get("type") == "proxy_targets":
        message = json.loads(json.dumps(source_payload))
        if sequence is not None:
            message["sequence"] = sequence
        return message

    source = str(source_payload.get("source", "vst"))
    output_sequence = int(sequence if sequence is not None else source_payload.get("sequence", 0))
    timestamp_ms = _as_float(source_payload.get("timestamp_ms"), time.time() * 1000.0)
    root_image = source_payload.get("image", {})
    if not isinstance(root_image, dict):
        root_image = {}

    detections = source_payload.get("detections")
    if not isinstance(detections, list):
        detections = source_payload.get("targets")
    if not isinstance(detections, list):
        detections = [source_payload]

    targets: list[dict[str, Any]] = []
    for index, detection in enumerate(detections):
        if not isinstance(detection, dict):
            continue
        raw_id = detection.get("target_id", detection.get("id", detection.get("track_id")))
        target_id = _target_id(source, raw_id, index)
        targets.append(
            {
                "target_id": target_id,
                "source": source,
                "state": _canonical_state(detection.get("state", "tracked")),
                "confidence": _as_float(detection.get("confidence"), 1.0),
                "timestamp_ms": _as_float(detection.get("timestamp_ms"), timestamp_ms),
                "transform": _transform_from_detection(detection, root_image, default_depth_m),
            }
        )

    cards = []
    if targets:
        cards.append(
            {
                "card_id": card_id,
                "target_id": targets[0]["target_id"],
                "offset_rule": {
                    "mode": "right_top",
                    "offset_space": "world",
                    "right_m": 0.35,
                    "up_m": 0.25,
                    "fallback": "hold_last_pose",
                },
            }
        )

    return {
        "type": "proxy_targets",
        "schema_version": 1,
        "sequence": output_sequence,
        "targets": targets,
        "cards": cards,
    }


def load_source_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"source payload must be an object: {path}")
    return payload


def load_source_messages(path: Path, card_id: str = "CardAnchor", default_depth_m: float = 1.2) -> list[dict[str, Any]]:
    if path.suffix.lower() != ".jsonl":
        return [normalize_source_payload(load_source_payload(path), card_id=card_id, default_depth_m=default_depth_m)]

    messages: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError(f"source JSONL line must be an object: {path}:{line_number}")
            normalized_frame = normalize_frame(payload, index=line_number, min_confidence=0.0)
            message = normalize_source_payload(normalized_frame, card_id=card_id, default_depth_m=default_depth_m)
            if message["targets"]:
                messages.append(message)
    if not messages:
        raise ValueError(f"source JSONL did not contain any target frames: {path}")
    return messages


def replay_message_at(source_messages: list[dict[str, Any]], sequence: int) -> dict[str, Any]:
    if not source_messages:
        raise ValueError("source_messages must not be empty")
    message = json.loads(json.dumps(source_messages[sequence % len(source_messages)]))
    message["sequence"] = sequence
    return message


def _publish_loop(conn: socket.socket, input_path: Path, hz: float, card_id: str, log_every: int) -> None:
    interval_s = 1.0 / max(hz, 0.1)
    source_messages = load_source_messages(input_path, card_id=card_id)
    sequence = 0
    while True:
        if not _drain_client_frames(conn):
            return
        message = replay_message_at(source_messages, sequence)
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        conn.sendall(encode_websocket_text_frame(payload))
        if log_every > 0 and sequence % log_every == 0:
            target = message["targets"][0] if message["targets"] else {}
            position = target.get("transform", {}).get("position", [0.0, 0.0, 0.0])
            print(
                "sent seq=%d source=%s target=%s pos=%.3f %.3f %.3f"
                % (
                    sequence,
                    target.get("source", "-"),
                    target.get("target_id", "-"),
                    position[0],
                    position[1],
                    position[2],
                ),
                flush=True,
            )
        sequence += 1
        time.sleep(interval_s)


def serve(host: str, port: int, input_path: Path, hz: float, card_id: str, log_every: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(1)
        print(f"proxy_targets publisher listening on ws://{host}:{port}/proxy_targets", flush=True)
        print(f"source input: {input_path}", flush=True)
        while True:
            conn, address = server.accept()
            with conn:
                ok, first_line = _handshake(conn)
                if not ok:
                    print(f"rejected {address}: {first_line}", flush=True)
                    continue
                print(f"client connected from {address}: {first_line}", flush=True)
                try:
                    _publish_loop(conn, input_path=input_path, hz=hz, card_id=card_id, log_every=log_every)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    print(f"client disconnected: {address}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adapt VST/external source JSON into proxy_targets messages.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--print-once", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--card-id", default="CardAnchor")
    parser.add_argument("--log-every", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.print_once:
        print(json.dumps(load_source_messages(args.input, card_id=args.card_id)[0], separators=(",", ":")))
        return 0
    serve(args.host, args.port, args.input, args.hz, args.card_id, args.log_every)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
