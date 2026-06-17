"""Module 3 live bridge: C1 tracking_raw WS -> align -> C2 proxy_targets WS.

This is the live wiring of module 3 (``docs/mr_integration.md``). It closes the
whole PC headless chain without a device:

    NV12 -> ncnn -> C1 producer -> C1 WS (/tracking_raw)
        -> [this bridge: C1->C2 alignment] -> proxy_targets WS (/proxy_targets)
        -> Godot card

The bridge is both a WebSocket **client** (it subscribes to an upstream C1
publisher, e.g. ``smartxr.cli.tracking_raw_publisher``) and a WebSocket
**server** (it serves canonical ``proxy_targets`` on ``/proxy_targets``, the
stream the Godot card already consumes). When a card connects, the bridge opens a
fresh upstream C1 subscription and a fresh converter (so the C2 ``sequence``
restarts per card, matching the C1 publisher's per-client producer), then pumps:
read one C1 frame, convert it via the owned calibration, forward the C2 frame.

Empty C1 frames (the valid "no people" state) convert to ``None`` and are simply
not forwarded -- the card idles/holds. The conversion itself is the unchanged,
dual-locked :mod:`smartxr.mr_integration` converter, so the live path and the
file path (``smartxr.cli.convert_tracking_raw``) produce identical C2.
"""

from __future__ import annotations

import argparse
import json
import select
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

from smartxr.mr_integration import (
    TrackingRawToProxyTargetsConverter,
    load_calibration,
)
from smartxr.transport import (
    client_handshake,
    drain_client_frames,
    encode_masked_text_frame,
    encode_websocket_text_frame,
    read_server_text_frame,
    serve_single_client,
)

PROXY_TARGETS_PATH = "/proxy_targets"
DEFAULT_C1_URL = "ws://127.0.0.1:8770/tracking_raw"
DEFAULT_PORT = 8766
# How often, while no upstream C1 frame is pending, we loop back to drain the
# card connection so a disconnected card is noticed promptly.
UPSTREAM_POLL_S = 0.2


def is_proxy_targets_request(first_line: str) -> bool:
    parts = first_line.split()
    if len(parts) < 2:
        return False
    path = parts[1].split("?", 1)[0]
    return path == PROXY_TARGETS_PATH


def _connect_upstream(c1_url: str, timeout_s: float) -> socket.socket:
    parsed = urlparse(c1_url)
    if parsed.scheme != "ws":
        raise ValueError(f"only ws:// C1 URLs are supported: {c1_url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    conn = socket.create_connection((host, port), timeout=timeout_s)
    client_handshake(conn, host, port, path)
    conn.sendall(
        encode_masked_text_frame(
            json.dumps({"type": "subscribe", "stream": "tracking_raw"}, separators=(",", ":"))
        )
    )
    return conn


def _bridge_loop(
    card_conn: socket.socket,
    c1_url: str,
    converter_factory,
    *,
    connect_timeout_s: float,
    log_every: int,
) -> None:
    try:
        upstream = _connect_upstream(c1_url, connect_timeout_s)
    except OSError as exc:
        print(
            f"bridge: cannot reach C1 source {c1_url}: {exc}. "
            "Start it first, e.g. python -m smartxr.cli.tracking_raw_publisher",
            flush=True,
        )
        return

    converter = converter_factory()
    forwarded = 0
    skipped_empty = 0
    try:
        while True:
            # Notice a card disconnect promptly even while the C1 source is idle.
            if not drain_client_frames(card_conn):
                return
            readable, _, _ = select.select([upstream], [], [], UPSTREAM_POLL_S)
            if not readable:
                continue
            text = read_server_text_frame(upstream)
            if text is None:
                print("bridge: C1 source closed the stream", flush=True)
                return
            if text == "":
                continue
            try:
                c1_message = json.loads(text)
            except json.JSONDecodeError as exc:
                print(f"bridge: dropping malformed C1 frame: {exc}", flush=True)
                continue
            c2_message = converter.convert(c1_message)
            if c2_message is None:
                skipped_empty += 1
                continue
            payload = json.dumps(c2_message, separators=(",", ":"), ensure_ascii=False)
            card_conn.sendall(encode_websocket_text_frame(payload))
            if log_every > 0 and forwarded % log_every == 0:
                position = c2_message["targets"][0]["transform"]["position"]
                print(
                    "bridge: forwarded seq=%d targets=%d pos=%.3f %.3f %.3f (skipped_empty=%d)"
                    % (
                        c2_message["sequence"],
                        len(c2_message["targets"]),
                        position[0],
                        position[1],
                        position[2],
                        skipped_empty,
                    ),
                    flush=True,
                )
            forwarded += 1
    finally:
        try:
            upstream.close()
        except OSError:
            pass


def serve(
    host: str,
    port: int,
    c1_url: str,
    *,
    calibration=None,
    card_id: str = "CardAnchor",
    min_confidence: float = 0.0,
    stale_after_ms: float | None = None,
    include_diagnostics: bool = False,
    connect_timeout_s: float = 10.0,
    log_every: int = 20,
) -> None:
    if calibration is None:
        calibration = load_calibration(None)

    def converter_factory() -> TrackingRawToProxyTargetsConverter:
        return TrackingRawToProxyTargetsConverter(
            calibration,
            card_id=card_id,
            stale_after_ms=stale_after_ms,
            min_confidence=min_confidence,
            include_diagnostics=include_diagnostics,
        )

    serve_single_client(
        host,
        port,
        lambda conn: _bridge_loop(
            conn,
            c1_url,
            converter_factory,
            connect_timeout_s=connect_timeout_s,
            log_every=log_every,
        ),
        on_listening=lambda: print(
            f"mr_integration bridge: proxy_targets on ws://{host}:{port}{PROXY_TARGETS_PATH} "
            f"<- C1 {c1_url} (calibration: {calibration.label})",
            flush=True,
        ),
        allow_request=is_proxy_targets_request,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Module 3 live bridge: subscribe to a C1 tracking_raw WS, convert to "
        "proxy_targets, and serve it to the Godot card."
    )
    parser.add_argument("--host", default="127.0.0.1", help="proxy_targets server host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="proxy_targets server port.")
    parser.add_argument("--c1-url", default=DEFAULT_C1_URL, help="upstream C1 tracking_raw WS URL.")
    parser.add_argument(
        "--right-eye-to-head",
        type=Path,
        default=None,
        help="Optional JSON file with a 16-element right_eye_to_head matrix "
        "(binocular calibration). Default: v1 monocular axis flip.",
    )
    parser.add_argument("--card-id", default="CardAnchor")
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--stale-after-ms", type=float, default=None)
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--connect-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--log-every", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    serve(
        args.host,
        args.port,
        args.c1_url,
        calibration=load_calibration(args.right_eye_to_head),
        card_id=args.card_id,
        min_confidence=args.min_confidence,
        stale_after_ms=args.stale_after_ms,
        include_diagnostics=args.diagnostics,
        connect_timeout_s=args.connect_timeout_seconds,
        log_every=args.log_every,
    )


if __name__ == "__main__":
    main()
