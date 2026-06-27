from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
_ROOT = TOOLS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from antman_vst_stereo_proxy_targets_live_publisher import (  # noqa: E402
    DEFAULT_MAX_PAIR_CAPTURE_DELTA_MS,
    DEFAULT_SOURCE_HZ,
    BroadcastHub,
    _broadcast_loop,
    _client_loop,
    _format_address,
    _handshake,
    is_proxy_targets_request,
)
from dump_antman_vst_humantrackor_jsonl import DEFAULT_ANTMAN_ROOT, _install_antman_paths  # noqa: E402
from smartxr.nv12_reader import read_packet_file  # noqa: E402
from smartxr.stereo_package import StereoPair, load_stereo_package  # noqa: E402


ReplayTiming = str


class StereoPackageReplayReader:
    def __init__(
        self,
        *,
        eye: str,
        refs: list[Any],
        replay_timing: ReplayTiming,
        source_hz: float,
        monotonic_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if replay_timing not in ("capture", "fixed", "fast"):
            raise ValueError(f"unsupported replay_timing: {replay_timing!r}")
        self.eye = eye
        self.refs = list(refs)
        self.replay_timing = replay_timing
        self.source_hz = float(source_hz)
        self.monotonic_fn = monotonic_fn
        self.sleep_fn = sleep_fn
        self.started_at_s: float | None = None
        self.first_timestamp_us = self.refs[0].timestamp_us if self.refs else 0
        self.next_index = 0
        self.frames_returned = 0
        self.empty_reads = 0
        self.total_sleep_s = 0.0
        self.last_frame_id: int | None = None
        self.last_timestamp_us: int | None = None

    def read_latest(self) -> tuple[bool, int, dict[str, Any] | None]:
        if self.next_index >= len(self.refs):
            self.empty_reads += 1
            return True, -1, None
        if self.started_at_s is None:
            self.started_at_s = self.monotonic_fn()

        ref = self.refs[self.next_index]
        self._wait_until_due(ref)
        self.next_index += 1

        packet = read_packet_file(ref.path, index=ref.index)
        payload = packet.y_plane + packet.uv_plane
        timestamp_us = int(ref.timestamp_us)
        frame = {
            "width": int(packet.width),
            "height": int(packet.height),
            "stride": int(packet.stride),
            "payload": payload,
            "timestamp_us": timestamp_us,
            "exposure_us": timestamp_us,
            "available_timestamp_keys": ["timestamp_us", "exposure_us"],
            "header_timestamp_debug": {
                "timestamp_us": timestamp_us,
                "exposure_us": timestamp_us,
                "frame_id": int(ref.frame_id),
                "packet_index": int(ref.index),
            },
            "source": "stereo_package_replay",
            "eye": self.eye,
            "packet_path": str(ref.path),
        }
        self.frames_returned += 1
        self.last_frame_id = int(ref.frame_id)
        self.last_timestamp_us = timestamp_us
        return True, int(ref.frame_id), frame

    def _wait_until_due(self, ref: Any) -> None:
        delay_s = self._scheduled_elapsed_s(ref)
        if delay_s <= 0.0 or self.replay_timing == "fast":
            return
        assert self.started_at_s is not None
        due_at_s = self.started_at_s + delay_s
        remaining_s = due_at_s - self.monotonic_fn()
        if remaining_s <= 0.0:
            return
        self.total_sleep_s += remaining_s
        self.sleep_fn(remaining_s)

    def _scheduled_elapsed_s(self, ref: Any) -> float:
        if self.replay_timing == "fast":
            return 0.0
        if self.replay_timing == "fixed":
            return float(self.next_index) / max(self.source_hz, 0.1)
        return max(0.0, (int(ref.timestamp_us) - int(self.first_timestamp_us)) / 1_000_000.0)

    def get_stats(self) -> dict[str, Any]:
        return {
            "reader": "stereo_package_replay",
            "eye": self.eye,
            "replay_timing": self.replay_timing,
            "source_hz": self.source_hz,
            "frames_total": len(self.refs),
            "frames_returned": self.frames_returned,
            "empty_reads": self.empty_reads,
            "remaining_frames": max(0, len(self.refs) - self.next_index),
            "last_frame_id": self.last_frame_id,
            "last_timestamp_us": self.last_timestamp_us,
            "total_sleep_s": self.total_sleep_s,
        }

    def release(self) -> None:
        return None


def create_stereo_package_replay_readers(
    package_dir: Path,
    *,
    replay_timing: ReplayTiming = "capture",
    source_hz: float = DEFAULT_SOURCE_HZ,
    monotonic_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[StereoPackageReplayReader, StereoPackageReplayReader]:
    summary = load_stereo_package(Path(package_dir))
    pairs: list[StereoPair] = list(summary.pairs)
    left_refs = [pair.left for pair in pairs]
    right_refs = [pair.right for pair in pairs]
    return (
        StereoPackageReplayReader(
            eye="left",
            refs=left_refs,
            replay_timing=replay_timing,
            source_hz=source_hz,
            monotonic_fn=monotonic_fn,
            sleep_fn=sleep_fn,
        ),
        StereoPackageReplayReader(
            eye="right",
            refs=right_refs,
            replay_timing=replay_timing,
            source_hz=source_hz,
            monotonic_fn=monotonic_fn,
            sleep_fn=sleep_fn,
        ),
    )


def create_trackers(args: argparse.Namespace) -> tuple[Any, Any]:
    _install_antman_paths(args.antman_root)
    from human_trackor.api import HumanTrackor

    tracker_kwargs = {
        "model": args.model,
        "backend": args.backend,
        "imgsz": args.imgsz,
        "conf": args.min_confidence,
        "device": args.device,
    }
    return HumanTrackor(**tracker_kwargs), HumanTrackor(**tracker_kwargs)


def serve(args: argparse.Namespace) -> int:
    try:
        left_reader, right_reader = create_stereo_package_replay_readers(
            args.package_dir,
            replay_timing=args.replay_timing,
            source_hz=args.source_hz,
        )
        left_tracker, right_tracker = create_trackers(args)
    except Exception as exc:
        status = {
            "source_alive": False,
            "reason": "stereo_package_replay_unavailable",
            "error": str(exc),
            "package_dir": str(Path(args.package_dir).resolve()),
        }
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")), flush=True)
        return 1

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((args.host, args.port))
            server.listen(8)
            print(
                f"package proxy_targets live replay publisher listening on ws://{args.host}:{args.port}/proxy_targets",
                flush=True,
            )
            print(f"source: stereo package replay {Path(args.package_dir).resolve()}", flush=True)
            print(f"replay_timing={args.replay_timing} source_hz={args.source_hz}", flush=True)
            hub = BroadcastHub()
            threading.Thread(
                target=_broadcast_loop,
                kwargs={
                    "hub": hub,
                    "left_reader": left_reader,
                    "right_reader": right_reader,
                    "left_tracker": left_tracker,
                    "right_tracker": right_tracker,
                    "hz": args.hz,
                    "card_id": args.card_id,
                    "min_confidence": args.min_confidence,
                    "recorded_width": args.recorded_width,
                    "recorded_height": args.recorded_height,
                    "log_every": args.log_every,
                    "max_empty_reads": args.max_empty_reads,
                    "max_vertical_error_px": args.max_vertical_error_px,
                    "depth_trace": args.depth_trace,
                    "max_pair_capture_delta_ms": args.max_pair_capture_delta_ms,
                    "target_source_hz": args.source_hz,
                },
                daemon=True,
            ).start()
            while True:
                conn, address = server.accept()
                ok, first_line = _handshake(conn, allow_request=is_proxy_targets_request)
                if not ok:
                    print(f"rejected {address}: {first_line}", flush=True)
                    conn.close()
                    continue
                label = "godot" if hub.client_count() == 0 else "monitor"
                client_id = hub.add_client(conn, address, label=label)
                print(
                    f"client connected: id={client_id} label={label} address={_format_address(address)} request={first_line}",
                    flush=True,
                )
                threading.Thread(target=_client_loop, args=(conn, address, hub), daemon=True).start()
    finally:
        left_reader.release()
        right_reader.release()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay a stereo package as live proxy_targets.")
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--replay-timing", choices=("capture", "fixed", "fast"), default="capture")
    parser.add_argument("--source-hz", type=float, default=DEFAULT_SOURCE_HZ)
    parser.add_argument("--antman-root", type=Path, default=DEFAULT_ANTMAN_ROOT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--card-id", default="CardAnchor")
    parser.add_argument("--log-every", type=int, default=20)
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--max-empty-reads", type=int, default=120)
    parser.add_argument("--max-vertical-error-px", type=float, default=None)
    parser.add_argument("--max-pair-capture-delta-ms", type=float, default=DEFAULT_MAX_PAIR_CAPTURE_DELTA_MS)
    parser.add_argument("--depth-trace", type=Path, default=None)
    parser.add_argument("--recorded-width", type=int, default=880)
    parser.add_argument("--recorded-height", type=int, default=660)
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--backend", default="ultralytics")
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--device", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return serve(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
