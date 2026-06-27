from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
_ROOT = TOOLS_DIR.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dump_antman_vst_humantrackor_jsonl import (  # noqa: E402
    DEFAULT_ANTMAN_ROOT,
    _install_antman_paths,
    resolve_vst_shm_name,
)
from smartxr.live_stereo_recorder import record_live_stereo_package  # noqa: E402
from smartxr.stereo_depth import SCENE_STEREO_28  # noqa: E402


DEFAULT_VST_AI_SHM_ROOT = Path("E:/xia/Antman/0422/0527/P1/vst_ai_shm")


def _header_timestamp_us(header: dict[str, Any]) -> int | None:
    for key in ("exposure_timestamp", "timestamp_us", "capture_timestamp_us", "ts_us"):
        value = header.get(key)
        if value is not None:
            return int(value)
    return None


class VstAiShmConsumerReader:
    def __init__(
        self,
        *,
        consumer: Any,
        wait_timeout_ms: int,
    ) -> None:
        self.consumer = consumer
        self.wait_timeout_ms = int(wait_timeout_ms)
        self.frames_returned = 0
        self.empty_waits = 0

    def read_latest(self):
        if not self.consumer.wait_for_frame(timeout_ms=self.wait_timeout_ms):
            self.empty_waits += 1
            return True, -1, None
        result = self.consumer.read_latest_frame()
        if result is None:
            self.empty_waits += 1
            return True, -1, None
        header, nv12 = result
        frame_id = int(header["frame_id"])
        self.consumer.acknowledge(frame_id)
        self.frames_returned += 1
        frame = {
            "width": int(header["width"]),
            "height": int(header["height"]),
            "stride": int(header["stride"]),
            "payload": nv12.tobytes(),
        }
        if "exposure_timestamp" in header and header["exposure_timestamp"] is not None:
            frame["exposure_timestamp"] = int(header["exposure_timestamp"])
        timestamp_us = _header_timestamp_us(header)
        if timestamp_us is not None:
            frame["timestamp_us"] = timestamp_us
        return (
            True,
            frame_id,
            frame,
        )

    def get_stats(self) -> dict[str, Any]:
        return {
            "reader": "vst_ai_shm_consumer",
            "frames_returned": self.frames_returned,
            "empty_waits": self.empty_waits,
            "shm_name": getattr(self.consumer, "shm_name", ""),
            "event_name": getattr(self.consumer, "event_name", ""),
        }

    def release(self) -> None:
        self.consumer.close()


def build_stereo_shm_names(base_name: str) -> tuple[str, str]:
    return (
        resolve_vst_shm_name(base_name, "Left"),
        resolve_vst_shm_name(base_name, "Right"),
    )


def _create_stereo_readers(args: argparse.Namespace) -> tuple[Any, Any]:
    if args.vst_reader == "vst_ai_shm":
        return _create_vst_ai_shm_readers(args)
    return _create_legacy_stereo_readers(args)


def _create_vst_ai_shm_readers(args: argparse.Namespace) -> tuple[Any, Any]:
    root = Path(args.vst_ai_shm_root)
    value = str(root.resolve())
    if value not in sys.path:
        sys.path.insert(0, value)
    from vst_ai_shm_consumer import VstAiShmConsumer

    left = VstAiShmConsumer(
        base_name=args.shm_name,
        namespace=args.shm_namespace,
        eye="Left",
    )
    right = VstAiShmConsumer(
        base_name=args.shm_name,
        namespace=args.shm_namespace,
        eye="Right",
    )
    left.open(wait_for_producer_seconds=args.wait_for_producer_seconds)
    right.open(wait_for_producer_seconds=args.wait_for_producer_seconds)
    return (
        VstAiShmConsumerReader(
            consumer=left,
            wait_timeout_ms=args.wait_timeout_ms,
        ),
        VstAiShmConsumerReader(
            consumer=right,
            wait_timeout_ms=args.wait_timeout_ms,
        ),
    )


def _create_legacy_stereo_readers(args: argparse.Namespace) -> tuple[Any, Any]:
    _install_antman_paths(args.antman_root)
    from human_face_visualizer.async_runtime import VstAiShmReader

    left_name, right_name = build_stereo_shm_names(args.shm_name)
    reader_kwargs = {
        "namespace": args.shm_namespace,
        "wait_timeout_ms": args.wait_timeout_ms,
        "wait_for_producer_seconds": args.wait_for_producer_seconds,
    }
    return (
        VstAiShmReader(name=left_name, **reader_kwargs),
        VstAiShmReader(name=right_name, **reader_kwargs),
    )


def startup_error_status(exc: Exception, out_dir: Path) -> tuple[dict[str, Any], int]:
    if isinstance(exc, ModuleNotFoundError):
        reason = "dependency_unavailable"
        exit_code = 3
    else:
        reason = "vst_source_unavailable"
        exit_code = 1
    return (
        {
            "source_alive": False,
            "frames_seen_left": 0,
            "frames_seen_right": 0,
            "pair_count": 0,
            "reason": reason,
            "error": str(exc),
            "output_dir": str(out_dir.resolve()),
        },
        exit_code,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record Antman VST Left/Right SHM into a SmartXR stereo package."
    )
    parser.add_argument("--antman-root", type=Path, default=DEFAULT_ANTMAN_ROOT)
    parser.add_argument("--vst-ai-shm-root", type=Path, default=DEFAULT_VST_AI_SHM_ROOT)
    parser.add_argument(
        "--vst-reader",
        choices=("vst_ai_shm", "legacy"),
        default="vst_ai_shm",
        help="Use the standalone vst_ai_shm_consumer module by default; pass legacy for human_face_visualizer.async_runtime.",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--shm-name", default="Antman.VST.AI.v1")
    parser.add_argument("--shm-namespace", default=None)
    parser.add_argument("--wait-timeout-ms", type=int, default=1000)
    parser.add_argument("--wait-for-producer-seconds", type=float, default=10.0)
    parser.add_argument("--recorded-width", type=int, default=880)
    parser.add_argument("--recorded-height", type=int, default=660)
    parser.add_argument("--max-read-attempts", type=int, default=240)
    parser.add_argument("--max-skew-frames", type=int, default=1)
    parser.add_argument("--sleep-seconds", type=float, default=0.005)
    parser.add_argument("--require-pair", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        left_reader, right_reader = _create_stereo_readers(args)
        calibration = SCENE_STEREO_28.scaled_to(
            args.recorded_width,
            args.recorded_height,
        )
        status = record_live_stereo_package(
            left_reader=left_reader,
            right_reader=right_reader,
            out_dir=args.out_dir,
            calibration=calibration,
            max_read_attempts=args.max_read_attempts,
            max_skew_frames=args.max_skew_frames,
            sleep_seconds=args.sleep_seconds,
        )
    except Exception as exc:
        status, exit_code = startup_error_status(exc, args.out_dir)
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
        return exit_code

    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    if status["validation_errors"]:
        return 4
    if status["frames_seen_left"] <= 0 or status["frames_seen_right"] <= 0:
        return 1
    if args.require_pair and status["pair_count"] <= 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
