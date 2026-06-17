"""Live C1 (tracking_raw) WebSocket publisher (YAN-108 PC chain).

Streams canonical C1 messages over a WebSocket so module 3 (and any consumer)
can develop against a **live** C1 source instead of a static fixture. It mirrors
the proxy_targets fake publisher: one client at a time on `/tracking_raw`, a
per-frame message at `--hz`, reusing `smartxr.transport`.

The frame source is pluggable (`make_source`, a zero-arg factory returning a
fresh iterator of `(timestamp_ms, detection_records)` per connection):

- The default source replays a recorded **detections JSONL** (real yolov8n
  detections dumped from VST capture) through the real
  `TrackingRawProducer` -- fully dependency-free, so it runs in CI and on any
  box without ncnn/numpy.
- The full PC chain (NV12 session -> PC-offload yolov8n -> producer) lives in
  `tools/run_tracking_raw_live_publisher.py`; it builds an NV12+ncnn source and
  calls :func:`serve` here, so the WebSocket/serve path is shared, not forked.

A fresh producer (and tracker) is created per client connection, so each
subscriber sees a clean track lifecycle from the start of the replay.
"""

from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path
from typing import Callable, Iterable, Iterator

from smartxr.detection_backend import detections_from_records
from smartxr.tracker import HumanTracker
from smartxr.tracking_raw_producer import ConstantDepthSource, TrackingRawProducer
from smartxr.transport import (
    drain_client_frames,
    encode_websocket_text_frame,
    serve_single_client,
)

WS_PATH = "/tracking_raw"
DEFAULT_DEPTH_M = 1.8
# Same tracker recipe the committed golden fixture is built with.
TRACKER_KWARGS = dict(iou_threshold=0.3, n_confirm=3, m_to_lost=1, k_to_delete=10)

# A source frame is (timestamp_ms or None, list-of-detection-records).
SourceFrame = tuple
Source = Iterator
MakeSource = Callable[[], Iterable]


def is_tracking_raw_request(first_line: str) -> bool:
    parts = first_line.split()
    if len(parts) < 2:
        return False
    path = parts[1].split("?", 1)[0]
    return path == WS_PATH


def iter_detection_jsonl(path: Path, loop: bool = True) -> Iterator[tuple]:
    """Yield `(timestamp_ms, records)` from a detections JSONL, optionally looped."""
    path = Path(path)
    while True:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                frame = json.loads(line)
                yield frame.get("timestamp_ms"), frame.get("detections", [])
        if not loop:
            return


def make_detection_jsonl_source(path: Path, loop: bool = True) -> MakeSource:
    return lambda: iter_detection_jsonl(path, loop=loop)


def make_producer(depth_m: float = DEFAULT_DEPTH_M) -> TrackingRawProducer:
    return TrackingRawProducer(
        tracker=HumanTracker(**TRACKER_KWARGS),
        depth_source=ConstantDepthSource(depth_m),
        source="pc_offload",
        coordinate_space="vst_right_camera",
    )


def _publish_loop(
    conn: socket.socket,
    make_source: MakeSource,
    hz: float,
    depth_m: float,
    log_every: int,
) -> None:
    producer = make_producer(depth_m)
    interval_s = 1.0 / max(hz, 0.1)
    sequence = 0
    start = time.monotonic()
    for frame_timestamp_ms, records in make_source():
        if not drain_client_frames(conn):
            return
        timestamp_ms = (
            float(frame_timestamp_ms)
            if frame_timestamp_ms is not None
            else (time.monotonic() - start) * 1000.0
        )
        detections = detections_from_records(records)
        message = producer.produce_frame(detections, sequence, timestamp_ms)
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        conn.sendall(encode_websocket_text_frame(payload))
        if log_every > 0 and sequence % log_every == 0:
            print(
                "sent seq=%d detections=%d states=%s"
                % (
                    sequence,
                    len(message["detections"]),
                    ",".join(sorted({d["state"] for d in message["detections"]})) or "-",
                ),
                flush=True,
            )
        sequence += 1
        time.sleep(interval_s)


def serve(
    host: str,
    port: int,
    make_source: MakeSource,
    hz: float = 20.0,
    depth_m: float = DEFAULT_DEPTH_M,
    log_every: int = 20,
) -> None:
    serve_single_client(
        host,
        port,
        lambda conn: _publish_loop(conn, make_source, hz=hz, depth_m=depth_m, log_every=log_every),
        on_listening=lambda: print(
            f"tracking_raw (C1) publisher listening on ws://{host}:{port}{WS_PATH}", flush=True
        ),
        allow_request=is_tracking_raw_request,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    default_source = root / "godot-android" / "fixtures" / "tracking_raw_replay_detections.jsonl"
    parser = argparse.ArgumentParser(description="Serve a live C1 (tracking_raw) WebSocket stream from recorded detections.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--depth-m", type=float, default=DEFAULT_DEPTH_M)
    parser.add_argument("--source", type=Path, default=default_source, help="detections JSONL to replay")
    parser.add_argument("--no-loop", action="store_true", help="stop after one pass instead of looping")
    parser.add_argument("--log-every", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    make_source = make_detection_jsonl_source(args.source, loop=not args.no_loop)
    serve(args.host, args.port, make_source, hz=args.hz, depth_m=args.depth_m, log_every=args.log_every)


if __name__ == "__main__":
    main()
