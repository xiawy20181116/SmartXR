"""Minimal WebSocket server primitives shared by every SmartXR publisher.

Single home for the hand-rolled RFC 6455 pieces that previously lived in
three copies (``ws_control.py``, ``fake_proxy_targets_publisher.py``,
``vst_proxy_targets_publisher.py``): handshake, frame encode/decode, and the
single-client accept loop.
"""

from __future__ import annotations

import base64
import hashlib
import select
import socket
import struct
from typing import Callable, Dict, Tuple


WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def make_websocket_accept_key(client_key: str) -> str:
    digest = hashlib.sha1((client_key + WEBSOCKET_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


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


# Alias kept for the asyncio control server, which historically used this name.
encode_server_text_frame = encode_websocket_text_frame


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


def drain_client_frames(conn: socket.socket) -> bool:
    """Drain pending client frames. Returns False once the client closed."""
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


def read_http_request(conn: socket.socket) -> str:
    chunks = []
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\r\n\r\n" in chunk:
            break
    return b"".join(chunks).decode("utf-8", errors="replace")


def parse_headers(request: str) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for line in request.splitlines()[1:]:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return headers


def handshake(conn: socket.socket, allow_request: Callable[[str], bool] | None = None) -> Tuple[bool, str]:
    """Perform the server side of the WebSocket upgrade handshake."""
    try:
        request = read_http_request(conn)
    except (ConnectionResetError, OSError):
        return False, ""
    first_line = request.splitlines()[0] if request else ""
    headers = parse_headers(request)
    key = headers.get("sec-websocket-key", "")
    if not first_line.startswith("GET ") or not key:
        return False, first_line
    if allow_request is not None and not allow_request(first_line):
        return False, first_line
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {make_websocket_accept_key(key)}\r\n"
        "\r\n"
    )
    conn.sendall(response.encode("ascii"))
    return True, first_line


def serve_single_client(
    host: str,
    port: int,
    handle_client: Callable[[socket.socket], None],
    on_listening: Callable[[], None] | None = None,
    allow_request: Callable[[str], bool] | None = None,
) -> None:
    """Accept loop shared by every publisher: one client at a time, forever.

    ``handle_client`` receives an upgraded connection and should return when
    the client disconnects; connection-reset style errors are absorbed here.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(1)
        if on_listening is not None:
            on_listening()
        while True:
            conn, address = server.accept()
            with conn:
                ok, first_line = handshake(conn, allow_request=allow_request)
                if not ok:
                    print(f"rejected {address}: {first_line}", flush=True)
                    continue
                print(f"client connected from {address}: {first_line}", flush=True)
                try:
                    handle_client(conn)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    print(f"client disconnected: {address}", flush=True)
