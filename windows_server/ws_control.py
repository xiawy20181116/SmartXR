"""Keyboard-to-WebSocket control server for the Android Godot card demo."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smartxr.transport import (  # noqa: E402
    WEBSOCKET_GUID as WS_GUID,
    encode_server_text_frame,
    make_websocket_accept_key,
)

try:
    import msvcrt
except ImportError:  # pragma: no cover - Windows-only keyboard path.
    msvcrt = None

try:
    import websockets
except ImportError:  # pragma: no cover - reported clearly by main().
    websockets = None


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8766

KEY_COMMANDS = {
    "a": "yaw_left",
    "left": "yaw_left",
    "d": "yaw_right",
    "right": "yaw_right",
    "w": "pitch_up",
    "up": "pitch_up",
    "s": "pitch_down",
    "down": "pitch_down",
    "+": "speed_up",
    "=": "speed_up",
    "add": "speed_up",
    "-": "speed_down",
    "subtract": "speed_down",
    "[": "depth_out",
    "]": "depth_in",
    "space": "pause",
    " ": "pause",
    "r": "reset",
    "b": "toggle_bbox_mode",
    "j": "bbox_left",
    "l": "bbox_right",
    "i": "bbox_up",
    "k": "bbox_down",
    "u": "bbox_depth_out",
    "o": "bbox_depth_in",
    "m": "reset_world_anchor",
}

EXTENDED_KEYS = {
    b"H": "pitch_up",
    b"P": "pitch_down",
    b"K": "yaw_left",
    b"M": "yaw_right",
}

QUIT_KEYS = {"q", "esc", "escape", "\x1b"}


def build_control_message(command: str) -> str:
    return json.dumps({"type": "control", "command": command}, separators=(",", ":"))


def build_bbox_message(
    center_x: int,
    center_y: int,
    width: int,
    height: int,
    image_width: int,
    image_height: int,
    depth_m: float,
) -> str:
    return json.dumps(
        {
            "type": "bbox",
            "bbox": {"cx": center_x, "cy": center_y, "w": width, "h": height},
            "image": {"w": image_width, "h": image_height},
            "depth_m": depth_m,
        },
        separators=(",", ":"),
    )


def command_for_key(key: str) -> str | None:
    normalized = key.lower().strip()
    if key == " ":
        normalized = " "
    return KEY_COMMANDS.get(normalized)


def is_quit_key(key: str) -> bool:
    normalized = key.lower().strip()
    return normalized in QUIT_KEYS


class ControlHub:
    def __init__(self) -> None:
        self.clients: set[object] = set()

    async def handler(self, websocket: object, _path: str | None = None) -> None:
        self.clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.clients.discard(websocket)

    async def broadcast(self, command: str) -> None:
        if not self.clients:
            return
        payload = build_control_message(command)
        stale = []
        for client in tuple(self.clients):
            try:
                await client.send(payload)
            except Exception:
                stale.append(client)
        for client in stale:
            self.clients.discard(client)


class StdlibWebSocket:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    async def send(self, payload: str) -> None:
        self.writer.write(encode_server_text_frame(payload))
        await self.writer.drain()

    async def wait_closed(self) -> None:
        try:
            while not self.reader.at_eof():
                data = await self.reader.read(1024)
                if not data:
                    break
        finally:
            self.writer.close()
            await self.writer.wait_closed()


async def _read_http_headers(reader: asyncio.StreamReader) -> dict[str, str]:
    raw = await reader.readuntil(b"\r\n\r\n")
    text = raw.decode("iso-8859-1")
    headers: dict[str, str] = {}
    for line in text.split("\r\n")[1:]:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.lower().strip()] = value.strip()
    return headers


async def _stdlib_client_handler(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    hub: ControlHub,
) -> None:
    try:
        headers = await _read_http_headers(reader)
        client_key = headers.get("sec-websocket-key")
        if not client_key:
            writer.close()
            await writer.wait_closed()
            return
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {make_websocket_accept_key(client_key)}\r\n"
            "\r\n"
        )
        writer.write(response.encode("ascii"))
        await writer.drain()
        await hub.handler(StdlibWebSocket(reader, writer))
    except Exception:
        writer.close()
        await writer.wait_closed()


async def _serve_stdlib(host: str, port: int, hub: ControlHub, stop: asyncio.Event) -> None:
    server = await asyncio.start_server(
        lambda reader, writer: _stdlib_client_handler(reader, writer, hub),
        host,
        port,
    )
    async with server:
        keyboard_task = asyncio.create_task(read_keyboard_loop(hub, stop))
        serve_task = asyncio.create_task(server.serve_forever())
        stop_task = asyncio.create_task(stop.wait())
        done, pending = await asyncio.wait(
            {keyboard_task, serve_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            task.result()


def _read_windows_key() -> str | None:
    if msvcrt is None or not msvcrt.kbhit():
        return None

    raw = msvcrt.getch()
    if raw in (b"\x00", b"\xe0"):
        return EXTENDED_KEYS.get(msvcrt.getch())
    if raw == b"\r":
        return None
    if raw == b" ":
        return " "
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


async def read_keyboard_loop(
    hub: ControlHub,
    stop: asyncio.Event,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> None:
    while not stop.is_set():
        key = _read_windows_key()
        if key is None:
            await sleep(0.03)
            continue
        if is_quit_key(key):
            stop.set()
            continue
        command = command_for_key(key)
        if command is not None:
            await hub.broadcast(command)
            print(f"sent: {command}")


async def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    hub = ControlHub()
    stop = asyncio.Event()
    print(f"SmartXR ws_control listening on ws://{host}:{port}/control")
    print("Keys: W/A/S/D or arrows adjust yaw/pitch, [/ ] depth, +/- angular speed, Space pause, R reset, M reset world latch, Q quit.")
    print("Mock bbox: B toggle mode, J/L move cx, I/K move cy, U/O depth.")
    if websockets is None:
        await _serve_stdlib(host, port, hub, stop)
        return

    async with websockets.serve(hub.handler, host, port):
        await read_keyboard_loop(hub, stop)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        asyncio.run(serve(args.host, args.port))
    except KeyboardInterrupt:
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
