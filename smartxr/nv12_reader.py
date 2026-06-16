"""NV12 capture packet/session reader (module 1, YAN-108).

Reads the recorded VST replay captures used to develop and verify the C1
(``tracking_raw``) producer without a device. Each session directory holds a
``metadata.json`` and an ``nv12_packets/`` folder of ``packet_*.bin`` files.

A packet is a fixed 32-byte header followed by a raw NV12 frame:

    header: ``<6I Q`` (little-endian)
        magic        uint32  == 0x4E563132  (ASCII "NV12")
        header_size  uint32  == 32
        width        uint32  pixels
        height       uint32  pixels
        stride       uint32  bytes per Y row (>= width; rows are padded)
        payload_size uint32  == stride * height * 3 // 2
        timestamp_us uint64  capture clock, microseconds

    payload: NV12 = a stride*height Y plane, then an interleaved
        stride*(height//2) UV plane (4:2:0, U and V byte-interleaved).

This module is **pure stdlib** (``struct`` only) so it stays inside the
dependency-free CI gate. NV12 -> RGB conversion and detection live in
``tools/`` behind optional numpy/opencv/ncnn (the PC-offload detection
backend), never imported by the test suite.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

# Header layout. ``calcsize`` of "<6IQ" is 32 with no padding (the '<' forces
# standard sizes/alignment), matching the recorded ``header_size`` field.
HEADER_FORMAT = "<6IQ"
HEADER_STRUCT = struct.Struct(HEADER_FORMAT)
HEADER_SIZE = HEADER_STRUCT.size  # 32

# 0x4E563132 == int.from_bytes(b"NV12", "big"); the four header bytes on disk
# (little-endian) read b"21VN", which is the same 32-bit value.
NV12_MAGIC = 0x4E563132

METADATA_FILE = "metadata.json"
PACKETS_DIR = "nv12_packets"


class Nv12FormatError(ValueError):
    """Raised when a packet header or payload does not match the NV12 contract."""


def nv12_payload_size(height: int, stride: int) -> int:
    """Bytes of NV12 image data for a frame of the given height and Y stride."""
    return stride * height * 3 // 2


@dataclass(frozen=True)
class Nv12Frame:
    """One decoded NV12 packet: header fields plus the two planes.

    ``index`` is the 1-based packet position within the session (0 for a
    standalone packet parsed via :func:`read_packet`). Planes are kept as raw
    ``bytes`` at the recorded ``stride`` (padding columns included); use
    :meth:`y_plane_cropped` to drop the stride padding for pure-python luma work.
    """

    index: int
    width: int
    height: int
    stride: int
    timestamp_us: int
    y_plane: bytes
    uv_plane: bytes

    @property
    def timestamp_ms(self) -> float:
        return self.timestamp_us / 1000.0

    @property
    def payload_size(self) -> int:
        return nv12_payload_size(self.height, self.stride)

    def y_plane_cropped(self) -> bytes:
        """Y (luma) plane with stride padding removed: width*height bytes."""
        if self.stride == self.width:
            return self.y_plane
        out = bytearray(self.width * self.height)
        for row in range(self.height):
            src = row * self.stride
            dst = row * self.width
            out[dst : dst + self.width] = self.y_plane[src : src + self.width]
        return bytes(out)


def parse_header(raw: bytes) -> dict:
    """Parse and validate a 32-byte NV12 packet header. Returns the fields."""
    if len(raw) < HEADER_SIZE:
        raise Nv12FormatError(
            f"packet too short for header: {len(raw)} < {HEADER_SIZE} bytes"
        )
    magic, header_size, width, height, stride, payload_size, timestamp_us = (
        HEADER_STRUCT.unpack_from(raw, 0)
    )
    if magic != NV12_MAGIC:
        raise Nv12FormatError(f"bad magic 0x{magic:08X}, expected 0x{NV12_MAGIC:08X}")
    if header_size != HEADER_SIZE:
        raise Nv12FormatError(f"header_size {header_size} != {HEADER_SIZE}")
    if width <= 0 or height <= 0 or stride < width:
        raise Nv12FormatError(
            f"invalid geometry width={width} height={height} stride={stride}"
        )
    expected = nv12_payload_size(height, stride)
    if payload_size != expected:
        raise Nv12FormatError(
            f"payload_size {payload_size} != stride*height*3/2 {expected}"
        )
    return {
        "magic": magic,
        "header_size": header_size,
        "width": width,
        "height": height,
        "stride": stride,
        "payload_size": payload_size,
        "timestamp_us": timestamp_us,
    }


def read_packet(raw: bytes, index: int = 0) -> Nv12Frame:
    """Parse one packet (header + payload) from ``raw`` bytes."""
    header = parse_header(raw)
    payload_size = header["payload_size"]
    end = HEADER_SIZE + payload_size
    if len(raw) < end:
        raise Nv12FormatError(
            f"packet payload truncated: have {len(raw) - HEADER_SIZE}, "
            f"need {payload_size} bytes"
        )
    height, stride = header["height"], header["stride"]
    y_size = stride * height
    y_plane = raw[HEADER_SIZE : HEADER_SIZE + y_size]
    uv_plane = raw[HEADER_SIZE + y_size : end]
    return Nv12Frame(
        index=index,
        width=header["width"],
        height=header["height"],
        stride=header["stride"],
        timestamp_us=header["timestamp_us"],
        y_plane=y_plane,
        uv_plane=uv_plane,
    )


def read_packet_file(path: Path, index: int = 0) -> Nv12Frame:
    return read_packet(Path(path).read_bytes(), index=index)


def load_session_metadata(session_dir: Path) -> dict:
    """Load ``metadata.json`` for a capture session."""
    return json.loads((Path(session_dir) / METADATA_FILE).read_text(encoding="utf-8"))


def session_packet_paths(session_dir: Path) -> list[Path]:
    """Ordered packet paths for a session.

    Prefers the ``files`` list in ``metadata.json`` (authoritative order); falls
    back to a sorted glob of ``nv12_packets/packet_*.bin`` when metadata is
    absent or lists no files.
    """
    session_dir = Path(session_dir)
    meta_path = session_dir / METADATA_FILE
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        files = meta.get("files")
        if isinstance(files, list) and files:
            return [session_dir / rel for rel in files]
    return sorted((session_dir / PACKETS_DIR).glob("packet_*.bin"))


def iter_session(
    session_dir: Path,
    start: int = 0,
    limit: int | None = None,
    step: int = 1,
) -> Iterator[Nv12Frame]:
    """Yield :class:`Nv12Frame` for packets in a session directory.

    ``start`` / ``limit`` / ``step`` select a window without loading the whole
    session into memory (packets are ~0.85 MB each). ``index`` on each yielded
    frame is its 1-based position in the full packet list.
    """
    if step < 1:
        raise ValueError("step must be >= 1")
    paths = session_packet_paths(session_dir)
    positions = range(start, len(paths), step)
    if limit is not None:
        positions = positions[:limit]
    for position in positions:
        # index is the 1-based packet position in the full session list.
        yield read_packet_file(paths[position], index=position + 1)
