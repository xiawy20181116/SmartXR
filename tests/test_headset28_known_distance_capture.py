"""Headset #28 known-distance capture session tests for YAN-119."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from smartxr.live_stereo_recorder import CapturedNv12Frame, record_live_stereo_package
from smartxr.nv12_reader import nv12_payload_size
from smartxr.stereo_depth import (
    DEPTH_SOURCE_KNOWN_DISTANCE_GT,
    POSE_QUALITY_STEREO,
    SCENE_STEREO_28,
)


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "prepare_headset28_known_distance_capture.py"
RUNNER = ROOT / "tools" / "run_headset28_known_distance_capture.ps1"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_frame(frame_id: int, *, fill: int) -> CapturedNv12Frame:
    width = 24
    height = 18
    stride = 24
    return CapturedNv12Frame(
        frame_id=frame_id,
        width=width,
        height=height,
        stride=stride,
        timestamp_us=frame_id * 1000,
        payload=bytes([fill]) * nv12_payload_size(height, stride),
    )


class FakeReader:
    def __init__(self, frames: list[CapturedNv12Frame]):
        self.frames = list(frames)
        self.index = 0

    def read_latest(self):
        if self.index >= len(self.frames):
            return True, -1, None
        frame = self.frames[self.index]
        self.index += 1
        return True, frame.frame_id, frame

    def release(self):
        pass


class Headset28KnownDistanceCaptureTests(unittest.TestCase):
    def test_writes_run_status_and_known_distance_gt_records_for_valid_package(self):
        capture = load_module(TOOL, "prepare_headset28_known_distance_capture")

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "headset28_known_distance_test"
            package_dir = run_dir / "stereo_package"
            package_dir.mkdir(parents=True)
            recorder_status = record_live_stereo_package(
                left_reader=FakeReader([make_frame(10, fill=0x11), make_frame(11, fill=0x12)]),
                right_reader=FakeReader([make_frame(10, fill=0x21), make_frame(11, fill=0x22)]),
                out_dir=package_dir,
                calibration=SCENE_STEREO_28.scaled_to(24, 18),
                max_read_attempts=2,
                max_skew_frames=0,
                sleep_seconds=0.0,
            )

            status = capture.write_known_distance_capture_run(
                run_dir=run_dir,
                stereo_package_dir=package_dir,
                known_distance_m=1.25,
                target_id="person-known-1",
                recorded_width=24,
                recorded_height=18,
                recorder_status=recorder_status,
                recorder_exit_code=0,
                run_id="headset28_known_distance_test",
                created_at="2026-06-19T00:00:00Z",
                command=["runner.ps1", "-KnownDistanceM", "1.25"],
            )

            self.assertTrue(status["ready_for_depth_error_report"])
            self.assertEqual(status["reason"], "ready_for_depth_error_report")
            self.assertEqual(status["pair_count"], 2)
            self.assertEqual(status["gt_record_count"], 2)
            self.assertEqual(status["validation_errors"], [])

            run_manifest = json.loads((run_dir / "capture_run.json").read_text(encoding="utf-8"))
            self.assertEqual(run_manifest["type"], "headset28_known_distance_capture")
            self.assertEqual(run_manifest["device_id"], "28")
            self.assertEqual(run_manifest["run_id"], "headset28_known_distance_test")
            self.assertEqual(run_manifest["known_distance"]["distance_m"], 1.25)
            self.assertEqual(run_manifest["known_distance"]["target_id"], "person-known-1")
            self.assertEqual(run_manifest["stereo_package"]["relative_path"], "stereo_package")
            self.assertEqual(run_manifest["stereo_package"]["pair_count"], 2)
            self.assertEqual(run_manifest["recording"]["recorded_width"], 24)
            self.assertEqual(run_manifest["recording"]["recorded_height"], 18)

            records = [
                json.loads(line)
                for line in (run_dir / "known_distance_gt.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([record["pair_id"] for record in records], ["pair-000010", "pair-000011"])
            self.assertEqual(records[0]["depth_source"], DEPTH_SOURCE_KNOWN_DISTANCE_GT)
            self.assertTrue(records[0]["is_ground_truth"])
            self.assertEqual(records[0]["depth_m"], 1.25)
            self.assertEqual(records[0]["pose_quality"], POSE_QUALITY_STEREO)
            self.assertEqual(records[0]["calibration_ref"], "headset-28-scene-pov-v1")

    def test_invalid_package_writes_failure_status_without_gt_records(self):
        capture = load_module(TOOL, "prepare_headset28_known_distance_capture")

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "headset28_known_distance_bad"
            package_dir = run_dir / "stereo_package"
            package_dir.mkdir(parents=True)

            status = capture.write_known_distance_capture_run(
                run_dir=run_dir,
                stereo_package_dir=package_dir,
                known_distance_m=1.25,
                target_id="person-known-1",
                recorded_width=24,
                recorded_height=18,
                recorder_status={"frames_seen_left": 0, "frames_seen_right": 0, "pair_count": 0},
                recorder_exit_code=1,
                run_id="headset28_known_distance_bad",
                created_at="2026-06-19T00:00:00Z",
            )

            self.assertFalse(status["ready_for_depth_error_report"])
            self.assertFalse(status["source_alive"])
            self.assertEqual(status["reason"], "vst_source_unavailable")
            self.assertIn("missing stereo.json", status["validation_errors"])
            self.assertFalse((run_dir / "known_distance_gt.jsonl").exists())
            persisted = json.loads((run_dir / "capture_status.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["reason"], "vst_source_unavailable")

    def test_runner_wires_existing_recorder_to_known_distance_helper(self):
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("record_antman_vst_stereo_package.py", source)
        self.assertIn("prepare_headset28_known_distance_capture.py", source)
        self.assertIn("KnownDistanceM", source)
        self.assertIn("capture_run.json", source)
        self.assertIn("capture_status.json", source)
        self.assertIn("stereo_package", source)


if __name__ == "__main__":
    unittest.main()
