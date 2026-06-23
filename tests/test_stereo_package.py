"""Offline stereo package/pairing tests for YAN-119.

The package layer is intentionally device-free: a stereo capture is a root
``stereo.json`` plus two normal mono NV12 sessions under ``left/`` and
``right/``. Pairing is derived from stable shared frame ids, never wall-clock
time, and each eye must still round-trip through ``nv12_reader.iter_session``.
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
    iter_session,
    nv12_payload_size,
)
from smartxr.stereo_depth import SCENE_STEREO_28, build_stereo_session_metadata
from smartxr.stereo_package import (
    LEFT_EYE_DIR,
    RIGHT_EYE_DIR,
    StereoPackageError,
    load_eye_packet_refs,
    load_stereo_package,
    pair_eye_packets,
    validate_stereo_package,
)

HEADER_STRUCT = struct.Struct("<6IQ")


def make_packet(
    width: int = 4,
    height: int = 2,
    stride: int | None = None,
    timestamp_us: int = 123456,
) -> bytes:
    if stride is None:
        stride = width
    payload_size = nv12_payload_size(height, stride)
    header = HEADER_STRUCT.pack(
        NV12_MAGIC,
        HEADER_SIZE,
        width,
        height,
        stride,
        payload_size,
        timestamp_us,
    )
    return header + b"\x10" * (stride * height) + b"\x80" * (stride * height // 2)


def write_eye_session(
    package_dir: Path,
    eye: str,
    frame_ids: list[int],
    *,
    timestamps_us: list[int] | None = None,
) -> None:
    eye_dir = package_dir / eye
    packet_dir = eye_dir / "nv12_packets"
    packet_dir.mkdir(parents=True)
    files = []
    if timestamps_us is None:
        timestamps_us = [frame_id * 1000 for frame_id in frame_ids]
    for position, (frame_id, timestamp_us) in enumerate(
        zip(frame_ids, timestamps_us, strict=True),
        start=1,
    ):
        name = f"packet_{position:06d}.bin"
        (packet_dir / name).write_bytes(make_packet(timestamp_us=timestamp_us))
        files.append(f"nv12_packets/{name}")
    (eye_dir / "metadata.json").write_text(
        json.dumps(
            {
                "width": 4,
                "height": 2,
                "stride": 4,
                "files": files,
                "frame_ids": frame_ids,
            }
        ),
        encoding="utf-8",
    )


def write_stereo_metadata(
    package_dir: Path,
    *,
    pair_count: int,
    dropped_unpaired_left: int,
    dropped_unpaired_right: int,
    max_skew_frames: int,
) -> None:
    metadata = build_stereo_session_metadata(
        SCENE_STEREO_28.scaled_to(1164, 872),
        pair_count=pair_count,
        dropped_unpaired_left=dropped_unpaired_left,
        dropped_unpaired_right=dropped_unpaired_right,
        max_skew_frames=max_skew_frames,
    )
    (package_dir / "stereo.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )


class StereoPackageTests(unittest.TestCase):
    def test_loads_package_pairs_shared_frame_ids_and_counts_drops(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp)
            write_eye_session(
                package_dir,
                LEFT_EYE_DIR,
                [100, 101, 102],
                timestamps_us=[100_000, 101_000, 102_000],
            )
            write_eye_session(
                package_dir,
                RIGHT_EYE_DIR,
                [100, 102, 103],
                timestamps_us=[100_125, 102_125, 103_125],
            )
            write_stereo_metadata(
                package_dir,
                pair_count=2,
                dropped_unpaired_left=1,
                dropped_unpaired_right=1,
                max_skew_frames=1,
            )

            summary = load_stereo_package(package_dir)

            self.assertEqual([pair.frame_id for pair in summary.pairs], [100, 102])
            self.assertEqual([pair.pair_id for pair in summary.pairs], ["pair-000100", "pair-000102"])
            self.assertEqual([pair.skew_frames for pair in summary.pairs], [0, 1])
            self.assertEqual([pair.timestamp_skew_us for pair in summary.pairs], [125, 125])
            self.assertEqual(summary.dropped_unpaired_left, 1)
            self.assertEqual(summary.dropped_unpaired_right, 1)
            self.assertEqual(summary.max_skew_frames, 1)

            left_frames = list(iter_session(package_dir / LEFT_EYE_DIR))
            right_frames = list(iter_session(package_dir / RIGHT_EYE_DIR))
            self.assertEqual([frame.timestamp_us for frame in left_frames], [100_000, 101_000, 102_000])
            self.assertEqual([frame.timestamp_us for frame in right_frames], [100_125, 102_125, 103_125])
            self.assertEqual(validate_stereo_package(package_dir), [])

    def test_pairing_sorts_by_frame_id_and_applies_max_skew_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp)
            write_eye_session(package_dir, LEFT_EYE_DIR, [12, 10, 11])
            write_eye_session(package_dir, RIGHT_EYE_DIR, [10, 11, 12])
            left_refs = load_eye_packet_refs(package_dir / LEFT_EYE_DIR, LEFT_EYE_DIR)
            right_refs = load_eye_packet_refs(package_dir / RIGHT_EYE_DIR, RIGHT_EYE_DIR)

            unbounded = pair_eye_packets(left_refs, right_refs)
            bounded = pair_eye_packets(left_refs, right_refs, max_skew_frames=1)

            self.assertEqual([pair.frame_id for pair in unbounded.pairs], [10, 11, 12])
            self.assertEqual(unbounded.max_skew_frames, 2)
            self.assertEqual([pair.frame_id for pair in bounded.pairs], [10, 11])
            self.assertEqual(bounded.dropped_unpaired_left, 1)
            self.assertEqual(bounded.dropped_unpaired_right, 1)

    def test_validate_rejects_missing_stereo_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp)
            write_eye_session(package_dir, LEFT_EYE_DIR, [1])
            write_eye_session(package_dir, RIGHT_EYE_DIR, [1])

            errors = validate_stereo_package(package_dir)

            self.assertTrue(any("missing stereo.json" in error for error in errors))

    def test_validate_reports_pairing_stats_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp)
            write_eye_session(package_dir, LEFT_EYE_DIR, [100, 101, 102])
            write_eye_session(package_dir, RIGHT_EYE_DIR, [100, 102, 103])
            write_stereo_metadata(
                package_dir,
                pair_count=99,
                dropped_unpaired_left=0,
                dropped_unpaired_right=0,
                max_skew_frames=1,
            )

            errors = validate_stereo_package(package_dir)

            self.assertTrue(any("pairing.stats.pair_count" in error for error in errors))
            self.assertTrue(any("pairing.stats.dropped_unpaired_left" in error for error in errors))
            self.assertTrue(any("pairing.stats.dropped_unpaired_right" in error for error in errors))

    def test_load_eye_packet_refs_rejects_frame_id_count_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp)
            write_eye_session(package_dir, LEFT_EYE_DIR, [1, 2])
            meta_path = package_dir / LEFT_EYE_DIR / "metadata.json"
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            metadata["frame_ids"] = [1]
            meta_path.write_text(json.dumps(metadata), encoding="utf-8")

            with self.assertRaises(StereoPackageError):
                load_eye_packet_refs(package_dir / LEFT_EYE_DIR, LEFT_EYE_DIR)

    def test_load_eye_packet_refs_rejects_non_integer_frame_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp)
            write_eye_session(package_dir, LEFT_EYE_DIR, [1])
            meta_path = package_dir / LEFT_EYE_DIR / "metadata.json"
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            metadata["frame_ids"] = [1.5]
            meta_path.write_text(json.dumps(metadata), encoding="utf-8")

            with self.assertRaises(StereoPackageError):
                load_eye_packet_refs(package_dir / LEFT_EYE_DIR, LEFT_EYE_DIR)


if __name__ == "__main__":
    unittest.main()
