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


VALID_DECODED_COLOR_ORDERS = {"BGR", "RGB"}


class Nv12FrameContractError(ValueError):
    """Raised when a live frame cannot be proven to be native NV12 bytes."""


class ExtractedNv12Frame:
    def __init__(
        self,
        *,
        width: int,
        height: int,
        stride: int,
        payload: bytes,
        source_frame_format: str,
        conversion: str,
    ) -> None:
        self.width = int(width)
        self.height = int(height)
        self.stride = int(stride)
        self.payload = payload
        self.source_frame_format = source_frame_format
        self.conversion = conversion


class FrameTimestamp:
    def __init__(self, *, timestamp_us: int, source: str) -> None:
        self.timestamp_us = int(timestamp_us)
        self.source = source


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


def _clip_u8(value: int) -> int:
    return max(0, min(255, int(value)))


def _rgb_to_yuv_bt601_limited(r: int, g: int, b: int) -> tuple[int, int, int]:
    y = ((66 * r + 129 * g + 25 * b + 128) >> 8) + 16
    u = ((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128
    v = ((112 * r - 94 * g - 18 * b + 128) >> 8) + 128
    return _clip_u8(y), _clip_u8(u), _clip_u8(v)


def _decoded_dimensions(frame: Any) -> tuple[int, int] | None:
    shape = getattr(frame, "shape", None)
    if isinstance(shape, tuple) and len(shape) >= 3 and int(shape[2]) == 3:
        return int(shape[1]), int(shape[0])
    return None


def _pixel_bgr(frame: Any, y: int, x: int, color_order: str) -> tuple[int, int, int]:
    c0 = int(frame[y, x, 0])
    c1 = int(frame[y, x, 1])
    c2 = int(frame[y, x, 2])
    if color_order == "RGB":
        return c2, c1, c0
    return c0, c1, c2


def _numpy_decoded_to_nv12(frame: Any, color_order: str) -> bytes | None:
    try:
        import numpy as np
    except Exception:
        return None

    try:
        arr = np.asarray(frame)
    except Exception:
        return None
    if arr.ndim != 3 or arr.shape[2] != 3:
        return None
    if arr.dtype != np.uint8:
        arr = arr.astype(np.uint8, copy=False)

    try:
        import cv2

        code = cv2.COLOR_RGB2YUV_I420 if color_order == "RGB" else cv2.COLOR_BGR2YUV_I420
        i420 = cv2.cvtColor(arr, code).reshape(-1)
        height, width = int(arr.shape[0]), int(arr.shape[1])
        y_size = width * height
        uv_size = y_size // 4
        y_plane = i420[:y_size].tobytes()
        u = i420[y_size : y_size + uv_size]
        v = i420[y_size + uv_size : y_size + uv_size + uv_size]
        uv = np.empty(uv_size * 2, dtype=np.uint8)
        uv[0::2] = u
        uv[1::2] = v
        return y_plane + uv.tobytes()
    except Exception:
        pass

    if color_order == "RGB":
        r = arr[:, :, 0].astype(np.int32)
        g = arr[:, :, 1].astype(np.int32)
        b = arr[:, :, 2].astype(np.int32)
    else:
        b = arr[:, :, 0].astype(np.int32)
        g = arr[:, :, 1].astype(np.int32)
        r = arr[:, :, 2].astype(np.int32)
    y_plane = np.clip(((66 * r + 129 * g + 25 * b + 128) >> 8) + 16, 0, 255).astype(np.uint8)
    u_full = np.clip(((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128, 0, 255)
    v_full = np.clip(((112 * r - 94 * g - 18 * b + 128) >> 8) + 128, 0, 255)
    u = np.rint(u_full.reshape(arr.shape[0] // 2, 2, arr.shape[1] // 2, 2).mean(axis=(1, 3))).astype(np.uint8)
    v = np.rint(v_full.reshape(arr.shape[0] // 2, 2, arr.shape[1] // 2, 2).mean(axis=(1, 3))).astype(np.uint8)
    uv = np.empty((arr.shape[0] // 2, arr.shape[1]), dtype=np.uint8)
    uv[:, 0::2] = u
    uv[:, 1::2] = v
    return y_plane.tobytes() + uv.tobytes()


def _decoded_to_nv12_payload(frame: Any, width: int, height: int, color_order: str) -> bytes:
    if color_order not in VALID_DECODED_COLOR_ORDERS:
        raise Nv12FrameContractError(
            f"unsupported decoded color order {color_order!r}; expected BGR or RGB"
        )
    if width % 2 != 0 or height % 2 != 0:
        raise Nv12FrameContractError(
            f"decoded frame dimensions must be even for NV12: width={width} height={height}"
        )

    payload = _numpy_decoded_to_nv12(frame, color_order)
    if payload is not None:
        return payload

    y_plane = bytearray(width * height)
    uv_plane = bytearray(width * height // 2)
    for row in range(height):
        for col in range(width):
            b, g, r = _pixel_bgr(frame, row, col, color_order)
            y_value, _u, _v = _rgb_to_yuv_bt601_limited(r, g, b)
            y_plane[row * width + col] = y_value
    for row in range(0, height, 2):
        uv_row = row // 2
        for col in range(0, width, 2):
            u_sum = 0
            v_sum = 0
            for yy in (row, row + 1):
                for xx in (col, col + 1):
                    b, g, r = _pixel_bgr(frame, yy, xx, color_order)
                    _y, u_value, v_value = _rgb_to_yuv_bt601_limited(r, g, b)
                    u_sum += u_value
                    v_sum += v_value
            offset = uv_row * width + col
            uv_plane[offset] = _clip_u8(round(u_sum / 4))
            uv_plane[offset + 1] = _clip_u8(round(v_sum / 4))
    return bytes(y_plane) + bytes(uv_plane)


def extract_nv12_frame(frame: Any, *, decoded_color_order: str = "BGR") -> ExtractedNv12Frame:
    """Return width, height, stride, raw NV12 payload from a live Antman frame.

    Native NV12 payloads are persisted unchanged. Decoded 3-channel frames are
    converted to tight-stride NV12 and flagged in metadata.
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
            if int(shape[2]) != 3:
                raise Nv12FrameContractError(
                    f"SHM frame shape {shape!r} is decoded but not 3-channel BGR/RGB"
                )
            decoded = _decoded_dimensions(frame)
            if decoded is None:
                raise Nv12FrameContractError(
                    f"SHM frame shape {shape!r} is decoded but dimensions are unavailable"
                )
            width, height = decoded
            payload = _decoded_to_nv12_payload(frame, width, height, decoded_color_order)
            source_format = f"decoded_{decoded_color_order.lower()}24"
            return ExtractedNv12Frame(
                width=width,
                height=height,
                stride=width,
                payload=payload,
                source_frame_format=source_format,
                conversion=f"{source_format}_to_nv12_bt601_limited",
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
    return ExtractedNv12Frame(
        width=width,
        height=height,
        stride=stride,
        payload=payload,
        source_frame_format="native_nv12",
        conversion="none",
    )


def frame_timestamp_us(
    frame: Any,
    *,
    capture_monotonic_s: float,
    start_monotonic_s: float,
) -> FrameTimestamp:
    value = _value(frame, ("timestamp_us", "capture_timestamp_us", "ts_us", "timestampUsec"))
    if value is not None:
        return FrameTimestamp(timestamp_us=int(value), source="frame_timestamp_us")
    value_ms = _value(frame, ("timestamp_ms", "capture_timestamp_ms", "ts_ms"))
    if value_ms is not None:
        return FrameTimestamp(timestamp_us=int(float(value_ms) * 1000), source="frame_timestamp_ms")
    fallback_us = int(max(0.0, capture_monotonic_s - start_monotonic_s) * 1_000_000)
    return FrameTimestamp(timestamp_us=fallback_us, source="recorder_monotonic_fallback")


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
        decoded_color_order: str = "BGR",
    ) -> None:
        self.session_dir = Path(session_dir)
        self.packets_dir = self.session_dir / PACKETS_DIR
        self.shm_name = shm_name
        self.shm_eye = shm_eye
        self.resolved_shm_name = resolved_shm_name
        self.antman_root = Path(antman_root)
        self.source_version = source_version
        self.record_start_wall_clock = record_start_wall_clock
        self.decoded_color_order = decoded_color_order.upper()
        self.files: list[str] = []
        self.timeline: list[dict[str, Any]] = []
        self.width: int | None = None
        self.height: int | None = None
        self.stride: int | None = None
        self.source_frame_format: str | None = None
        self.conversion: str | None = None
        self.packets_dir.mkdir(parents=True, exist_ok=True)

    def write_frame(
        self,
        *,
        frame: Any,
        frame_id: int,
        timestamp_us: int,
        at_ms: float,
    ) -> Path:
        extracted = extract_nv12_frame(frame, decoded_color_order=self.decoded_color_order)
        width = extracted.width
        height = extracted.height
        stride = extracted.stride
        payload = extracted.payload
        if self.width is None:
            self.width, self.height, self.stride = width, height, stride
            self.source_frame_format = extracted.source_frame_format
            self.conversion = extracted.conversion
        elif (width, height, stride) != (self.width, self.height, self.stride):
            raise Nv12FrameContractError(
                "capture geometry changed from "
                f"{self.width}x{self.height} stride {self.stride} to "
                f"{width}x{height} stride {stride}"
            )
        elif (extracted.source_frame_format, extracted.conversion) != (
            self.source_frame_format,
            self.conversion,
        ):
            raise Nv12FrameContractError("capture frame format/conversion changed during session")

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
            "source_frame_format": self.source_frame_format,
            "conversion": self.conversion,
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
    decoded_color_order: str = "BGR",
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
        decoded_color_order=decoded_color_order,
    )
    frames_written = 0
    dropped = 0
    last_frame_id: int | None = None
    first_timestamp_us: int | None = None
    last_timestamp_us: int | None = None
    timestamp_source: str | None = None
    reason = "duration_elapsed"

    try:
        while True:
            now = clock()
            if now - start >= duration_seconds:
                break
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

            timestamp = frame_timestamp_us(
                frame,
                capture_monotonic_s=now,
                start_monotonic_s=start,
            )
            timestamp_us = timestamp.timestamp_us
            if timestamp_source is None:
                timestamp_source = timestamp.source
            elif timestamp_source != timestamp.source:
                timestamp_source = "mixed"
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
    fps = (frames_written - 1) / elapsed_s if elapsed_s > 0 and frames_written > 1 else 0.0
    status = {
        "source_alive": frames_written > 0,
        "frames_written": frames_written,
        "dropped": dropped,
        "reason": reason if frames_written > 0 else "no_frames_seen",
        "last_frame_id": -1 if last_frame_id is None else last_frame_id,
        "observed_fps": round(fps, 3),
        "timestamp_source": timestamp_source,
        "source_frame_format": writer.source_frame_format,
        "conversion": writer.conversion,
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
    parser.add_argument(
        "--decoded-color-order",
        choices=sorted(VALID_DECODED_COLOR_ORDERS),
        default="BGR",
        help="Color channel order used when SHM exposes decoded HxWx3 frames instead of native NV12.",
    )
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
            decoded_color_order=args.decoded_color_order,
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
