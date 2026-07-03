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
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

from smartxr.live_stereo_recorder import (
    CapturedNv12Frame,
    LiveStereoRecorderError,
    coerce_captured_nv12_frame,
    record_live_stereo_package,
    write_mono_nv12_session,
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
ANTMAN_POSE_RUNNER = ROOT / "tools" / "run_antman_vst_stereo_package_recorder_with_pose.ps1"
WINDOWS_PCMR_RUNNER = ROOT / "tools" / "run_windows_pcmr.ps1"


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


class InfiniteReader:
    def __init__(self, *, start_frame_id: int = 1):
        self.next_frame_id = start_frame_id
        self.released = False

    def read_latest(self):
        frame = make_frame(self.next_frame_id)
        self.next_frame_id += 1
        return True, frame.frame_id, frame

    def release(self):
        self.released = True


class FakeNv12Array:
    shape = (3, 4)

    def __init__(self):
        self.payload = bytes([0x33]) * 12

    def tobytes(self):
        return self.payload


class LiveStereoRecorderTests(unittest.TestCase):
    def _out_dir(self, name: str) -> Path:
        out_dir = ROOT / ".tmp" / "test_live_stereo_recorder" / name
        shutil.rmtree(out_dir, ignore_errors=True)
        return out_dir

    def test_records_dual_eye_readers_into_valid_stereo_package(self):
        out_dir = self._out_dir("records_dual_eye_readers")
        try:
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

            with patch(
                "smartxr.live_stereo_recorder.time.time_ns",
                side_effect=[
                    1_000_000_001_000,
                    1_000_000_002_000,
                    1_000_000_003_000,
                    1_000_000_004_000,
                    1_000_000_005_000,
                    1_000_000_006_000,
                ],
            ):
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
            left_metadata = json.loads((out_dir / LEFT_EYE_DIR / "metadata.json").read_text(encoding="utf-8"))
            right_metadata = json.loads((out_dir / RIGHT_EYE_DIR / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(left_metadata["read_system_unix_time_us"], [1_000_000_001, 1_000_000_003, 1_000_000_005])
            self.assertEqual(right_metadata["read_system_unix_time_us"], [1_000_000_002, 1_000_000_004, 1_000_000_006])
            self.assertEqual(len(left_metadata["read_system_unix_time_us"]), len(left_metadata["frame_ids"]))
            self.assertEqual(len(left_metadata["read_system_unix_time_us"]), len(left_metadata["timestamps_us"]))
            self.assertEqual(len(right_metadata["read_system_unix_time_us"]), len(right_metadata["frame_ids"]))
            self.assertEqual(len(right_metadata["read_system_unix_time_us"]), len(right_metadata["timestamps_us"]))
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

    def test_record_stops_after_duration_without_estimating_attempts(self):
        out_dir = self._out_dir("record_stops_after_duration")
        try:
            left = InfiniteReader(start_frame_id=1)
            right = InfiniteReader(start_frame_id=1)

            status = record_live_stereo_package(
                left_reader=left,
                right_reader=right,
                out_dir=out_dir,
                calibration=SCENE_STEREO_28.scaled_to(1164, 872),
                max_read_attempts=10_000,
                max_skew_frames=0,
                sleep_seconds=0.001,
                duration_seconds=0.01,
            )

            self.assertTrue(1 <= status["attempts"] < 10_000)
            self.assertEqual(status["frames_seen_left"], status["attempts"])
            self.assertEqual(status["frames_seen_right"], status["attempts"])
            self.assertAlmostEqual(status["duration_seconds"], 0.01)
            self.assertGreaterEqual(status["elapsed_seconds"], 0.0)
            self.assertTrue(left.released)
            self.assertTrue(right.released)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

    def test_record_reports_progress_every_n_stereo_frames(self):
        out_dir = self._out_dir("record_reports_progress")
        try:
            progress: list[dict] = []
            left = FakeReader([make_frame(i) for i in range(1, 6)])
            right = FakeReader([make_frame(i) for i in range(1, 6)])

            status = record_live_stereo_package(
                left_reader=left,
                right_reader=right,
                out_dir=out_dir,
                calibration=SCENE_STEREO_28.scaled_to(1164, 872),
                max_read_attempts=5,
                max_skew_frames=0,
                sleep_seconds=0.0,
                progress_every_frames=2,
                progress_callback=progress.append,
            )

            self.assertEqual(status["frames_seen_left"], 5)
            self.assertEqual(status["frames_seen_right"], 5)
            self.assertEqual([event["stereo_frames"] for event in progress], [2, 4])
            self.assertEqual(progress[0]["frames_seen_left"], 2)
            self.assertEqual(progress[0]["frames_seen_right"], 2)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

    def test_write_mono_session_omits_read_system_time_when_frames_lack_it(self):
        out_dir = self._out_dir("write_mono_omits_missing_read_system_time")
        try:
            write_mono_nv12_session(
                out_dir,
                [
                    make_frame(1, timestamp_us=111_000),
                    make_frame(2, timestamp_us=222_000),
                ],
            )

            metadata = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))

            self.assertEqual(metadata["frame_ids"], [1, 2])
            self.assertEqual(metadata["timestamps_us"], [111_000, 222_000])
            self.assertNotIn("read_system_unix_time_us", metadata)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

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

        out_dir = self._out_dir("record_rejects_non_integer_reader_frame_id")
        try:
            with self.assertRaises(LiveStereoRecorderError):
                record_live_stereo_package(
                    left_reader=BadFrameIdReader(),
                    right_reader=FakeReader([]),
                    out_dir=out_dir,
                    calibration=SCENE_STEREO_28.scaled_to(1164, 872),
                    max_read_attempts=1,
                    max_skew_frames=0,
                    sleep_seconds=0.0,
                )
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

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
        self.assertIn("--duration-seconds", tool_source)
        self.assertIn("--progress-every-frames", tool_source)
        self.assertIn("[double]$DurationSeconds", runner_source)
        self.assertIn("[int]$ProgressEveryFrames", runner_source)

    def test_antman_pose_runner_wires_pcmr_pose_logger_recorder_and_merge(self):
        self.assertTrue(ANTMAN_POSE_RUNNER.exists())

        runner_source = ANTMAN_POSE_RUNNER.read_text(encoding="utf-8")

        self.assertIn("[string]$OutDir", runner_source)
        self.assertIn("[double]$DurationSeconds", runner_source)
        self.assertIn("[string]$SmartXROptionsPath", runner_source)
        self.assertIn("SMARTXR_XR_POSE_TRACE_PATH", runner_source)
        self.assertIn("$ResolvedOutDir", runner_source)
        self.assertIn('Join-Path -Path $ResolvedOutDir -ChildPath "xr_pose_trace.jsonl"', runner_source)
        self.assertIn('Join-Path -Path $ResolvedOutDir -ChildPath "frame_pose_assoc.jsonl"', runner_source)
        self.assertIn('$env:SMARTXR_XR_POSE_TRACE_PATH = $PoseTracePath', runner_source)
        self.assertIn("$OldSmartXrPoseTracePath", runner_source)
        self.assertIn("finally", runner_source)
        self.assertIn("Restore-EnvVar -Name \"SMARTXR_XR_POSE_TRACE_PATH\"", runner_source)
        self.assertIn("run_windows_pcmr.ps1", runner_source)
        self.assertIn("Start-Process", runner_source)
        self.assertIn("record_antman_vst_stereo_package.py", runner_source)
        self.assertIn("merge_stereo_pose_trace.py", runner_source)
        self.assertIn("frame_pose_assoc.jsonl", runner_source)
        self.assertIn("--pose-trace", runner_source)
        self.assertIn("--output", runner_source)
        self.assertNotIn("OpenXR", runner_source)

    def test_antman_pose_runner_resolves_paths_and_quotes_pcmr_child_args(self):
        runner_source = ANTMAN_POSE_RUNNER.read_text(encoding="utf-8")

        self.assertIn("function Resolve-RunnerPath", runner_source)
        self.assertIn("[System.IO.Path]::IsPathRooted($Path)", runner_source)
        self.assertIn("[System.IO.Path]::GetFullPath((Join-Path -Path $RepoRoot -ChildPath $Path))", runner_source)
        self.assertIn('$ResolvedOutDir = Resolve-RunnerPath -Path $OutDir', runner_source)
        self.assertIn('$ResolvedSmartXROptionsPath = ""', runner_source)
        self.assertIn(
            '$ResolvedSmartXROptionsPath = Resolve-RunnerPath -Path $SmartXROptionsPath',
            runner_source,
        )
        self.assertIn(' -SmartXROptionsPath ', runner_source)
        self.assertIn("$ResolvedSmartXROptionsPath", runner_source)
        self.assertIn("--out-dir $ResolvedOutDir", runner_source)
        self.assertIn("--package-dir $ResolvedOutDir", runner_source)
        self.assertIn("function ConvertTo-PowerShellLiteral", runner_source)
        self.assertIn('$PcmrCommand = "& " + (ConvertTo-PowerShellLiteral $PcmrRunner)', runner_source)
        self.assertIn(
            '$PcmrCommand += " -SmartXROptionsPath " + '
            "(ConvertTo-PowerShellLiteral $ResolvedSmartXROptionsPath)",
            runner_source,
        )
        self.assertIn("[System.Text.Encoding]::Unicode.GetBytes($PcmrCommand)", runner_source)
        self.assertIn("[Convert]::ToBase64String", runner_source)
        self.assertIn("$EncodedPcmrCommand", runner_source)
        self.assertIn('"-EncodedCommand"', runner_source)
        self.assertIn("$EncodedPcmrCommand", runner_source)
        self.assertIn("-ArgumentList $PcmrNativeArgs", runner_source)
        self.assertNotIn("$PcmrCommandLine", runner_source)
        self.assertNotIn("-ArgumentList $PcmrCommandLine", runner_source)
        self.assertNotIn("-ArgumentList $PcmrArgs", runner_source)
        self.assertNotIn("ConvertTo-PowerShellLiteral $_", runner_source)

    def test_antman_pose_runner_lets_pcmr_own_godot_lifecycle(self):
        pose_runner_source = ANTMAN_POSE_RUNNER.read_text(encoding="utf-8")
        pcmr_runner_source = WINDOWS_PCMR_RUNNER.read_text(encoding="utf-8")

        self.assertIn("[double]$RunForSeconds = 0.0", pcmr_runner_source)
        self.assertIn("[string]$StopWhenFileExists = \"\"", pcmr_runner_source)
        self.assertIn("$TimedRun = $RunForSeconds -gt 0.0", pcmr_runner_source)
        self.assertIn("$GodotProcess = Start-Process", pcmr_runner_source)
        self.assertIn("while (-not $GodotProcess.HasExited)", pcmr_runner_source)
        self.assertIn("Test-Path -LiteralPath $StopWhenFileExists", pcmr_runner_source)
        self.assertIn("Stop-ChildProcess -Process $GodotProcess", pcmr_runner_source)

        self.assertIn("$PcmrStopFile", pose_runner_source)
        self.assertIn("Remove-Item -LiteralPath $PoseTracePath, $FramePoseAssocPath, $PcmrStopFile", pose_runner_source)
        self.assertIn(' -RunForSeconds " + $PcmrRunSeconds', pose_runner_source)
        self.assertIn(' -StopWhenFileExists " + (ConvertTo-PowerShellLiteral $PcmrStopFile)', pose_runner_source)
        self.assertIn("Request-PcmrStop -Process $PcmrProcess -StopFile $PcmrStopFile", pose_runner_source)
        self.assertIn("$PcmrExitCode = $PcmrProcess.ExitCode", pose_runner_source)
        self.assertIn("if ($PcmrExitCode -ne 0)", pose_runner_source)
        self.assertIn("exit $PcmrExitCode", pose_runner_source)

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

    def test_vst_ai_shm_consumer_reader_uses_exposure_timestamp_header(self):
        tool = load_module(ANTMAN_TOOL, "record_antman_vst_stereo_package")

        class FakeConsumer:
            def __init__(self, frame_id: int, exposure_timestamp: int):
                self.frame_id = frame_id
                self.exposure_timestamp = exposure_timestamp
                self.frames_returned = 0
                self.acknowledged = []
                self.closed = False

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
                        "exposure_timestamp": self.exposure_timestamp,
                    },
                    FakeNv12Array(),
                )

            def acknowledge(self, frame_id):
                self.acknowledged.append(frame_id)

            def close(self):
                self.closed = True

        left_reader = tool.VstAiShmConsumerReader(
            consumer=FakeConsumer(frame_id=20, exposure_timestamp=234_567),
            wait_timeout_ms=1,
        )
        right_reader = tool.VstAiShmConsumerReader(
            consumer=FakeConsumer(frame_id=20, exposure_timestamp=234_890),
            wait_timeout_ms=1,
        )

        out_dir = ROOT / ".tmp" / "test_live_stereo_recorder" / "vst_ai_shm_exposure_timestamp"
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
            left_metadata = json.loads((out_dir / LEFT_EYE_DIR / "metadata.json").read_text(encoding="utf-8"))
            right_metadata = json.loads((out_dir / RIGHT_EYE_DIR / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(left_metadata["timestamps_us"], [234_567])
            self.assertEqual(right_metadata["timestamps_us"], [234_890])
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

    def test_vst_ai_shm_consumer_reader_uses_exposure_us_header(self):
        tool = load_module(ANTMAN_TOOL, "record_antman_vst_stereo_package")

        class FakeConsumer:
            def __init__(self, frame_id: int, exposure_us: int):
                self.frame_id = frame_id
                self.exposure_us = exposure_us
                self.frames_returned = 0

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
                        "exposure_us": self.exposure_us,
                    },
                    FakeNv12Array(),
                )

            def acknowledge(self, frame_id):
                pass

            def close(self):
                pass

        reader = tool.VstAiShmConsumerReader(
            consumer=FakeConsumer(frame_id=25, exposure_us=345_678),
            wait_timeout_ms=1,
        )

        ok, frame_id, frame = reader.read_latest()

        self.assertTrue(ok)
        self.assertEqual(frame_id, 25)
        self.assertEqual(frame["timestamp_us"], 345_678)
        self.assertEqual(frame["exposure_us"], 345_678)

    def test_vst_ai_shm_consumer_reader_includes_header_timestamp_debug(self):
        tool = load_module(ANTMAN_TOOL, "record_antman_vst_stereo_package")

        class FakeConsumer:
            def __init__(self):
                self.frames_returned = 0

            def wait_for_frame(self, timeout_ms):
                return self.frames_returned == 0

            def read_latest_frame(self):
                self.frames_returned += 1
                return (
                    {
                        "frame_id": 30,
                        "width": 4,
                        "height": 2,
                        "stride": 4,
                        "exposure_time_ns": 987_654_321,
                        "pts": 12345,
                        "random_value": 7,
                    },
                    FakeNv12Array(),
                )

            def acknowledge(self, frame_id):
                pass

            def close(self):
                pass

        reader = tool.VstAiShmConsumerReader(consumer=FakeConsumer(), wait_timeout_ms=1)

        ok, frame_id, frame = reader.read_latest()

        self.assertTrue(ok)
        self.assertEqual(frame_id, 30)
        self.assertEqual(frame["available_timestamp_keys"], ["exposure_time_ns", "frame_id", "pts"])
        self.assertEqual(
            frame["header_timestamp_debug"],
            {
                "exposure_time_ns": 987_654_321,
                "frame_id": 30,
                "pts": 12345,
            },
        )

    def test_vst_ai_shm_consumer_reader_stats_keep_recent_header_timestamp_debug(self):
        tool = load_module(ANTMAN_TOOL, "record_antman_vst_stereo_package")

        class FakeConsumer:
            def __init__(self):
                self.next_frame_id = 40

            def wait_for_frame(self, timeout_ms):
                return True

            def read_latest_frame(self):
                frame_id = self.next_frame_id
                self.next_frame_id += 1
                return (
                    {
                        "frame_id": frame_id,
                        "width": 4,
                        "height": 2,
                        "stride": 4,
                        "exposure_us": 900_000 + frame_id,
                    },
                    FakeNv12Array(),
                )

            def acknowledge(self, frame_id):
                pass

            def close(self):
                pass

        reader = tool.VstAiShmConsumerReader(
            consumer=FakeConsumer(),
            wait_timeout_ms=1,
            header_debug_frames=2,
        )

        reader.read_latest()
        reader.read_latest()
        reader.read_latest()
        stats = reader.get_stats()

        self.assertEqual(len(stats["recent_header_timestamp_debug"]), 2)
        self.assertEqual(stats["recent_header_timestamp_debug"][0]["frame_id"], 41)
        self.assertEqual(stats["recent_header_timestamp_debug"][1]["frame_id"], 42)
        self.assertEqual(stats["last_header_timestamp_debug"]["values"]["exposure_us"], 900_042)


if __name__ == "__main__":
    unittest.main()
