"""Live dual-eye SHM recorder core tests for YAN-119.

The real Antman reader is device-bound. These tests pin the recorder boundary
with fake ``read_latest()`` readers: the live layer collects Left/Right frames,
writes ordinary mono NV12 sessions, and lets ``stereo_package`` compute the
shared-frame pairing stats.
"""

from __future__ import annotations

import json
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path, PureWindowsPath

from smartxr.live_stereo_recorder import (
    CapturedNv12Frame,
    LiveStereoRecorderError,
    coerce_captured_nv12_frame,
    record_live_stereo_package,
)
from smartxr.nv12_reader import iter_session, nv12_payload_size
from smartxr.stereo_depth import SCENE_STEREO_28
from smartxr.stereo_package import (
    LEFT_EYE_DIR,
    RIGHT_EYE_DIR,
    load_stereo_package,
    validate_stereo_package,
)

ROOT = Path(__file__).resolve().parents[1]
ANTMAN_TOOL = ROOT / "tools" / "record_antman_vst_stereo_package.py"
ANTMAN_RUNNER = ROOT / "tools" / "run_antman_vst_stereo_package_recorder.ps1"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_frame(
    frame_id: int,
    *,
    width: int = 4,
    height: int = 2,
    stride: int = 4,
    timestamp_us: int | None = None,
    fill: int = 0x10,
) -> CapturedNv12Frame:
    if timestamp_us is None:
        timestamp_us = frame_id * 1000
    payload = bytes([fill]) * nv12_payload_size(height, stride)
    return CapturedNv12Frame(
        frame_id=frame_id,
        width=width,
        height=height,
        stride=stride,
        timestamp_us=timestamp_us,
        payload=payload,
    )


class FakeReader:
    def __init__(self, frames: list[CapturedNv12Frame]):
        self.frames = list(frames)
        self.index = 0
        self.released = False

    def read_latest(self):
        if self.index >= len(self.frames):
            return True, -1, None
        frame = self.frames[self.index]
        self.index += 1
        return True, frame.frame_id, frame

    def get_stats(self):
        return {"frames_returned": self.index}

    def release(self):
        self.released = True


class FakeNv12Array:
    shape = (3, 4)

    def __init__(self):
        self.payload = bytes([0x33]) * 12

    def tobytes(self):
        return self.payload


class LiveStereoRecorderTests(unittest.TestCase):
    def test_records_dual_eye_readers_into_valid_stereo_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            left = FakeReader(
                [
                    make_frame(100, timestamp_us=100_000, fill=0x11),
                    make_frame(101, timestamp_us=101_000, fill=0x12),
                    make_frame(102, timestamp_us=102_000, fill=0x13),
                ]
            )
            right = FakeReader(
                [
                    make_frame(100, timestamp_us=100_125, fill=0x21),
                    make_frame(102, timestamp_us=102_125, fill=0x22),
                    make_frame(103, timestamp_us=103_125, fill=0x23),
                ]
            )

            status = record_live_stereo_package(
                left_reader=left,
                right_reader=right,
                out_dir=out_dir,
                calibration=SCENE_STEREO_28.scaled_to(1164, 872),
                max_read_attempts=3,
                max_skew_frames=1,
                sleep_seconds=0.0,
            )

            self.assertTrue(left.released)
            self.assertTrue(right.released)
            self.assertEqual(status["frames_seen_left"], 3)
            self.assertEqual(status["frames_seen_right"], 3)
            self.assertEqual(status["pair_count"], 2)
            self.assertEqual(status["dropped_unpaired_left"], 1)
            self.assertEqual(status["dropped_unpaired_right"], 1)
            self.assertEqual(status["max_skew_frames"], 1)
            self.assertEqual(validate_stereo_package(out_dir), [])

            left_frames = list(iter_session(out_dir / LEFT_EYE_DIR))
            right_frames = list(iter_session(out_dir / RIGHT_EYE_DIR))
            self.assertEqual([frame.timestamp_us for frame in left_frames], [100_000, 101_000, 102_000])
            self.assertEqual([frame.timestamp_us for frame in right_frames], [100_125, 102_125, 103_125])

            summary = load_stereo_package(out_dir)
            self.assertEqual([pair.pair_id for pair in summary.pairs], ["pair-000100", "pair-000102"])

            metadata = json.loads((out_dir / "stereo.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["pairing"]["stats"]["pair_count"], 2)
            self.assertEqual(metadata["pairing"]["stats"]["dropped_unpaired_left"], 1)
            self.assertEqual(metadata["pairing"]["stats"]["dropped_unpaired_right"], 1)

    def test_coerce_mapping_frame_rejects_bad_payload_size(self):
        with self.assertRaises(LiveStereoRecorderError):
            coerce_captured_nv12_frame(
                {
                    "width": 4,
                    "height": 2,
                    "stride": 4,
                    "timestamp_us": 1000,
                    "payload": b"too-short",
                },
                frame_id=1,
            )

    def test_coerce_nv12_like_array_frame_from_reader(self):
        frame = coerce_captured_nv12_frame(
            FakeNv12Array(),
            frame_id=7,
            fallback_timestamp_us=70_000,
        )

        self.assertEqual(frame.frame_id, 7)
        self.assertEqual(frame.width, 4)
        self.assertEqual(frame.height, 2)
        self.assertEqual(frame.stride, 4)
        self.assertEqual(frame.timestamp_us, 70_000)
        self.assertEqual(frame.payload, bytes([0x33]) * 12)

    def test_record_rejects_non_integer_reader_frame_id(self):
        class BadFrameIdReader:
            def read_latest(self):
                return True, 1.5, make_frame(1)

            def release(self):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LiveStereoRecorderError):
                record_live_stereo_package(
                    left_reader=BadFrameIdReader(),
                    right_reader=FakeReader([]),
                    out_dir=Path(tmp),
                    calibration=SCENE_STEREO_28.scaled_to(1164, 872),
                    max_read_attempts=1,
                    max_skew_frames=0,
                    sleep_seconds=0.0,
                )

    def test_antman_tool_wires_left_right_shm_names_to_recorder_core(self):
        tool = load_module(ANTMAN_TOOL, "record_antman_vst_stereo_package")

        self.assertEqual(
            tool.build_stereo_shm_names("Antman.VST.AI.v1"),
            ("Antman.VST.AI.v1.Left", "Antman.VST.AI.v1.Right"),
        )

        tool_source = ANTMAN_TOOL.read_text(encoding="utf-8")
        runner_source = ANTMAN_RUNNER.read_text(encoding="utf-8")
        self.assertIn("record_live_stereo_package", tool_source)
        self.assertIn("VstAiShmReader", tool_source)
        self.assertIn("build_stereo_shm_names", tool_source)
        self.assertIn("record_antman_vst_stereo_package.py", runner_source)
        self.assertIn("Antman.VST.AI.v1", runner_source)

    def test_antman_tool_defaults_to_vst_ai_shm_consumer_module(self):
        tool = load_module(ANTMAN_TOOL, "record_antman_vst_stereo_package")

        self.assertEqual(
            PureWindowsPath(str(tool.DEFAULT_VST_AI_SHM_ROOT)),
            PureWindowsPath("E:\\xia\\Antman\\0422\\0527\\P1\\vst_ai_shm"),
        )
        tool_source = ANTMAN_TOOL.read_text(encoding="utf-8")
        self.assertIn("VstAiShmConsumer", tool_source)
        self.assertIn("--vst-ai-shm-root", tool_source)

    def test_vst_ai_shm_consumer_reader_preserves_header_timestamp_us_in_recorded_package(self):
        tool = load_module(ANTMAN_TOOL, "record_antman_vst_stereo_package")

        class FakeConsumer:
            def __init__(self, frame_id: int, timestamp_us: int):
                self.frame_id = frame_id
                self.timestamp_us = timestamp_us
                self.frames_returned = 0
                self.acknowledged = []
                self.closed = False
                self.shm_name = f"fake-{frame_id}"
                self.event_name = f"fake-event-{frame_id}"

            def wait_for_frame(self, timeout_ms):
                return self.frames_returned == 0

            def read_latest_frame(self):
                self.frames_returned += 1
                return (
                    {
                        "frame_id": self.frame_id,
                        "width": 4,
                        "height": 2,
                        "stride": 4,
                        "timestamp_us": self.timestamp_us,
                    },
                    FakeNv12Array(),
                )

            def acknowledge(self, frame_id):
                self.acknowledged.append(frame_id)

            def close(self):
                self.closed = True

        left_consumer = FakeConsumer(frame_id=10, timestamp_us=123_456)
        right_consumer = FakeConsumer(frame_id=10, timestamp_us=123_789)
        left_reader = tool.VstAiShmConsumerReader(consumer=left_consumer, wait_timeout_ms=1)
        right_reader = tool.VstAiShmConsumerReader(consumer=right_consumer, wait_timeout_ms=1)

        out_dir = ROOT / ".tmp" / "test_live_stereo_recorder" / "vst_ai_shm_timestamp"
        shutil.rmtree(out_dir, ignore_errors=True)
        try:
            status = record_live_stereo_package(
                left_reader=left_reader,
                right_reader=right_reader,
                out_dir=out_dir,
                calibration=SCENE_STEREO_28.scaled_to(1164, 872),
                max_read_attempts=1,
                max_skew_frames=0,
                sleep_seconds=0.0,
            )

            self.assertEqual(status["pair_count"], 1)
            self.assertEqual(left_consumer.acknowledged, [10])
            self.assertEqual(right_consumer.acknowledged, [10])
            self.assertTrue(left_consumer.closed)
            self.assertTrue(right_consumer.closed)

            left_metadata = json.loads((out_dir / LEFT_EYE_DIR / "metadata.json").read_text(encoding="utf-8"))
            right_metadata = json.loads((out_dir / RIGHT_EYE_DIR / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(left_metadata["timestamps_us"], [123_456])
            self.assertEqual(right_metadata["timestamps_us"], [123_789])
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
