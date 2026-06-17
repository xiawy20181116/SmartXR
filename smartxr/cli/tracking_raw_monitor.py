"""Consumer-side harness for the live C1 (tracking_raw) WebSocket stream.

Connects to a `tracking_raw` publisher, reads N messages, and validates the
stream end to end without Godot/OpenXR/a device: every message must pass the
frozen C1 schema and be accepted by the contract-only `TrackingRawConsumer`,
sequence numbers must be contiguous, and it summarizes the track ids and the
lifecycle states observed. This is the "consumer side" of the PC chain -- the
thing module 3 (or CI) runs to prove a live C1 source is healthy.

Dependency-free (stdlib + `smartxr` schema/fakes). Mirrors
`tools/monitor_proxy_targets_live_stream.py`.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from smartxr.tracking_raw_fakes import TrackingRawConsumer
from smartxr.tracking_raw_schema import validate_message

DEFAULT_URL = "ws://127.0.0.1:8770/tracking_raw"


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
    payload = _read_exact(conn, length) if length else b""
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


def analyze_c1_messages(messages: list[dict[str, Any]], min_packets: int) -> dict[str, Any]:
    """Validate a list of C1 messages and summarize the stream."""
    consumer = TrackingRawConsumer()
    errors: list[str] = []
    sequences: list[int] = []
    states: set[str] = set()
    frames_with_detections = 0
    empty_frames = 0

    for index, message in enumerate(messages):
        schema_errors = validate_message(message)
        errors.extend(f"packet[{index}]: {error}" for error in schema_errors)
        consumer.consume(message)

        sequence = message.get("sequence")
        if isinstance(sequence, int) and not isinstance(sequence, bool):
            sequences.append(sequence)

        detections = message.get("detections")
        if isinstance(detections, list):
            if detections:
                frames_with_detections += 1
            else:
                empty_frames += 1
            for detection in detections:
                if isinstance(detection, dict) and isinstance(detection.get("state"), str):
                    states.add(detection["state"])

    if len(messages) < min_packets:
        errors.append(f"not enough packets: {len(messages)} < {min_packets}")
    if consumer.frames_rejected:
        errors.append(f"consumer rejected {consumer.frames_rejected} frame(s)")

    sequence_contiguous = False
    if len(sequences) == len(messages) and sequences:
        sequence_contiguous = all(b == a + 1 for a, b in zip(sequences, sequences[1:]))
        if not sequence_contiguous:
            errors.append(f"sequence not contiguous: {sequences}")
    elif messages:
        errors.append("sequence missing from one or more packets")

    return {
        "ok": not errors,
        "packets": len(messages),
        "accepted": consumer.frames_accepted,
        "rejected": consumer.frames_rejected,
        "first_sequence": sequences[0] if sequences else None,
        "last_sequence": sequences[-1] if sequences else None,
        "sequence_contiguous": sequence_contiguous,
        "frames_with_detections": frames_with_detections,
        "empty_frames": empty_frames,
        "track_ids": sorted(consumer.seen_ids),
        "lifecycle_states": sorted(states),
        "errors": errors,
    }


def status_from_exception(exc: Exception, url: str, timeout_seconds: float) -> dict[str, Any]:
    reason = "exception"
    hint = "Inspect the C1 publisher and network settings."
    if isinstance(exc, ConnectionRefusedError):
        reason = "connection_refused"
        hint = (
            "publisher is not listening on this URL. Start it first, e.g.: "
            "python -m smartxr.cli.tracking_raw_publisher --port 8770"
        )
    elif isinstance(exc, (TimeoutError, socket.timeout)):
        reason = "timeout"
        hint = "publisher accepted no usable WebSocket traffic before timeout."
    elif isinstance(exc, ConnectionError):
        reason = "connection_error"
        hint = "connection opened but closed before enough C1 packets arrived."
    return {
        "ok": False,
        "packets": 0,
        "accepted": 0,
        "url": url,
        "timeout_seconds": timeout_seconds,
        "reason": reason,
        "hint": hint,
        "errors": [str(exc)],
    }


def monitor_stream(url: str, min_packets: int, timeout_seconds: float) -> dict[str, Any]:
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
        conn.sendall(
            _encode_masked_text_frame(json.dumps({"type": "subscribe", "stream": "tracking_raw"}, separators=(",", ":")))
        )
        while len(messages) < min_packets and time.monotonic() < deadline:
            conn.settimeout(max(0.1, deadline - time.monotonic()))
            payload = _read_websocket_text(conn)
            if payload is None:
                break
            if payload == "":
                continue
            messages.append(json.loads(payload))

    status = analyze_c1_messages(messages, min_packets=min_packets)
    status["url"] = url
    status["timeout_seconds"] = timeout_seconds
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor a live C1 (tracking_raw) WebSocket stream without a device.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--min-packets", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        status = monitor_stream(
            args.url,
            min_packets=max(1, args.min_packets),
            timeout_seconds=max(0.1, args.timeout_seconds),
        )
    except Exception as exc:  # noqa: BLE001 - reported as structured status
        status = status_from_exception(exc, args.url, args.timeout_seconds)

    text = json.dumps(status, ensure_ascii=False, indent=2)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if status.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
