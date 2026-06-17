"""L0/L1 tests for the NV12 capture reader (module 1, YAN-108).

Pure-python: packets are synthesized in memory, so no recorded capture data is
needed and the test stays inside the dependency-free CI gate.
"""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from smartxr.nv12_reader import (
    HEADER_SIZE,
    NV12_MAGIC,
    Nv12FormatError,
    iter_session,
    nv12_payload_size,
    parse_header,
    read_packet,
    session_packet_paths,
)

HEADER_STRUCT = struct.Struct("<6IQ")


def make_packet(
    width: int = 4,
    height: int = 2,
    stride: int | None = None,
    timestamp_us: int = 123456,
    *,
    fill_y: int = 0,
    fill_uv: int = 128,
    magic: int = NV12_MAGIC,
    header_size: int = HEADER_SIZE,
    payload_size: int | None = None,
    truncate_payload: bool = False,
) -> bytes:
    """Build one NV12 packet with controllable header fields for negative tests."""
    if stride is None:
        stride = width
    real_payload = nv12_payload_size(height, stride)
    header_payload = real_payload if payload_size is None else payload_size
    header = HEADER_STRUCT.pack(
        magic, header_size, width, height, stride, header_payload, timestamp_us
    )
    y = bytes([fill_y]) * (stride * height)
    uv = bytes([fill_uv]) * (stride * height // 2)
    payload = y + uv
    if truncate_payload:
        payload = payload[:-1]
    return header + payload


class HeaderTests(unittest.TestCase):
    def test_header_size_is_32(self):
        self.assertEqual(HEADER_SIZE, 32)

    def test_parse_real_geometry(self):
        # The actual capture geometry: 880x660, stride 896.
        raw = make_packet(width=880, height=660, stride=896, timestamp_us=168132637892)
        header = parse_header(raw)
        self.assertEqual(header["magic"], NV12_MAGIC)
        self.assertEqual(header["width"], 880)
        self.assertEqual(header["height"], 660)
        self.assertEqual(header["stride"], 896)
        self.assertEqual(header["payload_size"], 896 * 660 * 3 // 2)
        self.assertEqual(header["payload_size"], 887040)
        self.assertEqual(header["timestamp_us"], 168132637892)

    def test_rejects_bad_magic(self):
        with self.assertRaises(Nv12FormatError):
            parse_header(make_packet(magic=0xDEADBEEF))

    def test_rejects_bad_header_size(self):
        with self.assertRaises(Nv12FormatError):
            parse_header(make_packet(header_size=40))

    def test_rejects_stride_smaller_than_width(self):
        with self.assertRaises(Nv12FormatError):
            parse_header(make_packet(width=10, stride=8))

    def test_rejects_payload_size_mismatch(self):
        with self.assertRaises(Nv12FormatError):
            parse_header(make_packet(payload_size=999))

    def test_rejects_short_buffer(self):
        with self.assertRaises(Nv12FormatError):
            parse_header(b"\x00" * 8)


class ReadPacketTests(unittest.TestCase):
    def test_planes_split_at_stride(self):
        frame = read_packet(make_packet(width=4, height=2, stride=6), index=5)
        self.assertEqual(frame.index, 5)
        self.assertEqual(frame.width, 4)
        self.assertEqual(frame.height, 2)
        self.assertEqual(frame.stride, 6)
        self.assertEqual(len(frame.y_plane), 6 * 2)
        self.assertEqual(len(frame.uv_plane), 6 * 2 // 2)
        self.assertEqual(len(frame.y_plane) + len(frame.uv_plane), frame.payload_size)

    def test_timestamp_ms_from_us(self):
        frame = read_packet(make_packet(timestamp_us=2_000))
        self.assertEqual(frame.timestamp_ms, 2.0)

    def test_y_plane_cropped_drops_stride_padding(self):
        # width 3, stride 5, height 2; Y row r filled with value r+1.
        width, height, stride = 3, 2, 5
        header = HEADER_STRUCT.pack(
            NV12_MAGIC, HEADER_SIZE, width, height, stride,
            nv12_payload_size(height, stride), 0,
        )
        y = bytearray()
        for r in range(height):
            y += bytes([r + 1]) * width + b"\xff" * (stride - width)
        uv = b"\x80" * (stride * height // 2)
        frame = read_packet(header + bytes(y) + uv)
        cropped = frame.y_plane_cropped()
        self.assertEqual(len(cropped), width * height)
        self.assertEqual(cropped, bytes([1, 1, 1, 2, 2, 2]))

    def test_truncated_payload_rejected(self):
        with self.assertRaises(Nv12FormatError):
            read_packet(make_packet(truncate_payload=True))


class SessionTests(unittest.TestCase):
    def _make_session(self, root: Path, count: int, with_metadata: bool) -> None:
        packets = root / "nv12_packets"
        packets.mkdir(parents=True)
        files = []
        for i in range(1, count + 1):
            name = f"packet_{i:06d}.bin"
            (packets / name).write_bytes(make_packet(timestamp_us=i * 1000))
            files.append(f"nv12_packets/{name}")
        if with_metadata:
            (root / "metadata.json").write_text(
                json.dumps({"width": 4, "height": 2, "stride": 4, "files": files}),
                encoding="utf-8",
            )

    def test_iter_session_with_metadata_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_session(root, 5, with_metadata=True)
            self.assertEqual(len(session_packet_paths(root)), 5)
            frames = list(iter_session(root))
            self.assertEqual([f.index for f in frames], [1, 2, 3, 4, 5])
            self.assertEqual([f.timestamp_us for f in frames], [1000, 2000, 3000, 4000, 5000])

    def test_iter_session_glob_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_session(root, 3, with_metadata=False)
            frames = list(iter_session(root))
            self.assertEqual(len(frames), 3)

    def test_iter_session_window_and_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_session(root, 10, with_metadata=True)
            windowed = list(iter_session(root, start=2, limit=3))
            self.assertEqual([f.index for f in windowed], [3, 4, 5])
            stepped = list(iter_session(root, step=3))
            self.assertEqual([f.index for f in stepped], [1, 4, 7, 10])

    def test_iter_session_rejects_zero_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_session(root, 2, with_metadata=True)
            with self.assertRaises(ValueError):
                list(iter_session(root, step=0))


if __name__ == "__main__":
    unittest.main()
