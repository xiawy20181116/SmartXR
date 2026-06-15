"""Serve SmartMR M-star demo assistant-card updates over WebSocket."""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from SmartMRAssistant.assistant.demo import build_mstar_demo_result_sync  # noqa: E402
from smartxr.transport import drain_client_frames, encode_websocket_text_frame, serve_single_client  # noqa: E402


def is_assistant_updates_request(first_line: str) -> bool:
    parts = first_line.split()
    if len(parts) < 2:
        return False
    path = parts[1].split("?", 1)[0]
    return path == "/assistant_updates"


def _publish_loop(conn: socket.socket, hz: float, log_every: int) -> None:
    interval_s = 1.0 / max(hz, 0.1)
    sequence = 0
    while True:
        if not drain_client_frames(conn):
            return
        message = build_mstar_demo_result_sync()["assistant_card"]
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        conn.sendall(encode_websocket_text_frame(payload))
        if log_every > 0 and sequence % log_every == 0:
            print(
                "sent M-star assistant_updates seq=%d card=%s target=%s"
                % (sequence, message["card_id"], message["target_id"]),
                flush=True,
            )
        sequence += 1
        time.sleep(interval_s)


def serve(host: str, port: int, hz: float, log_every: int) -> None:
    serve_single_client(
        host,
        port,
        lambda conn: _publish_loop(conn, hz=hz, log_every=log_every),
        on_listening=lambda: print(
            f"assistant_updates M-star demo publisher listening on ws://{host}:{port}/assistant_updates",
            flush=True,
        ),
        allow_request=is_assistant_updates_request,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve SmartMR M-star assistant updates for Godot MR validation.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8775)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--log-every", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    serve(args.host, args.port, args.hz, args.log_every)


if __name__ == "__main__":
    main()
