from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
ROOT = TOOLS_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dump_antman_vst_humantrackor_jsonl import (  # noqa: E402
    DEFAULT_ANTMAN_ROOT,
    create_live_vst_reader,
    resolve_vst_shm_name,
    startup_error_status,
)
from smartxr.nv12_reader import (  # noqa: E402
    HEADER_STRUCT,
    HEADER_SIZE,
    NV12_MAGIC,
    PACKETS_DIR,
    nv12_payload_size,
)


class Nv12FrameContractError(ValueError):
    """Raised when a live frame cannot be proven to be native NV12 bytes."""


def _value(obj: Any, names: tuple[str, ...], default: Any = None) -> Any:
    if isinstance(obj, dict):
        for name in names:
            if name in obj:
                return obj[name]
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _bytes_from_value(value: Any) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    if hasattr(value, "tobytes"):
        return value.tobytes()
    return None


def extract_nv12_frame(frame: Any) -> tuple[int, int, int, bytes]:
    """Return width, height, stride, raw NV12 payload from a live Antman frame.

    The recorder only writes native NV12 payloads. RGB/BGR-like arrays are
    rejected instead of silently producing a replay package with the wrong
    format or stride.
    """
    payload = _bytes_from_value(_value(frame, ("nv12", "nv12_bytes", "payload", "data", "buffer")))
    if payload is None:
        payload = _bytes_from_value(frame)

    width = _value(frame, ("width", "image_width", "w"))
    height = _value(frame, ("height", "image_height", "h"))
    stride = _value(frame, ("stride", "pitch", "row_stride", "y_stride"))

    shape = getattr(frame, "shape", None)
    strides = getattr(frame, "strides", None)
    if isinstance(shape, tuple):
        if len(shape) >= 3 and int(shape[2]) in (3, 4):
            raise Nv12FrameContractError(
                f"SHM frame shape {shape!r} looks decoded, not native NV12"
            )
        if width is None and len(shape) >= 2:
            width = int(shape[1])
        if height is None and len(shape) >= 2:
            rows = int(shape[0])
            height = rows * 2 // 3 if rows % 3 == 0 else rows
        if stride is None and isinstance(strides, tuple) and strides:
            stride = int(strides[0])
        elif stride is None and width is not None:
            stride = int(width)

    if width is None or height is None or stride is None or payload is None:
        raise Nv12FrameContractError(
            "SHM frame does not expose native NV12 payload plus width/height/stride"
        )

    width = int(width)
    height = int(height)
    stride = int(stride)
    expected = nv12_payload_size(height, stride)
    if len(payload) != expected:
        raise Nv12FrameContractError(
            f"NV12 payload size {len(payload)} != stride*height*3/2 {expected} "
            f"(width={width} height={height} stride={stride})"
        )
    return width, height, stride, payload


def frame_timestamp_us(frame: Any, fallback_frame_id: int) -> int:
    value = _value(frame, ("timestamp_us", "capture_timestamp_us", "ts_us", "timestampUsec"))
    if value is not None:
        return int(value)
    value_ms = _value(frame, ("timestamp_ms", "capture_timestamp_ms", "ts_ms"))
    if value_ms is not None:
        return int(float(value_ms) * 1000)
    return int(fallback_frame_id)


class CaptureSessionWriter:
    def __init__(
        self,
        *,
        session_dir: Path,
        shm_name: str,
        shm_eye: str,
        resolved_shm_name: str,
        antman_root: Path,
        source_version: str,
        record_start_wall_clock: str,
    ) -> None:
        self.session_dir = Path(session_dir)
        self.packets_dir = self.session_dir / PACKETS_DIR
        self.shm_name = shm_name
        self.shm_eye = shm_eye
        self.resolved_shm_name = resolved_shm_name
        self.antman_root = Path(antman_root)
        self.source_version = source_version
        self.record_start_wall_clock = record_start_wall_clock
        self.files: list[str] = []
        self.timeline: list[dict[str, Any]] = []
        self.width: int | None = None
        self.height: int | None = None
        self.stride: int | None = None
        self.packets_dir.mkdir(parents=True, exist_ok=True)

    def write_frame(
        self,
        *,
        frame: Any,
        frame_id: int,
        timestamp_us: int,
        at_ms: float,
    ) -> Path:
        width, height, stride, payload = extract_nv12_frame(frame)
        if self.width is None:
            self.width, self.height, self.stride = width, height, stride
        elif (width, height, stride) != (self.width, self.height, self.stride):
            raise Nv12FrameContractError(
                "capture geometry changed from "
                f"{self.width}x{self.height} stride {self.stride} to "
                f"{width}x{height} stride {stride}"
            )

        index = len(self.files) + 1
        rel = f"{PACKETS_DIR}/packet_{index:06d}.bin"
        path = self.session_dir / rel
        header = HEADER_STRUCT.pack(
            NV12_MAGIC,
            HEADER_SIZE,
            width,
            height,
            stride,
            len(payload),
            int(timestamp_us),
        )
        path.write_bytes(header + payload)
        self.files.append(rel)
        self.timeline.append(
            {
                "index": index,
                "frame_id": int(frame_id),
                "at_ms": round(float(at_ms), 3),
                "timestamp_us": int(timestamp_us),
                "file": rel,
            }
        )
        return path

    def write_manifest(self, *, status: dict[str, Any]) -> None:
        metadata = {
            "format": "smartxr_nv12_capture_session",
            "version": 1,
            "width": self.width,
            "height": self.height,
            "stride": self.stride,
            "files": self.files,
            "shm_name": self.shm_name,
            "shm_eye": self.shm_eye,
            "resolved_shm_name": self.resolved_shm_name,
            "antman_root": str(self.antman_root),
            "source_version": self.source_version,
            "record_start_wall_clock": self.record_start_wall_clock,
            "status": status,
        }
        timeline = {"frames": self.timeline}
        (self.session_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (self.session_dir / "timeline.json").write_text(
            json.dumps(timeline, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def record_vst_capture(
    *,
    reader: Any,
    session_dir: Path,
    duration_seconds: float,
    max_frames: int | None,
    shm_name: str,
    shm_eye: str,
    resolved_shm_name: str,
    antman_root: Path,
    source_version: str,
    sleep_seconds: float = 0.005,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    start = clock()
    writer = CaptureSessionWriter(
        session_dir=session_dir,
        shm_name=shm_name,
        shm_eye=shm_eye,
        resolved_shm_name=resolved_shm_name,
        antman_root=antman_root,
        source_version=source_version,
        record_start_wall_clock=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    frames_written = 0
    dropped = 0
    last_frame_id: int | None = None
    first_timestamp_us: int | None = None
    last_timestamp_us: int | None = None
    reason = "duration_elapsed"

    try:
        while clock() - start < duration_seconds:
            ok, frame_id, frame = reader.read_latest()
            if not ok:
                reason = "source_read_failed"
                break
            if frame is None or int(frame_id) < 0:
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
                continue
            frame_id = int(frame_id)
            if frame_id == last_frame_id:
                dropped += 1
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
                continue

            timestamp_us = frame_timestamp_us(frame, frame_id)
            if first_timestamp_us is None:
                first_timestamp_us = timestamp_us
            at_ms = (timestamp_us - first_timestamp_us) / 1000.0
            writer.write_frame(
                frame=frame,
                frame_id=frame_id,
                timestamp_us=timestamp_us,
                at_ms=at_ms,
            )
            frames_written += 1
            last_frame_id = frame_id
            last_timestamp_us = timestamp_us
            if max_frames is not None and frames_written >= max(1, int(max_frames)):
                reason = "max_frames"
                break
    finally:
        if hasattr(reader, "release"):
            reader.release()

    elapsed_s = 0.0
    if first_timestamp_us is not None and last_timestamp_us is not None:
        elapsed_s = max(0.0, (last_timestamp_us - first_timestamp_us) / 1_000_000.0)
    fps = frames_written / elapsed_s if elapsed_s > 0 else 0.0
    status = {
        "source_alive": frames_written > 0,
        "frames_written": frames_written,
        "dropped": dropped,
        "reason": reason if frames_written > 0 else "no_frames_seen",
        "last_frame_id": -1 if last_frame_id is None else last_frame_id,
        "observed_fps": round(fps, 3),
        "output_dir": str(Path(session_dir).resolve()),
    }
    writer.write_manifest(status=status)
    return status


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record Antman VST SHM into a SmartXR NV12 capture session.")
    parser.add_argument("--antman-root", type=Path, default=DEFAULT_ANTMAN_ROOT)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, default=30.0)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--shm-name", default="Antman.VST.AI.v1")
    parser.add_argument("--shm-eye", default="Right", help='VST eye suffix: "Right", "Left", or "" for legacy unsuffixed SHM')
    parser.add_argument("--shm-namespace", default=None)
    parser.add_argument("--wait-timeout-ms", type=int, default=1000)
    parser.add_argument("--wait-for-producer-seconds", type=float, default=10.0)
    parser.add_argument("--source-version", default="Antman.VST.AI.v1")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        reader = create_live_vst_reader(args)
    except Exception as exc:
        status, exit_code = startup_error_status(exc, args.out_dir / "metadata.json")
        status["output_dir"] = str(args.out_dir.resolve())
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
        return exit_code

    try:
        status = record_vst_capture(
            reader=reader,
            session_dir=args.out_dir,
            duration_seconds=args.duration_seconds,
            max_frames=args.max_frames,
            shm_name=args.shm_name,
            shm_eye=args.shm_eye,
            resolved_shm_name=resolve_vst_shm_name(args.shm_name, args.shm_eye),
            antman_root=args.antman_root,
            source_version=args.source_version,
        )
    except Nv12FrameContractError as exc:
        status = {
            "source_alive": False,
            "frames_written": 0,
            "dropped": 0,
            "reason": "unsupported_frame_contract",
            "error": str(exc),
            "output_dir": str(args.out_dir.resolve()),
        }
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
        return 4
    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    return 0 if status["source_alive"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
