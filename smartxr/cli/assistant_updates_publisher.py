"""Serve synthetic assistant_updates messages for Godot MR validation."""

from __future__ import annotations

import argparse
import json
import socket
import time

from SmartMRAssistant.assistant.card_payload import build_assistant_card_payload
from smartxr.transport import drain_client_frames, encode_websocket_text_frame, serve_single_client


def is_assistant_updates_request(first_line: str) -> bool:
    parts = first_line.split()
    if len(parts) < 2:
        return False
    path = parts[1].split("?", 1)[0]
    return path == "/assistant_updates"


def build_demo_payload(sequence: int = 0) -> dict[str, object]:
    return build_assistant_card_payload(
        card_id="CardAnchor",
        target_id="person-ada",
        assistant_state="responding",
        response_text="Ada is working on XR-42.",
        tool_summary={
            "status_line": "Ada Lovelace | XR-42 | In Progress",
            "sequence": str(sequence),
        },
        person={
            "id": "person-ada",
            "display_name": "Ada Lovelace",
        },
        issue={
            "key": "XR-42",
            "summary": "Prepare MR assistant demo",
            "status": "In Progress",
        },
    )


def _publish_loop(conn: socket.socket, hz: float, log_every: int) -> None:
    interval_s = 1.0 / max(hz, 0.1)
    sequence = 0
    while True:
        if not drain_client_frames(conn):
            return
        message = build_demo_payload(sequence)
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        conn.sendall(encode_websocket_text_frame(payload))
        if log_every > 0 and sequence % log_every == 0:
            print(
                "sent assistant_updates seq=%d card=%s target=%s"
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
            f"assistant_updates fake publisher listening on ws://{host}:{port}/assistant_updates",
            flush=True,
        ),
        allow_request=is_assistant_updates_request,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve synthetic assistant_updates messages for Godot MR validation.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8774)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--log-every", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    serve(args.host, args.port, args.hz, args.log_every)


if __name__ == "__main__":
    main()
