"""Live dual-eye VST recorder core for YAN-119.

This module is the dependency-free boundary between a device-specific
``read_latest()`` source and the offline stereo package contract. The Antman
runtime creates the real readers in ``tools/``; this module only records frames
that have already been exposed as NV12 payloads.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping

from .nv12_reader import (
    HEADER_SIZE,
    HEADER_STRUCT,
    METADATA_FILE,
    NV12_MAGIC,
    PACKETS_DIR,
    nv12_payload_size,
)
from .stereo_depth import StereoCalibration, build_stereo_session_metadata
from .stereo_package import (
    LEFT_EYE_DIR,
    RIGHT_EYE_DIR,
    EyePacketRef,
    pair_eye_packets,
    validate_stereo_package,
)


class LiveStereoRecorderError(ValueError):
    """Raised when a live frame cannot be written as an NV12 stereo package."""


@dataclass(frozen=True)
class CapturedNv12Frame:
    """One live NV12 frame ready to be written into a mono session."""

    frame_id: int
    width: int
    height: int
    stride: int
    timestamp_us: int
    payload: bytes
    read_system_unix_time_us: int | None = None

    def __post_init__(self) -> None:
        if self.frame_id < 0:
            raise LiveStereoRecorderError(f"frame_id must be non-negative, got {self.frame_id}")
        if self.width <= 0 or self.height <= 0:
            raise LiveStereoRecorderError(
                f"width/height must be positive, got {self.width}x{self.height}"
            )
        if self.stride < self.width:
            raise LiveStereoRecorderError(
                f"stride {self.stride} must be >= width {self.width}"
            )
        if self.timestamp_us < 0:
            raise LiveStereoRecorderError(
                f"timestamp_us must be non-negative, got {self.timestamp_us}"
            )
        if self.read_system_unix_time_us is not None:
            _coerce_non_negative_int(
                self.read_system_unix_time_us,
                "read_system_unix_time_us",
            )
        expected = nv12_payload_size(self.height, self.stride)
        if len(self.payload) != expected:
            raise LiveStereoRecorderError(
                f"payload size {len(self.payload)} != stride*height*3/2 {expected}"
            )


def coerce_captured_nv12_frame(
    frame: Any,
    *,
    frame_id: int,
    fallback_timestamp_us: int | None = None,
    read_system_unix_time_us: int | None = None,
) -> CapturedNv12Frame:
    """Convert a reader-returned frame object into :class:`CapturedNv12Frame`."""
    frame_id = _coerce_non_negative_int(frame_id, "frame_id")
    if read_system_unix_time_us is not None:
        read_system_unix_time_us = _coerce_non_negative_int(
            read_system_unix_time_us,
            "read_system_unix_time_us",
        )
    if isinstance(frame, CapturedNv12Frame):
        if frame.frame_id != frame_id:
            raise LiveStereoRecorderError(
                f"reader frame_id {frame_id} != frame.frame_id {frame.frame_id}"
            )
        if read_system_unix_time_us is not None:
            return replace(frame, read_system_unix_time_us=read_system_unix_time_us)
        return frame
    if isinstance(frame, Mapping):
        timestamp_us = frame.get("timestamp_us", fallback_timestamp_us)
        if timestamp_us is None and "timestamp_ms" in frame:
            timestamp_us = int(float(frame["timestamp_ms"]) * 1000.0)
        if timestamp_us is None:
            timestamp_us = int(time.time() * 1_000_000)
        payload = frame.get("payload", frame.get("nv12_payload"))
        if isinstance(payload, bytearray):
            payload = bytes(payload)
        if not isinstance(payload, bytes):
            raise LiveStereoRecorderError("mapping frame must include bytes payload")
        return CapturedNv12Frame(
            frame_id=frame_id,
            width=_coerce_positive_int(frame.get("width"), "width"),
            height=_coerce_positive_int(frame.get("height"), "height"),
            stride=_coerce_positive_int(frame.get("stride"), "stride"),
            timestamp_us=_coerce_non_negative_int(timestamp_us, "timestamp_us"),
            payload=payload,
            read_system_unix_time_us=read_system_unix_time_us,
        )
    array_frame = _coerce_nv12_like_array_frame(
        frame,
        frame_id=frame_id,
        fallback_timestamp_us=fallback_timestamp_us,
        read_system_unix_time_us=read_system_unix_time_us,
    )
    if array_frame is not None:
        return array_frame
    raise LiveStereoRecorderError(
        "frame must be CapturedNv12Frame, a mapping with width/height/stride/payload, "
        "or a 2D NV12-like object with shape/tobytes()"
    )


def write_mono_nv12_session(session_dir: Path, frames: list[CapturedNv12Frame]) -> None:
    """Write one mono NV12 session using the existing reader's on-disk contract."""
    session_dir = Path(session_dir)
    packets_dir = session_dir / PACKETS_DIR
    packets_dir.mkdir(parents=True, exist_ok=True)

    files: list[str] = []
    frame_ids: list[int] = []
    timestamps_us: list[int] = []
    read_system_unix_time_us: list[int] | None = []
    for position, frame in enumerate(frames, start=1):
        name = f"packet_{position:06d}.bin"
        path = packets_dir / name
        header = HEADER_STRUCT.pack(
            NV12_MAGIC,
            HEADER_SIZE,
            frame.width,
            frame.height,
            frame.stride,
            len(frame.payload),
            frame.timestamp_us,
        )
        path.write_bytes(header + frame.payload)
        files.append(f"{PACKETS_DIR}/{name}")
        frame_ids.append(frame.frame_id)
        timestamps_us.append(frame.timestamp_us)
        if frame.read_system_unix_time_us is None:
            read_system_unix_time_us = None
        elif read_system_unix_time_us is not None:
            read_system_unix_time_us.append(frame.read_system_unix_time_us)

    metadata: dict[str, Any] = {
        "files": files,
        "frame_ids": frame_ids,
        "timestamps_us": timestamps_us,
    }
    if read_system_unix_time_us is not None:
        metadata["read_system_unix_time_us"] = read_system_unix_time_us
    if frames:
        first = frames[0]
        metadata.update(
            {
                "width": first.width,
                "height": first.height,
                "stride": first.stride,
            }
        )
    (session_dir / METADATA_FILE).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def record_live_stereo_package(
    *,
    left_reader: Any,
    right_reader: Any,
    out_dir: Path,
    calibration: StereoCalibration,
    max_read_attempts: int,
    max_skew_frames: int,
    sleep_seconds: float = 0.005,
    duration_seconds: float | None = None,
    progress_every_frames: int = 0,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Read live L/R frames and write a validated stereo package."""
    out_dir = Path(out_dir)
    max_read_attempts = _coerce_non_negative_int(max_read_attempts, "max_read_attempts")
    if max_read_attempts == 0 and duration_seconds is None:
        raise LiveStereoRecorderError("max_read_attempts must be positive without duration_seconds")
    max_skew_frames = _coerce_non_negative_int(max_skew_frames, "max_skew_frames")
    duration_seconds = _coerce_optional_positive_float(duration_seconds, "duration_seconds")
    progress_every_frames = _coerce_non_negative_int(
        progress_every_frames,
        "progress_every_frames",
    )
    left_frames: list[CapturedNv12Frame] = []
    right_frames: list[CapturedNv12Frame] = []
    seen_left: set[int] = set()
    seen_right: set[int] = set()
    read_failures = 0
    attempts = 0
    next_progress_frames = progress_every_frames if progress_every_frames > 0 else None
    started_at = time.monotonic()

    try:
        while True:
            elapsed_seconds = time.monotonic() - started_at
            if duration_seconds is not None and attempts > 0 and elapsed_seconds >= duration_seconds:
                break
            if max_read_attempts > 0 and attempts >= max_read_attempts:
                break
            attempts += 1
            read_failures += _read_one_eye(
                left_reader,
                left_frames,
                seen_left,
            )
            read_failures += _read_one_eye(
                right_reader,
                right_frames,
                seen_right,
            )
            if next_progress_frames is not None:
                stereo_frames = min(len(left_frames), len(right_frames))
                if stereo_frames >= next_progress_frames:
                    _emit_progress(
                        progress_callback,
                        attempts=attempts,
                        elapsed_seconds=time.monotonic() - started_at,
                        frames_seen_left=len(left_frames),
                        frames_seen_right=len(right_frames),
                        read_failures=read_failures,
                    )
                    while next_progress_frames <= stereo_frames:
                        next_progress_frames += progress_every_frames
            if sleep_seconds > 0.0:
                time.sleep(sleep_seconds)
    finally:
        _release_reader(left_reader)
        _release_reader(right_reader)

    summary = _summarize_frames(
        left_frames,
        right_frames,
        max_skew_frames=max_skew_frames,
    )
    write_mono_nv12_session(out_dir / LEFT_EYE_DIR, left_frames)
    write_mono_nv12_session(out_dir / RIGHT_EYE_DIR, right_frames)
    metadata = build_stereo_session_metadata(
        calibration,
        pair_count=summary.pair_count,
        dropped_unpaired_left=summary.dropped_unpaired_left,
        dropped_unpaired_right=summary.dropped_unpaired_right,
        max_skew_frames=max_skew_frames,
    )
    (out_dir / "stereo.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    validation_errors = validate_stereo_package(out_dir)
    return {
        "output_dir": str(out_dir),
        "frames_seen_left": len(left_frames),
        "frames_seen_right": len(right_frames),
        "read_failures": read_failures,
        "attempts": attempts,
        "duration_seconds": duration_seconds,
        "elapsed_seconds": time.monotonic() - started_at,
        "pair_count": summary.pair_count,
        "dropped_unpaired_left": summary.dropped_unpaired_left,
        "dropped_unpaired_right": summary.dropped_unpaired_right,
        "max_skew_frames": summary.max_skew_frames,
        "validation_errors": validation_errors,
    }


def _emit_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    *,
    attempts: int,
    elapsed_seconds: float,
    frames_seen_left: int,
    frames_seen_right: int,
    read_failures: int,
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        {
            "attempts": attempts,
            "elapsed_seconds": elapsed_seconds,
            "frames_seen_left": frames_seen_left,
            "frames_seen_right": frames_seen_right,
            "stereo_frames": min(frames_seen_left, frames_seen_right),
            "read_failures": read_failures,
        }
    )


def _read_one_eye(
    reader: Any,
    frames: list[CapturedNv12Frame],
    seen_frame_ids: set[int],
) -> int:
    ok, frame_id, frame = reader.read_latest()
    if not ok:
        return 1
    if frame is None:
        return 0
    frame_id = _coerce_non_negative_int(frame_id, "reader frame_id")
    if frame_id in seen_frame_ids:
        return 0
    read_system_unix_time_us = time.time_ns() // 1000
    frames.append(
        coerce_captured_nv12_frame(
            frame,
            frame_id=frame_id,
            fallback_timestamp_us=int(time.time() * 1_000_000),
            read_system_unix_time_us=read_system_unix_time_us,
        )
    )
    seen_frame_ids.add(frame_id)
    return 0


def _coerce_nv12_like_array_frame(
    frame: Any,
    *,
    frame_id: int,
    fallback_timestamp_us: int | None,
    read_system_unix_time_us: int | None,
) -> CapturedNv12Frame | None:
    shape = getattr(frame, "shape", None)
    if not (isinstance(shape, tuple) and len(shape) == 2 and hasattr(frame, "tobytes")):
        return None
    rows, stride = shape
    rows = _coerce_positive_int(rows, "frame.shape[0]")
    stride = _coerce_positive_int(stride, "frame.shape[1]")
    if (rows * 2) % 3 != 0:
        raise LiveStereoRecorderError(
            f"2D NV12 frame rows must be height*3/2, got rows={rows}"
        )
    height = rows * 2 // 3
    timestamp_us = fallback_timestamp_us
    if timestamp_us is None:
        timestamp_us = int(time.time() * 1_000_000)
    payload = frame.tobytes()
    if isinstance(payload, bytearray):
        payload = bytes(payload)
    if not isinstance(payload, bytes):
        raise LiveStereoRecorderError("frame.tobytes() must return bytes")
    return CapturedNv12Frame(
        frame_id=frame_id,
        width=stride,
        height=height,
        stride=stride,
        timestamp_us=_coerce_non_negative_int(timestamp_us, "timestamp_us"),
        payload=payload,
        read_system_unix_time_us=read_system_unix_time_us,
    )


def _summarize_frames(
    left_frames: list[CapturedNv12Frame],
    right_frames: list[CapturedNv12Frame],
    *,
    max_skew_frames: int,
):
    left_refs = [
        EyePacketRef(LEFT_EYE_DIR, frame.frame_id, Path(), index, frame.timestamp_us)
        for index, frame in enumerate(left_frames, start=1)
    ]
    right_refs = [
        EyePacketRef(RIGHT_EYE_DIR, frame.frame_id, Path(), index, frame.timestamp_us)
        for index, frame in enumerate(right_frames, start=1)
    ]
    return pair_eye_packets(left_refs, right_refs, max_skew_frames=max_skew_frames)


def _release_reader(reader: Any) -> None:
    if hasattr(reader, "release"):
        reader.release()


def _coerce_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LiveStereoRecorderError(f"{name} must be a positive integer, got {value!r}")
    if value <= 0:
        raise LiveStereoRecorderError(f"{name} must be positive, got {value}")
    return value


def _coerce_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LiveStereoRecorderError(
            f"{name} must be a non-negative integer, got {value!r}"
        )
    if value < 0:
        raise LiveStereoRecorderError(f"{name} must be non-negative, got {value}")
    return value


def _coerce_optional_positive_float(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LiveStereoRecorderError(f"{name} must be a positive number, got {value!r}")
    value = float(value)
    if value <= 0.0:
        raise LiveStereoRecorderError(f"{name} must be positive, got {value}")
    return value
