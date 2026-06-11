"""Adapt VST/external source JSON into proxy_targets messages and serve them."""

from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path

from smartxr.publisher import load_source_messages, replay_message_at
from smartxr.transport import drain_client_frames, encode_websocket_text_frame, serve_single_client


def _publish_loop(conn: socket.socket, input_path: Path, hz: float, card_id: str, log_every: int) -> None:
    interval_s = 1.0 / max(hz, 0.1)
    source_messages = load_source_messages(input_path, card_id=card_id)
    sequence = 0
    while True:
        if not drain_client_frames(conn):
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
    def on_listening() -> None:
        print(f"proxy_targets publisher listening on ws://{host}:{port}/proxy_targets", flush=True)
        print(f"source input: {input_path}", flush=True)

    serve_single_client(
        host,
        port,
        lambda conn: _publish_loop(conn, input_path=input_path, hz=hz, card_id=card_id, log_every=log_every),
        on_listening=on_listening,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adapt VST/external source JSON into proxy_targets messages.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--print-once", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--card-id", default="CardAnchor")
    parser.add_argument("--log-every", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.print_once:
        print(json.dumps(load_source_messages(args.input, card_id=args.card_id)[0], separators=(",", ":")))
        return 0
    serve(args.host, args.port, args.input, args.hz, args.card_id, args.log_every)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
