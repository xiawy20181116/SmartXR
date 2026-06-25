from __future__ import annotations

import importlib.util
import json
import uuid
import unittest
from pathlib import Path

from smartxr.live_stereo_recorder import CapturedNv12Frame, write_mono_nv12_session
from smartxr.stereo_depth import SCENE_STEREO_28, build_stereo_session_metadata
from smartxr.stereo_package import LEFT_EYE_DIR, RIGHT_EYE_DIR


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "collect_stereo_bbox_pairs.py"
TMP = ROOT / ".tmp" / "test_collect_stereo_bbox_pairs"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeFrame:
    shape = (660, 880, 3)


class FakePerson:
    def __init__(self, track_id: int, bbox, confidence: float):
        self.track_id = track_id
        self.bbox = bbox
        self.confidence = confidence
        self.tracking_status = "tracked"


class FakeTrackingResult:
    def __init__(self, people):
        self.people = people
        self.frame_index = 1
        self.frame_latency_ms = 1.5


class FakeReader:
    def __init__(self, frames):
        self.frames = list(frames)
        self.index = 0
        self.released = False

    def read_latest(self):
        if self.index >= len(self.frames):
            return True, -1, None
        item = self.frames[self.index]
        self.index += 1
        return item

    def get_stats(self):
        return {"frames_returned": self.index}

    def release(self):
        self.released = True


class FakeTracker:
    def __init__(self, people_by_call):
        self.people_by_call = list(people_by_call)
        self.calls = 0

    def process_frame(self, frame):
        people = self.people_by_call[self.calls]
        self.calls += 1
        return FakeTrackingResult(people)


def make_nv12_frame(frame_id: int, timestamp_us: int) -> CapturedNv12Frame:
    return CapturedNv12Frame(
        frame_id=frame_id,
        width=4,
        height=2,
        stride=4,
        timestamp_us=timestamp_us,
        payload=bytes([0x10]) * 12,
    )


class CollectStereoBboxPairsTests(unittest.TestCase):
    def setUp(self):
        self.tmp_path = TMP / uuid.uuid4().hex
        self.tmp_path.mkdir(parents=True, exist_ok=True)

    def test_builds_pair_record_from_highest_confidence_people(self):
        collector = load_module(TOOL, "collect_stereo_bbox_pairs")

        record = collector.build_stereo_bbox_pair_record(
            frame_id=42,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult(
                [
                    FakePerson(1, (10, 20, 110, 220), 0.40),
                    FakePerson(7, (20, 30, 120, 230), 0.91),
                ]
            ),
            right_tracking_result=FakeTrackingResult(
                [FakePerson(8, (14, 31, 114, 231), 0.87)]
            ),
            timestamp_ms=1780899000000,
        )

        self.assertEqual(record["frame_id"], 42)
        self.assertEqual(record["pair_id"], "pair-000042")
        self.assertEqual(record["person_id"], "person-7-8")
        self.assertEqual(record["left_bbox_xyxy"], [20, 30, 120, 230])
        self.assertEqual(record["right_bbox_xyxy"], [14, 31, 114, 231])
        self.assertEqual(record["confidence"], 0.87)
        self.assertEqual(record["left"]["image_width"], 880)
        self.assertEqual(record["right"]["people"][0]["track_id"], 8)

    def test_collects_only_matching_frame_ids_into_evaluator_jsonl(self):
        collector = load_module(TOOL, "collect_stereo_bbox_pairs")

        left_reader = FakeReader(
            [
                (True, 100, FakeFrame()),
                (True, 101, FakeFrame()),
                (True, 102, FakeFrame()),
            ]
        )
        right_reader = FakeReader(
            [
                (True, 100, FakeFrame()),
                (True, 102, FakeFrame()),
                (True, 103, FakeFrame()),
            ]
        )
        tracker = FakeTracker(
            [
                [FakePerson(1, (640, 240, 720, 520), 0.91)],
                [FakePerson(2, (608, 240, 688, 520), 0.90)],
                [FakePerson(3, (644, 240, 724, 520), 0.92)],
                [FakePerson(4, (612, 240, 692, 520), 0.88)],
            ]
        )

        out_path = self.tmp_path / "stereo_bbox_pairs.jsonl"
        status = collector.collect_stereo_bbox_pairs(
            left_reader=left_reader,
            right_reader=right_reader,
            tracker=tracker,
            out_path=out_path,
            max_read_attempts=3,
            stop_after_pairs=2,
            sleep_seconds=0.0,
            clock=lambda: 0.0,
        )

        records = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]

        self.assertTrue(left_reader.released)
        self.assertTrue(right_reader.released)
        self.assertEqual(status["frames_seen_left"], 3)
        self.assertEqual(status["frames_seen_right"], 3)
        self.assertEqual(status["pair_count"], 2)
        self.assertEqual(status["dropped_unpaired_left"], 1)
        self.assertEqual(status["dropped_unpaired_right"], 1)
        self.assertEqual([record["frame_id"] for record in records], [100, 102])
        self.assertEqual(records[0]["left_bbox_xyxy"], [640, 240, 720, 520])
        self.assertEqual(records[1]["right_bbox_xyxy"], [612, 240, 692, 520])

    def test_builds_pairs_from_package_with_independent_eye_trackers(self):
        collector = load_module(TOOL, "collect_stereo_bbox_pairs")
        package_dir = self.tmp_path / "package"
        left_frames = [
            make_nv12_frame(100, 100_000),
            make_nv12_frame(101, 101_000),
        ]
        right_frames = [
            make_nv12_frame(100, 100_100),
            make_nv12_frame(101, 101_100),
        ]
        write_mono_nv12_session(package_dir / LEFT_EYE_DIR, left_frames)
        write_mono_nv12_session(package_dir / RIGHT_EYE_DIR, right_frames)
        metadata = build_stereo_session_metadata(
            SCENE_STEREO_28.scaled_to(1164, 872),
            pair_count=2,
            dropped_unpaired_left=0,
            dropped_unpaired_right=0,
            max_skew_frames=1,
        )
        (package_dir / "stereo.json").write_text(json.dumps(metadata), encoding="utf-8")
        left_tracker = FakeTracker(
            [
                [FakePerson(1, (640, 240, 720, 520), 0.91)],
                [FakePerson(1, (641, 240, 721, 520), 0.92)],
            ]
        )
        right_tracker = FakeTracker(
            [
                [FakePerson(2, (608, 240, 688, 520), 0.90)],
                [FakePerson(2, (609, 240, 689, 520), 0.88)],
            ]
        )

        out_path = self.tmp_path / "from_package_independent.jsonl"
        status = collector.build_stereo_bbox_pairs_from_package(
            package_dir=package_dir,
            left_tracker=left_tracker,
            right_tracker=right_tracker,
            out_path=out_path,
            frame_decoder=lambda _frame: FakeFrame(),
        )

        records = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(status["pair_count"], 2)
        self.assertEqual(left_tracker.calls, 2)
        self.assertEqual(right_tracker.calls, 2)
        self.assertEqual(records[0]["person_id"], "person-1-2")
        self.assertEqual(records[1]["left_bbox_xyxy"], [641, 240, 721, 520])
        self.assertEqual(records[1]["right_bbox_xyxy"], [609, 240, 689, 520])

    def test_skips_pairs_without_target(self):
        collector = load_module(TOOL, "collect_stereo_bbox_pairs")

        left_reader = FakeReader([(True, 100, FakeFrame())])
        right_reader = FakeReader([(True, 100, FakeFrame())])
        tracker = FakeTracker(
            [
                [FakePerson(1, (640, 240, 720, 520), 0.91)],
                [],
            ]
        )

        out_path = self.tmp_path / "stereo_bbox_pairs.jsonl"
        status = collector.collect_stereo_bbox_pairs(
            left_reader=left_reader,
            right_reader=right_reader,
            tracker=tracker,
            out_path=out_path,
            max_read_attempts=1,
            sleep_seconds=0.0,
            clock=lambda: 0.0,
        )

        contents = out_path.read_text(encoding="utf-8")

        self.assertEqual(contents, "")
        self.assertEqual(status["pair_count"], 0)
        self.assertEqual(status["dropped_no_target_pairs"], 1)
        self.assertFalse(status["target_observed"])

    def test_builds_pairs_from_existing_stereo_record_package(self):
        collector = load_module(TOOL, "collect_stereo_bbox_pairs")
        package_dir = self.tmp_path / "package"
        left_frames = [
            make_nv12_frame(100, 100_000),
            make_nv12_frame(101, 101_000),
            make_nv12_frame(102, 102_000),
        ]
        right_frames = [
            make_nv12_frame(100, 100_100),
            make_nv12_frame(102, 102_100),
            make_nv12_frame(103, 103_100),
        ]
        write_mono_nv12_session(package_dir / LEFT_EYE_DIR, left_frames)
        write_mono_nv12_session(package_dir / RIGHT_EYE_DIR, right_frames)
        metadata = build_stereo_session_metadata(
            SCENE_STEREO_28.scaled_to(1164, 872),
            pair_count=2,
            dropped_unpaired_left=1,
            dropped_unpaired_right=1,
            max_skew_frames=1,
        )
        (package_dir / "stereo.json").write_text(json.dumps(metadata), encoding="utf-8")
        tracker = FakeTracker(
            [
                [FakePerson(1, (640, 240, 720, 520), 0.91)],
                [FakePerson(2, (608, 240, 688, 520), 0.90)],
                [FakePerson(3, (644, 240, 724, 520), 0.92)],
                [FakePerson(4, (612, 240, 692, 520), 0.88)],
            ]
        )

        out_path = self.tmp_path / "from_package.jsonl"
        status = collector.build_stereo_bbox_pairs_from_package(
            package_dir=package_dir,
            tracker=tracker,
            out_path=out_path,
            frame_decoder=lambda _frame: FakeFrame(),
        )

        records = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(status["source"], "stereo_record_package")
        self.assertEqual(status["pair_count"], 2)
        self.assertEqual(status["dropped_unpaired_left"], 1)
        self.assertEqual(status["dropped_unpaired_right"], 1)
        self.assertEqual([record["frame_id"] for record in records], [100, 102])
        self.assertEqual(records[0]["left_bbox_xyxy"], [640, 240, 720, 520])
        self.assertEqual(records[1]["right_bbox_xyxy"], [612, 240, 692, 520])


if __name__ == "__main__":
    unittest.main()
