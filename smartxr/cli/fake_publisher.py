"""Serve synthetic moving proxy_targets messages for Windows PCMR validation."""

from __future__ import annotations

import argparse
import json
import socket
import time

from smartxr.publisher import build_fake_proxy_targets_message
from smartxr.transport import drain_client_frames, encode_websocket_text_frame, serve_single_client


def is_proxy_targets_request(first_line: str) -> bool:
    parts = first_line.split()
    if len(parts) < 2:
        return False
    path = parts[1].split("?", 1)[0]
    return path == "/proxy_targets"


def _publish_loop(conn: socket.socket, hz: float, target_id: str, card_id: str, mode: str, log_every: int) -> None:
    start = time.monotonic()
    interval_s = 1.0 / max(hz, 0.1)
    sequence = 0
    while True:
        if not drain_client_frames(conn):
            return
        elapsed_s = time.monotonic() - start
        message = build_fake_proxy_targets_message(
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
    serve_single_client(
        host,
        port,
        lambda conn: _publish_loop(conn, hz=hz, target_id=target_id, card_id=card_id, mode=mode, log_every=log_every),
        on_listening=lambda: print(
            f"proxy_targets fake publisher listening on ws://{host}:{port}/proxy_targets", flush=True
        ),
        allow_request=is_proxy_targets_request,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve moving proxy_targets messages for Windows PCMR validation.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--target-id", default="person-7")
    parser.add_argument("--card-id", default="CardAnchor")
    parser.add_argument("--mode", default="moving", choices=["moving", "static"])
    parser.add_argument("--log-every", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    serve(args.host, args.port, args.hz, args.target_id, args.card_id, args.mode, args.log_every)


if __name__ == "__main__":
    main()
