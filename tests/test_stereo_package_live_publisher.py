from __future__ import annotations

import importlib.util
import json
import shutil
import struct
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from smartxr.nv12_reader import HEADER_SIZE, NV12_MAGIC, nv12_payload_size
from smartxr.stereo_depth import SCENE_STEREO_28, build_stereo_session_metadata


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PUBLISHER = ROOT / "tools" / "antman_vst_stereo_package_proxy_targets_live_publisher.py"
HEADER_STRUCT = struct.Struct("<6IQ")
TEST_TMP = ROOT / ".tmp" / "tests"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_packet(timestamp_us: int, width: int = 4, height: int = 2, stride: int = 4) -> bytes:
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


def write_eye_session(package_dir: Path, eye: str, frame_ids: list[int], timestamps_us: list[int]) -> None:
    eye_dir = package_dir / eye
    packet_dir = eye_dir / "nv12_packets"
    packet_dir.mkdir(parents=True)
    files = []
    for index, timestamp_us in enumerate(timestamps_us, start=1):
        name = f"packet_{index:06d}.bin"
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
                "timestamps_us": timestamps_us,
            }
        ),
        encoding="utf-8",
    )


def write_stereo_package(package_dir: Path) -> None:
    write_eye_session(package_dir, "left", [100, 101], [1_000_000, 1_033_333])
    write_eye_session(package_dir, "right", [100, 101], [1_000_120, 1_033_450])
    metadata = build_stereo_session_metadata(
        SCENE_STEREO_28.scaled_to(1164, 872),
        pair_count=2,
        dropped_unpaired_left=0,
        dropped_unpaired_right=0,
        max_skew_frames=0,
    )
    (package_dir / "stereo.json").write_text(json.dumps(metadata), encoding="utf-8")


@contextmanager
def temporary_package_dir():
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    path = TEST_TMP / f"stereo_package_live_publisher_{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class StereoPackageLivePublisherTests(unittest.TestCase):
    def test_package_replay_reader_returns_nv12_frames_with_live_timestamp_fields(self):
        publisher = load_module(PACKAGE_PUBLISHER, "antman_vst_stereo_package_proxy_targets_live_publisher")
        with temporary_package_dir() as tmp:
            package_dir = Path(tmp)
            write_stereo_package(package_dir)

            left_reader, right_reader = publisher.create_stereo_package_replay_readers(
                package_dir,
                replay_timing="fast",
                source_hz=45.0,
            )

            left_ok, left_frame_id, left_frame = left_reader.read_latest()
            right_ok, right_frame_id, right_frame = right_reader.read_latest()

            self.assertTrue(left_ok)
            self.assertTrue(right_ok)
            self.assertEqual(left_frame_id, 100)
            self.assertEqual(right_frame_id, 100)
            self.assertEqual(left_frame["timestamp_us"], 1_000_000)
            self.assertEqual(left_frame["exposure_us"], 1_000_000)
            self.assertEqual(right_frame["timestamp_us"], 1_000_120)
            self.assertEqual(right_frame["exposure_us"], 1_000_120)
            self.assertEqual(left_frame["available_timestamp_keys"], ["timestamp_us", "exposure_us"])
            self.assertEqual(left_frame["header_timestamp_debug"]["exposure_us"], 1_000_000)
            self.assertEqual(left_frame["payload"], b"\x10" * 8 + b"\x80" * 4)
            self.assertEqual(left_reader.get_stats()["reader"], "stereo_package_replay")
            self.assertEqual(left_reader.get_stats()["frames_returned"], 1)

    def test_package_replay_reader_supports_capture_and_fixed_timing(self):
        publisher = load_module(PACKAGE_PUBLISHER, "antman_vst_stereo_package_proxy_targets_live_publisher")
        with temporary_package_dir() as tmp:
            package_dir = Path(tmp)
            write_stereo_package(package_dir)

            capture_clock = FakeClock()
            capture_left, _capture_right = publisher.create_stereo_package_replay_readers(
                package_dir,
                replay_timing="capture",
                source_hz=45.0,
                monotonic_fn=capture_clock.monotonic,
                sleep_fn=capture_clock.sleep,
            )
            capture_left.read_latest()
            capture_left.read_latest()

            fixed_clock = FakeClock()
            fixed_left, _fixed_right = publisher.create_stereo_package_replay_readers(
                package_dir,
                replay_timing="fixed",
                source_hz=45.0,
                monotonic_fn=fixed_clock.monotonic,
                sleep_fn=fixed_clock.sleep,
            )
            fixed_left.read_latest()
            fixed_left.read_latest()

            self.assertAlmostEqual(capture_clock.sleeps[-1], 0.033333, places=5)
            self.assertAlmostEqual(fixed_clock.sleeps[-1], 1.0 / 45.0, places=5)

    def test_package_replay_parse_args_exposes_timing_modes_and_trace(self):
        publisher = load_module(PACKAGE_PUBLISHER, "antman_vst_stereo_package_proxy_targets_live_publisher")

        args = publisher.parse_args(
            [
                "--package-dir",
                ".tmp/stereo_package",
                "--replay-timing",
                "fixed",
                "--source-hz",
                "45",
                "--depth-trace",
                ".tmp/depth_estimation_trace.jsonl",
            ]
        )

        self.assertEqual(args.package_dir, Path(".tmp/stereo_package"))
        self.assertEqual(args.replay_timing, "fixed")
        self.assertEqual(args.source_hz, 45.0)
        self.assertEqual(args.depth_trace, Path(".tmp/depth_estimation_trace.jsonl"))


if __name__ == "__main__":
    unittest.main()
