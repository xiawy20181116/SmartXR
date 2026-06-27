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


def _message_timestamp_ms(message: dict[str, Any]) -> float | None:
    value = message.get("timestamp_ms")
    if value is None:
        targets = message.get("targets")
        if isinstance(targets, list) and targets and isinstance(targets[0], dict):
            value = targets[0].get("timestamp_ms")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _realtime_summary(
    messages: list[dict[str, Any]],
    *,
    sequences: list[int],
    expected_source_hz: float,
) -> dict[str, Any]:
    timestamps = [
        timestamp
        for timestamp in (_message_timestamp_ms(message) for message in messages)
        if timestamp is not None
    ]
    intervals = [current - previous for previous, current in zip(timestamps, timestamps[1:]) if current >= previous]
    expected_interval_ms = 1000.0 / max(float(expected_source_hz), 0.1)
    observed_packet_hz = None
    if intervals:
        mean_interval_ms = sum(intervals) / len(intervals)
        if mean_interval_ms > 0.0:
            observed_packet_hz = 1000.0 / mean_interval_ms
    packet_drop_count = 0
    sequence_gap_count = 0
    for previous, current in zip(sequences, sequences[1:]):
        gap = current - previous - 1
        if gap > 0:
            sequence_gap_count += 1
            packet_drop_count += gap
    return {
        "expected_source_hz": float(expected_source_hz),
        "expected_interval_ms": expected_interval_ms,
        "timestamp_count": len(timestamps),
        "interval_count": len(intervals),
        "min_interval_ms": min(intervals) if intervals else None,
        "max_interval_ms": max(intervals) if intervals else None,
        "mean_interval_ms": (sum(intervals) / len(intervals)) if intervals else None,
        "observed_packet_hz": observed_packet_hz,
        "late_interval_count": sum(1 for interval in intervals if interval > expected_interval_ms * 1.5),
        "sequence_gap_count": sequence_gap_count,
        "packet_drop_count": packet_drop_count,
    }


def analyze_messages(messages: list[dict[str, Any]], min_packets: int, expected_source_hz: float = 45.0) -> dict[str, Any]:
    errors: list[str] = []
    sequences: list[int] = []
    target_ids: set[str] = set()
    depth_confidences: dict[str, int] = {}
    depth_sources: dict[str, int] = {}
    first_positions: dict[str, list[float]] = {}
    position_changed = False
    target_count = 0
    missing_depth_confidence_count = 0
    missing_depth_source_count = 0

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
            target_count += 1
            target_ids.add(target_id)
            depth_confidence = target.get("depth_confidence")
            if isinstance(depth_confidence, str) and depth_confidence:
                depth_confidences[depth_confidence] = depth_confidences.get(depth_confidence, 0) + 1
            else:
                missing_depth_confidence_count += 1
            depth_source = target.get("depth_source")
            if isinstance(depth_source, str) and depth_source:
                depth_sources[depth_source] = depth_sources.get(depth_source, 0) + 1
            else:
                missing_depth_source_count += 1
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

    realtime = _realtime_summary(messages, sequences=sequences, expected_source_hz=expected_source_hz)

    return {
        "ok": not errors,
        "packets": len(messages),
        "parsed": len(messages),
        "first_sequence": sequences[0] if sequences else None,
        "last_sequence": sequences[-1] if sequences else None,
        "sequence_contiguous": sequence_contiguous,
        "position_changed": position_changed,
        "target_ids": sorted(target_ids),
        "target_count": target_count,
        "depth_confidences": dict(sorted(depth_confidences.items())),
        "depth_sources": dict(sorted(depth_sources.items())),
        "missing_depth_confidence_count": missing_depth_confidence_count,
        "missing_depth_source_count": missing_depth_source_count,
        "realtime": realtime,
        "errors": errors,
    }


def _sequence_bounds(messages: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    sequences = [
        message.get("sequence")
        for message in messages
        if isinstance(message.get("sequence"), int) and not isinstance(message.get("sequence"), bool)
    ]
    return (sequences[0], sequences[-1]) if sequences else (None, None)


def status_from_exception(
    exc: Exception,
    url: str,
    timeout_seconds: float,
    *,
    ws_connected: bool = False,
    ws_subscribed: bool = False,
    packets_before_close: int = 0,
    first_sequence: int | None = None,
    last_sequence: int | None = None,
    client_label: str = "monitor",
) -> dict[str, Any]:
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
    elif isinstance(exc, ConnectionResetError):
        reason = "connection_reset"
        hint = "connection opened but the peer reset it before enough proxy_targets packets arrived."
    elif isinstance(exc, ConnectionError):
        reason = "connection_error"
        hint = "connection opened but closed or failed before enough proxy_targets packets arrived."

    return {
        "ok": False,
        "packets": packets_before_close,
        "parsed": packets_before_close,
        "url": url,
        "timeout_seconds": timeout_seconds,
        "client_label": client_label,
        "ws_connected": ws_connected,
        "ws_subscribed": ws_subscribed,
        "first_packet_seen": packets_before_close > 0,
        "first_sequence": first_sequence,
        "last_sequence": last_sequence,
        "packets_before_close": packets_before_close,
        "close_reason": reason,
        "reason": reason,
        "hint": hint,
        "errors": [str(exc)],
    }


def monitor_stream(
    url: str,
    min_packets: int,
    timeout_seconds: float,
    subscribe_stream: str = "proxy_targets",
    expected_source_hz: float = 45.0,
) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme != "ws":
        raise ValueError(f"only ws:// URLs are supported: {url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    messages: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_seconds
    ws_connected = False
    ws_subscribed = False

    try:
        with socket.create_connection((host, port), timeout=timeout_seconds) as conn:
            conn.settimeout(max(0.1, timeout_seconds))
            _perform_client_handshake(conn, host, port, path)
            ws_connected = True
            subscribe_payload = json.dumps(
                {"type": "subscribe", "stream": subscribe_stream, "client_label": "monitor"},
                separators=(",", ":"),
            )
            conn.sendall(_encode_masked_text_frame(subscribe_payload))
            ws_subscribed = True

            while len(messages) < min_packets and time.monotonic() < deadline:
                remaining = max(0.1, deadline - time.monotonic())
                conn.settimeout(remaining)
                payload = _read_websocket_text(conn)
                if payload is None:
                    break
                if payload == "":
                    continue
                messages.append(json.loads(payload))
    except Exception as exc:
        first_sequence, last_sequence = _sequence_bounds(messages)
        return status_from_exception(
            exc,
            url,
            timeout_seconds,
            ws_connected=ws_connected,
            ws_subscribed=ws_subscribed,
            packets_before_close=len(messages),
            first_sequence=first_sequence,
            last_sequence=last_sequence,
        )

    status = analyze_messages(messages, min_packets=min_packets, expected_source_hz=expected_source_hz)
    status["url"] = url
    status["timeout_seconds"] = timeout_seconds
    status["client_label"] = "monitor"
    status["ws_connected"] = ws_connected
    status["ws_subscribed"] = ws_subscribed
    status["first_packet_seen"] = bool(messages)
    status["packets_before_close"] = len(messages)
    status["close_reason"] = "completed" if status.get("ok") else "insufficient_packets"
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor a live proxy_targets WebSocket stream without Godot/OpenXR.")
    parser.add_argument("--url", default="ws://127.0.0.1:8766/proxy_targets")
    parser.add_argument("--min-packets", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--subscribe-stream", default="proxy_targets")
    parser.add_argument("--expected-source-hz", type=float, default=45.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        status = monitor_stream(
            args.url,
            min_packets=max(1, args.min_packets),
            timeout_seconds=max(0.1, args.timeout_seconds),
            subscribe_stream=args.subscribe_stream,
            expected_source_hz=max(0.1, args.expected_source_hz),
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
