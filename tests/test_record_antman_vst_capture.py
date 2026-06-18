from __future__ import annotations

import importlib.util
import json
import shutil
import uuid
import unittest
from pathlib import Path

from smartxr.nv12_reader import iter_session


ROOT = Path(__file__).resolve().parents[1]
RECORDER = ROOT / "tools" / "record_antman_vst_capture.py"
RUNNER = ROOT / "tools" / "run_record_antman_vst_capture.ps1"
TMP = ROOT / ".tmp" / "test_record_antman_vst_capture"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeNv12Frame:
    def __init__(
        self,
        *,
        width: int = 4,
        height: int = 4,
        stride: int = 6,
        timestamp_us: int = 2_000_000,
        fill_y: int = 17,
        fill_uv: int = 128,
    ):
        self.width = width
        self.height = height
        self.stride = stride
        self.timestamp_us = timestamp_us
        self.nv12 = bytes([fill_y]) * (stride * height) + bytes([fill_uv]) * (stride * height // 2)


class RecordAntmanVstCaptureTests(unittest.TestCase):
    def make_tmp_dir(self) -> Path:
        path = TMP / uuid.uuid4().hex
        path.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(path, ignore_errors=True))
        return path

    def test_writer_round_trips_through_nv12_reader(self):
        recorder = load_module(RECORDER, "record_antman_vst_capture")
        source = FakeNv12Frame()

        session_dir = self.make_tmp_dir()
        writer = recorder.CaptureSessionWriter(
            session_dir=session_dir,
            shm_name="Antman.VST.AI.v1",
            shm_eye="Right",
            resolved_shm_name="Antman.VST.AI.v1.Right",
            antman_root=Path("E:/xia/Antman_smart"),
            source_version="test-source",
            record_start_wall_clock="2026-06-18T10:00:00Z",
        )
        writer.write_frame(
            frame=source,
            frame_id=42,
            timestamp_us=source.timestamp_us,
            at_ms=0.0,
        )
        writer.write_manifest(
            status={"source_alive": True, "frames_written": 1, "dropped": 0, "reason": "max_frames"},
        )

        frames = list(iter_session(session_dir))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].width, source.width)
        self.assertEqual(frames[0].height, source.height)
        self.assertEqual(frames[0].stride, source.stride)
        self.assertEqual(frames[0].timestamp_us, source.timestamp_us)
        self.assertEqual(frames[0].y_plane, source.nv12[: source.stride * source.height])
        self.assertEqual(frames[0].uv_plane, source.nv12[source.stride * source.height :])

        metadata = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["files"], ["nv12_packets/packet_000001.bin"])
        self.assertEqual(metadata["width"], source.width)
        self.assertEqual(metadata["height"], source.height)
        self.assertEqual(metadata["stride"], source.stride)
        self.assertEqual(metadata["shm_name"], "Antman.VST.AI.v1")
        self.assertEqual(metadata["shm_eye"], "Right")
        self.assertEqual(metadata["resolved_shm_name"], "Antman.VST.AI.v1.Right")

        timeline = json.loads((session_dir / "timeline.json").read_text(encoding="utf-8"))
        self.assertEqual(timeline["frames"][0]["frame_id"], 42)
        self.assertEqual(timeline["frames"][0]["at_ms"], 0.0)
        self.assertEqual(timeline["frames"][0]["timestamp_us"], source.timestamp_us)

    def test_recorder_dedups_frame_ids_and_reports_status(self):
        recorder = load_module(RECORDER, "record_antman_vst_capture")
        source = FakeNv12Frame()

        class FakeReader:
            def __init__(self):
                self.index = 0
                self.released = False

            def read_latest(self):
                frames = [
                    (True, 10, source),
                    (True, 10, source),
                    (True, 11, FakeNv12Frame(timestamp_us=2_033_000, fill_y=18)),
                ]
                if self.index >= len(frames):
                    return True, -1, None
                item = frames[self.index]
                self.index += 1
                return item

            def release(self):
                self.released = True

        session_dir = self.make_tmp_dir()
        reader = FakeReader()
        status = recorder.record_vst_capture(
            reader=reader,
            session_dir=session_dir,
            duration_seconds=30.0,
            max_frames=2,
            shm_name="Antman.VST.AI.v1",
            shm_eye="Right",
            resolved_shm_name="Antman.VST.AI.v1.Right",
            antman_root=Path("E:/xia/Antman_smart"),
            source_version="test-source",
            sleep_seconds=0.0,
        )

        self.assertTrue(reader.released)
        self.assertTrue(status["source_alive"])
        self.assertEqual(status["frames_written"], 2)
        self.assertEqual(status["dropped"], 1)
        self.assertEqual(status["reason"], "max_frames")
        self.assertEqual([f.timestamp_us for f in iter_session(session_dir)], [2_000_000, 2_033_000])
        timeline = json.loads((session_dir / "timeline.json").read_text(encoding="utf-8"))
        self.assertEqual([frame["at_ms"] for frame in timeline["frames"]], [0.0, 33.0])

    def test_runner_invokes_recorder_with_antman_python(self):
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("record_antman_vst_capture.py", source)
        self.assertIn("[string]$ShmEye = \"Right\"", source)
        self.assertIn("--shm-eye", source)
        self.assertIn("--max-frames", source)
        self.assertIn("human_detect\\.venv\\Scripts\\python.exe", source)
        self.assertIn(".uv-venv\\Scripts\\python.exe", source)
        self.assertIn("Need headset", source)


if __name__ == "__main__":
    unittest.main()
