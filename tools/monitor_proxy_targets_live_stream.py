from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from validate_proxy_targets_payload_schema import validate_message  # noqa: E402


def _read_exact(conn: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = conn.recv(remaining)
        if not chunk:
            raise ConnectionError("connection closed while reading websocket frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _encode_masked_text_frame(payload: str) -> bytes:
    data = payload.encode("utf-8")
    length = len(data)
    if length < 126:
        header = struct.pack("!BB", 0x81, 0x80 | length)
    elif length <= 0xFFFF:
        header = struct.pack("!BBH", 0x81, 0x80 | 126, length)
    else:
        header = struct.pack("!BBQ", 0x81, 0x80 | 127, length)
    mask = os.urandom(4)
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
    return header + mask + masked


def _encode_masked_control_frame(opcode: int, payload: bytes = b"") -> bytes:
    if len(payload) >= 126:
        raise ValueError("control frame payload too large")
    mask = os.urandom(4)
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    return struct.pack("!BB", 0x80 | opcode, 0x80 | len(payload)) + mask + masked


def _read_websocket_text(conn: socket.socket) -> str | None:
    first, second = _read_exact(conn, 2)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(conn, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(conn, 8))[0]
    mask = _read_exact(conn, 4) if masked else b""
    payload = _read_exact(conn, length)
    if masked:
        payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))

    if opcode == 0x1:
        return payload.decode("utf-8", errors="replace")
    if opcode == 0x8:
        return None
    if opcode == 0x9:
        conn.sendall(_encode_masked_control_frame(0xA, payload))
        return ""
    return ""


def _perform_client_handshake(conn: socket.socket, host: str, port: int, path: str) -> None:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    conn.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = conn.recv(4096)
        if not chunk:
            break
        response += chunk
    first_line = response.decode("utf-8", errors="replace").splitlines()[0] if response else ""
    if " 101 " not in first_line:
        raise ConnectionError(f"websocket handshake failed: {first_line}")


def analyze_messages(messages: list[dict[str, Any]], min_packets: int) -> dict[str, Any]:
    errors: list[str] = []
    sequences: list[int] = []
    target_ids: set[str] = set()
    first_positions: dict[str, list[float]] = {}
    position_changed = False

    for index, message in enumerate(messages):
        schema_errors = validate_message(message)
        errors.extend(f"packet[{index}]: {error}" for error in schema_errors)

        sequence = message.get("sequence")
        if isinstance(sequence, int) and not isinstance(sequence, bool):
            sequences.append(sequence)

        for target in message.get("targets", []) if isinstance(message.get("targets"), list) else []:
            if not isinstance(target, dict):
                continue
            target_id = target.get("target_id")
            if not isinstance(target_id, str) or not target_id:
                continue
            target_ids.add(target_id)
            position = target.get("transform", {}).get("position") if isinstance(target.get("transform"), dict) else None
            if not isinstance(position, list):
                continue
            if target_id not in first_positions:
                first_positions[target_id] = position
            elif position != first_positions[target_id]:
                position_changed = True

    if len(messages) < min_packets:
        errors.append(f"not enough packets: {len(messages)} < {min_packets}")

    sequence_contiguous = False
    if len(sequences) == len(messages) and sequences:
        sequence_contiguous = all(current == previous + 1 for previous, current in zip(sequences, sequences[1:]))
        if not sequence_contiguous:
            errors.append(f"sequence not contiguous: {sequences}")
    elif messages:
        errors.append("sequence missing from one or more packets")

    return {
        "ok": not errors,
        "packets": len(messages),
        "parsed": len(messages),
        "first_sequence": sequences[0] if sequences else None,
        "last_sequence": sequences[-1] if sequences else None,
        "sequence_contiguous": sequence_contiguous,
        "position_changed": position_changed,
        "target_ids": sorted(target_ids),
        "errors": errors,
    }


def status_from_exception(exc: Exception, url: str, timeout_seconds: float) -> dict[str, Any]:
    reason = "exception"
    hint = "Inspect the live publisher and network settings."
    if isinstance(exc, ConnectionRefusedError):
        reason = "connection_refused"
        hint = (
            "publisher is not listening on this URL. Start it first, for example: "
            ".\\run_antman_vst_proxy_targets_live_publisher.ps1 -Port 8766 -Hz 20 -MinConfidence 0.3"
        )
    elif isinstance(exc, TimeoutError) or isinstance(exc, socket.timeout):
        reason = "timeout"
        hint = "publisher accepted no usable WebSocket traffic before timeout; check the publisher console."
    elif isinstance(exc, ConnectionError):
        reason = "connection_error"
        hint = "connection opened but closed or failed before enough proxy_targets packets arrived."

    return {
        "ok": False,
        "packets": 0,
        "parsed": 0,
        "url": url,
        "timeout_seconds": timeout_seconds,
        "reason": reason,
        "hint": hint,
        "errors": [str(exc)],
    }


def monitor_stream(url: str, min_packets: int, timeout_seconds: float, subscribe_stream: str = "proxy_targets") -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme != "ws":
        raise ValueError(f"only ws:// URLs are supported: {url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    messages: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_seconds

    with socket.create_connection((host, port), timeout=timeout_seconds) as conn:
        conn.settimeout(max(0.1, timeout_seconds))
        _perform_client_handshake(conn, host, port, path)
        conn.sendall(_encode_masked_text_frame(json.dumps({"type": "subscribe", "stream": subscribe_stream}, separators=(",", ":"))))

        while len(messages) < min_packets and time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            conn.settimeout(remaining)
            payload = _read_websocket_text(conn)
            if payload is None:
                break
            if payload == "":
                continue
            messages.append(json.loads(payload))

    status = analyze_messages(messages, min_packets=min_packets)
    status["url"] = url
    status["timeout_seconds"] = timeout_seconds
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor a live proxy_targets WebSocket stream without Godot/OpenXR.")
    parser.add_argument("--url", default="ws://127.0.0.1:8766/proxy_targets")
    parser.add_argument("--min-packets", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--subscribe-stream", default="proxy_targets")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        status = monitor_stream(
            args.url,
            min_packets=max(1, args.min_packets),
            timeout_seconds=max(0.1, args.timeout_seconds),
            subscribe_stream=args.subscribe_stream,
        )
    except Exception as exc:
        status = status_from_exception(exc, args.url, args.timeout_seconds)

    text = json.dumps(status, ensure_ascii=False, indent=2)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if status.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
