from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import select
import socket
import struct
import time
from typing import Dict, Tuple


WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def build_proxy_targets_message(
    elapsed_s: float,
    target_id: str = "person-7",
    card_id: str = "CardAnchor",
    radius_m: float = 0.25,
    depth_m: float = 1.2,
    sequence: int = 0,
    mode: str = "moving",
) -> Dict:
    if mode == "static":
        x = 0.0
        y = 0.0
        z = -depth_m
    else:
        x = math.sin(elapsed_s) * radius_m
        y = math.sin(elapsed_s * 0.5) * 0.08
        z = -depth_m + math.cos(elapsed_s) * 0.08
    return {
        "type": "proxy_targets",
        "schema_version": 1,
        "sequence": sequence,
        "targets": [
            {
                "target_id": target_id,
                "source": "fake_vst",
                "state": "tracked",
                "confidence": 0.96,
                "timestamp_ms": int(time.time() * 1000),
                "transform": {
                    "position": [x, y, z],
                    "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                    "scale": [1.0, 1.0, 1.0],
                },
            }
        ],
        "cards": [
            {
                "card_id": card_id,
                "target_id": target_id,
                "offset_rule": {
                    "mode": "custom",
                    "offset_space": "world",
                    "x_m": 0.0,
                    "y_m": 0.0,
                    "z_m": 0.0,
                    "fallback": "hold_last_pose",
                },
            }
        ],
    }


def encode_websocket_text_frame(payload: str) -> bytes:
    data = payload.encode("utf-8")
    length = len(data)
    if length < 126:
        header = struct.pack("!BB", 0x81, length)
    elif length <= 0xFFFF:
        header = struct.pack("!BBH", 0x81, 126, length)
    else:
        header = struct.pack("!BBQ", 0x81, 127, length)
    return header + data


def encode_websocket_control_frame(opcode: int, payload: bytes = b"") -> bytes:
    if len(payload) >= 126:
        raise ValueError("control frame payload too large")
    return struct.pack("!BB", 0x80 | opcode, len(payload)) + payload


def decode_websocket_frame(frame: bytes) -> Tuple[int, str]:
    if len(frame) < 2:
        raise ValueError("incomplete websocket frame")
    first, second = frame[0], frame[1]
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    index = 2
    if length == 126:
        if len(frame) < index + 2:
            raise ValueError("incomplete websocket frame length")
        length = struct.unpack("!H", frame[index : index + 2])[0]
        index += 2
    elif length == 127:
        if len(frame) < index + 8:
            raise ValueError("incomplete websocket frame length")
        length = struct.unpack("!Q", frame[index : index + 8])[0]
        index += 8
    mask = b""
    if masked:
        if len(frame) < index + 4:
            raise ValueError("incomplete websocket frame mask")
        mask = frame[index : index + 4]
        index += 4
    if len(frame) < index + length:
        raise ValueError("incomplete websocket frame payload")
    payload = frame[index : index + length]
    if masked:
        payload = bytes(value ^ mask[offset % 4] for offset, value in enumerate(payload))
    return opcode, payload.decode("utf-8", errors="replace")


def _drain_client_frames(conn: socket.socket) -> bool:
    keep_open = True
    while True:
        readable, _, _ = select.select([conn], [], [], 0)
        if not readable:
            return keep_open
        frame = conn.recv(4096)
        if not frame:
            return False
        try:
            opcode, payload = decode_websocket_frame(frame)
        except ValueError as exc:
            print(f"client frame decode failed: {exc}", flush=True)
            continue
        if opcode == 0x1:
            print(f"client text: {payload}", flush=True)
        elif opcode == 0x8:
            conn.sendall(encode_websocket_control_frame(0x8))
            return False
        elif opcode == 0x9:
            conn.sendall(encode_websocket_control_frame(0xA, payload.encode("utf-8")))
        elif opcode == 0xA:
            print("client pong", flush=True)


def _read_http_request(conn: socket.socket) -> str:
    chunks = []
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\r\n\r\n" in chunk:
            break
    return b"".join(chunks).decode("utf-8", errors="replace")


def _parse_headers(request: str) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for line in request.splitlines()[1:]:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return headers


def _handshake(conn: socket.socket) -> Tuple[bool, str]:
    request = _read_http_request(conn)
    first_line = request.splitlines()[0] if request else ""
    headers = _parse_headers(request)
    key = headers.get("sec-websocket-key", "")
    if not first_line.startswith("GET ") or not key:
        return False, first_line
    accept = base64.b64encode(hashlib.sha1((key + WEBSOCKET_GUID).encode("ascii")).digest()).decode("ascii")
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    )
    conn.sendall(response.encode("ascii"))
    return True, first_line


def _publish_loop(conn: socket.socket, hz: float, target_id: str, card_id: str, mode: str, log_every: int) -> None:
    start = time.monotonic()
    interval_s = 1.0 / max(hz, 0.1)
    sequence = 0
    while True:
        if not _drain_client_frames(conn):
            return
        elapsed_s = time.monotonic() - start
        message = build_proxy_targets_message(
            elapsed_s,
            target_id=target_id,
            card_id=card_id,
            sequence=sequence,
            mode=mode,
        )
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        conn.sendall(encode_websocket_text_frame(payload))
        if log_every > 0 and sequence % log_every == 0:
            position = message["targets"][0]["transform"]["position"]
            print(
                "sent seq=%d mode=%s pos=%.3f %.3f %.3f"
                % (sequence, mode, position[0], position[1], position[2]),
                flush=True,
        )
        sequence += 1
        time.sleep(interval_s)


def serve(host: str, port: int, hz: float, target_id: str, card_id: str, mode: str, log_every: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(1)
        print(f"proxy_targets fake publisher listening on ws://{host}:{port}/proxy_targets", flush=True)
        while True:
            conn, address = server.accept()
            with conn:
                ok, first_line = _handshake(conn)
                if not ok:
                    print(f"rejected {address}: {first_line}", flush=True)
                    continue
                print(f"client connected from {address}: {first_line}", flush=True)
                try:
                    _publish_loop(conn, hz=hz, target_id=target_id, card_id=card_id, mode=mode, log_every=log_every)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    print(f"client disconnected: {address}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve moving proxy_targets messages for Windows PCMR validation.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--target-id", default="person-7")
    parser.add_argument("--card-id", default="CardAnchor")
    parser.add_argument("--mode", default="moving", choices=["moving", "static"])
    parser.add_argument("--log-every", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    serve(args.host, args.port, args.hz, args.target_id, args.card_id, args.mode, args.log_every)


if __name__ == "__main__":
    main()
