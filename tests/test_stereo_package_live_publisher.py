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


def write_stereo_package(
    package_dir: Path,
    *,
    frame_ids: list[int] | None = None,
    left_timestamps_us: list[int] | None = None,
    right_timestamps_us: list[int] | None = None,
) -> None:
    frame_ids = frame_ids or [100, 101]
    left_timestamps_us = left_timestamps_us or [1_000_000, 1_033_333]
    right_timestamps_us = right_timestamps_us or [1_000_120, 1_033_450]
    write_eye_session(package_dir, "left", frame_ids, left_timestamps_us)
    write_eye_session(package_dir, "right", frame_ids, right_timestamps_us)
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
            capture_ok, capture_frame_id, capture_frame = capture_left.read_latest()

            fixed_clock = FakeClock()
            fixed_left, _fixed_right = publisher.create_stereo_package_replay_readers(
                package_dir,
                replay_timing="fixed",
                source_hz=45.0,
                monotonic_fn=fixed_clock.monotonic,
                sleep_fn=fixed_clock.sleep,
            )
            fixed_left.read_latest()
            fixed_ok, fixed_frame_id, fixed_frame = fixed_left.read_latest()

            self.assertTrue(capture_ok)
            self.assertEqual(capture_frame_id, -1)
            self.assertIsNone(capture_frame)
            self.assertEqual(capture_clock.sleeps, [])
            self.assertTrue(fixed_ok)
            self.assertEqual(fixed_frame_id, -1)
            self.assertIsNone(fixed_frame)
            self.assertEqual(fixed_clock.sleeps, [])

            capture_clock.now = 0.033334
            fixed_clock.now = 1.0 / 45.0
            self.assertEqual(capture_left.read_latest()[1], 101)
            self.assertEqual(fixed_left.read_latest()[1], 101)

    def test_package_replay_reader_clocked_modes_return_latest_due_frame_without_draining(self):
        publisher = load_module(PACKAGE_PUBLISHER, "antman_vst_stereo_package_proxy_targets_live_publisher")
        with temporary_package_dir() as tmp:
            package_dir = Path(tmp)
            write_stereo_package(
                package_dir,
                frame_ids=[100, 101, 102, 103],
                left_timestamps_us=[1_000_000, 1_022_222, 1_044_444, 1_066_666],
                right_timestamps_us=[1_000_100, 1_022_322, 1_044_544, 1_066_766],
            )
            clock = FakeClock()
            left_reader, _right_reader = publisher.create_stereo_package_replay_readers(
                package_dir,
                replay_timing="fixed",
                source_hz=45.0,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            )

            self.assertEqual(left_reader.read_latest()[1], 100)
            self.assertEqual(left_reader.read_latest()[1], -1)

            clock.now = 3.0 / 45.0
            ok, frame_id, frame = left_reader.read_latest()

            self.assertTrue(ok)
            self.assertEqual(frame_id, 103)
            self.assertIsNotNone(frame)
            stats = left_reader.get_stats()
            self.assertEqual(stats["frames_returned"], 2)
            self.assertEqual(stats["source_frame_index_gap"], 3)
            self.assertEqual(stats["detector_backlog"], 2)
            self.assertEqual(stats["frames_skipped_by_clock"], 2)
            self.assertIn("replay_clock_lag_ms", stats)

    def test_package_replay_source_clock_stats_are_promoted_to_trace_event(self):
        live = load_module(
            ROOT / "tools" / "antman_vst_stereo_proxy_targets_live_publisher.py",
            "antman_vst_stereo_proxy_targets_live_publisher_for_trace",
        )

        event = live.build_depth_trace_event(
            message=None,
            sequence=7,
            diagnostics={
                "reason": "no_target",
                "left_source_stats": {
                    "source_frame_index_gap": 4,
                    "replay_clock_lag_ms": 11.5,
                    "detector_backlog": 3,
                },
                "right_source_stats": {
                    "source_frame_index_gap": 2,
                    "replay_clock_lag_ms": 7.0,
                    "detector_backlog": 1,
                },
            },
        )

        self.assertEqual(event["source_frame_index_gap"], 4)
        self.assertEqual(event["left_source_frame_index_gap"], 4)
        self.assertEqual(event["right_source_frame_index_gap"], 2)
        self.assertEqual(event["replay_clock_lag_ms"], 11.5)
        self.assertEqual(event["detector_backlog"], 3)

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

    def test_package_replay_parse_args_exposes_depth_override_controls(self):
        publisher = load_module(PACKAGE_PUBLISHER, "antman_vst_stereo_package_proxy_targets_live_publisher")

        args = publisher.parse_args(
            [
                "--package-dir",
                ".tmp/stereo_package",
                "--depth-override-mode",
                "fixed",
                "--depth-override-fixed-m",
                "1.5",
                "--depth-override-scale",
                "1.1",
                "--depth-override-offset-m",
                "0.2",
                "--depth-override-noise-std-m",
                "0.04",
                "--depth-override-seed",
                "9",
            ]
        )

        self.assertEqual(args.depth_override_mode, "fixed")
        self.assertEqual(args.depth_override_fixed_m, 1.5)
        self.assertEqual(args.depth_override_scale, 1.1)
        self.assertEqual(args.depth_override_offset_m, 0.2)
        self.assertEqual(args.depth_override_noise_std_m, 0.04)
        self.assertEqual(args.depth_override_seed, 9)

    def test_package_replay_parse_args_exposes_keypoint_async_cache_controls(self):
        publisher = load_module(PACKAGE_PUBLISHER, "antman_vst_stereo_package_proxy_targets_live_publisher")

        args = publisher.parse_args(
            [
                "--package-dir",
                ".tmp/stereo_package",
                "--enable-keypoint-anchor",
                "--keypoint-max-hz",
                "10",
                "--keypoint-reuse-max-age-ms",
                "120",
            ]
        )

        self.assertEqual(args.keypoint_max_hz, 10.0)
        self.assertEqual(args.keypoint_reuse_max_age_ms, 120.0)


if __name__ == "__main__":
    unittest.main()
