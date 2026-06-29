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

    def test_active_target_stabilizer_keeps_current_pair_over_one_frame_distractor(self):
        collector = load_module(TOOL, "collect_stereo_bbox_pairs")
        stabilizer = collector.StereoActiveTargetStabilizer(
            switch_confirm_frames=2,
            switch_score_margin=0.05,
            hold_frames=6,
        )

        first = collector.build_stereo_bbox_pair_record(
            frame_id=10,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult([FakePerson(1, (640, 240, 720, 520), 0.70)]),
            right_tracking_result=FakeTrackingResult([FakePerson(2, (608, 240, 688, 520), 0.70)]),
            timestamp_ms=1780899000000,
            target_stabilizer=stabilizer,
        )
        second = collector.build_stereo_bbox_pair_record(
            frame_id=11,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult(
                [
                    FakePerson(1, (641, 240, 721, 520), 0.62),
                    FakePerson(9, (420, 250, 500, 530), 0.96),
                ]
            ),
            right_tracking_result=FakeTrackingResult(
                [
                    FakePerson(2, (609, 240, 689, 520), 0.62),
                    FakePerson(10, (388, 250, 468, 530), 0.96),
                ]
            ),
            timestamp_ms=1780899000033,
            target_stabilizer=stabilizer,
        )

        self.assertEqual(first["person_id"], "active-1")
        self.assertEqual(first["selection"]["active_state"], "TRACKING_STEREO")
        self.assertTrue(first["selection"]["left_active_seen"])
        self.assertTrue(first["selection"]["right_active_seen"])
        self.assertEqual(second["person_id"], "active-1")
        self.assertEqual(second["left_bbox_xyxy"], [641, 240, 721, 520])
        self.assertEqual(second["right_bbox_xyxy"], [609, 240, 689, 520])
        self.assertEqual(second["selection"]["candidate_count"], 4)
        self.assertEqual(second["selection"]["raw_left_track_id"], 1)
        self.assertEqual(second["selection"]["raw_right_track_id"], 2)
        self.assertEqual(second["selection"]["switch_count"], 0)
        self.assertEqual(second["selection"]["switch_reason"], "active_continuity")
        self.assertEqual(second["selection"]["active_age_frames"], 2)
        self.assertEqual(second["selection"]["active_state"], "TRACKING_STEREO")
        self.assertTrue(second["selection"]["left_active_seen"])
        self.assertTrue(second["selection"]["right_active_seen"])
        self.assertEqual(second["selection"]["mono_missing_frames"], 0)
        self.assertEqual(second["selection"]["both_missing_frames"], 0)
        self.assertTrue(second["selection"]["depth_update_allowed"])
        self.assertGreater(second["selection"]["estimated_depth_m"], 0.0)
        self.assertFalse(second["selection"]["held_last_pose"])

    def test_active_target_stabilizer_holds_last_pose_for_short_missing_window(self):
        collector = load_module(TOOL, "collect_stereo_bbox_pairs")
        stabilizer = collector.StereoActiveTargetStabilizer(hold_frames=6)

        first = collector.build_stereo_bbox_pair_record(
            frame_id=20,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult([FakePerson(1, (640, 240, 720, 520), 0.80)]),
            right_tracking_result=FakeTrackingResult([FakePerson(2, (608, 240, 688, 520), 0.80)]),
            timestamp_ms=1780899000000,
            target_stabilizer=stabilizer,
        )
        held = collector.build_stereo_bbox_pair_record(
            frame_id=21,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult([]),
            right_tracking_result=FakeTrackingResult([]),
            timestamp_ms=1780899000033,
            target_stabilizer=stabilizer,
        )

        self.assertEqual(held["person_id"], "active-1")
        self.assertEqual(held["left_bbox_xyxy"], first["left_bbox_xyxy"])
        self.assertEqual(held["right_bbox_xyxy"], first["right_bbox_xyxy"])
        self.assertEqual(held["selection"]["switch_reason"], "held_missing")
        self.assertTrue(held["selection"]["held_last_pose"])
        self.assertEqual(held["selection"]["active_age_frames"], 1)
        self.assertEqual(held["selection"]["active_state"], "TEMP_LOST_BOTH")
        self.assertFalse(held["selection"]["left_active_seen"])
        self.assertFalse(held["selection"]["right_active_seen"])
        self.assertEqual(held["selection"]["mono_missing_frames"], 0)
        self.assertEqual(held["selection"]["both_missing_frames"], 1)
        self.assertEqual(held["selection"]["held_reason"], "both_eye_temp_lost")
        self.assertFalse(held["selection"]["depth_update_allowed"])

    def test_active_target_stabilizer_classifies_mono_missing_and_gates_depth_update(self):
        collector = load_module(TOOL, "collect_stereo_bbox_pairs")
        stabilizer = collector.StereoActiveTargetStabilizer(hold_frames=6)

        first = collector.build_stereo_bbox_pair_record(
            frame_id=22,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult([FakePerson(1, (640, 240, 720, 520), 0.80)]),
            right_tracking_result=FakeTrackingResult([FakePerson(2, (608, 240, 688, 520), 0.80)]),
            timestamp_ms=1780899000000,
            target_stabilizer=stabilizer,
        )
        mono = collector.build_stereo_bbox_pair_record(
            frame_id=23,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult([FakePerson(1, (642, 240, 722, 520), 0.76)]),
            right_tracking_result=FakeTrackingResult([]),
            timestamp_ms=1780899000033,
            target_stabilizer=stabilizer,
        )

        self.assertEqual(mono["person_id"], "active-1")
        self.assertEqual(mono["left_bbox_xyxy"], first["left_bbox_xyxy"])
        self.assertEqual(mono["right_bbox_xyxy"], first["right_bbox_xyxy"])
        self.assertEqual(mono["selection"]["switch_reason"], "held_missing")
        self.assertTrue(mono["selection"]["held_last_pose"])
        self.assertEqual(mono["selection"]["active_state"], "TRACKING_MONO_LEFT")
        self.assertTrue(mono["selection"]["left_active_seen"])
        self.assertFalse(mono["selection"]["right_active_seen"])
        self.assertEqual(mono["selection"]["mono_missing_frames"], 1)
        self.assertEqual(mono["selection"]["both_missing_frames"], 0)
        self.assertEqual(mono["selection"]["held_reason"], "mono_eye_missing")
        self.assertFalse(mono["selection"]["depth_update_allowed"])

    def test_active_target_stabilizer_uses_longer_grace_for_mono_missing_than_both_missing(self):
        collector = load_module(TOOL, "collect_stereo_bbox_pairs")
        stabilizer = collector.StereoActiveTargetStabilizer(hold_frames=2, mono_hold_frames=4)

        first = collector.build_stereo_bbox_pair_record(
            frame_id=24,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult([FakePerson(1, (640, 240, 720, 520), 0.80)]),
            right_tracking_result=FakeTrackingResult([FakePerson(2, (608, 240, 688, 520), 0.80)]),
            timestamp_ms=1780899000000,
            target_stabilizer=stabilizer,
        )
        self.assertIsNotNone(first)

        third_mono_hold = None
        for frame_id in (25, 26, 27):
            third_mono_hold = collector.build_stereo_bbox_pair_record(
                frame_id=frame_id,
                left_frame=FakeFrame(),
                right_frame=FakeFrame(),
                left_tracking_result=FakeTrackingResult([FakePerson(1, (642, 240, 722, 520), 0.76)]),
                right_tracking_result=FakeTrackingResult([]),
                timestamp_ms=1780899000000 + (frame_id - 24) * 33,
                target_stabilizer=stabilizer,
            )

        self.assertIsNotNone(third_mono_hold)
        self.assertEqual(third_mono_hold["selection"]["switch_reason"], "held_missing")
        self.assertEqual(third_mono_hold["selection"]["active_state"], "TRACKING_MONO_LEFT")
        self.assertEqual(third_mono_hold["selection"]["mono_missing_frames"], 3)
        self.assertEqual(third_mono_hold["selection"]["held_reason"], "mono_eye_missing")
        self.assertFalse(third_mono_hold["selection"]["depth_update_allowed"])

        both_stabilizer = collector.StereoActiveTargetStabilizer(hold_frames=2, mono_hold_frames=4)
        collector.build_stereo_bbox_pair_record(
            frame_id=30,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult([FakePerson(1, (640, 240, 720, 520), 0.80)]),
            right_tracking_result=FakeTrackingResult([FakePerson(2, (608, 240, 688, 520), 0.80)]),
            timestamp_ms=1780899000000,
            target_stabilizer=both_stabilizer,
        )
        for frame_id in (31, 32):
            held = collector.build_stereo_bbox_pair_record(
                frame_id=frame_id,
                left_frame=FakeFrame(),
                right_frame=FakeFrame(),
                left_tracking_result=FakeTrackingResult([]),
                right_tracking_result=FakeTrackingResult([]),
                timestamp_ms=1780899000000 + (frame_id - 30) * 33,
                target_stabilizer=both_stabilizer,
            )
            self.assertIsNotNone(held)
            self.assertEqual(held["selection"]["held_reason"], "both_eye_temp_lost")

        released = collector.build_stereo_bbox_pair_record(
            frame_id=33,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult([]),
            right_tracking_result=FakeTrackingResult([]),
            timestamp_ms=1780899000099,
            target_stabilizer=both_stabilizer,
        )
        self.assertIsNone(released)

    def test_active_target_stabilizer_gates_large_fresh_depth_jump_for_stable_target(self):
        collector = load_module(TOOL, "collect_stereo_bbox_pairs")
        stabilizer = collector.StereoActiveTargetStabilizer(max_depth_jump_m=0.10)

        first = collector.build_stereo_bbox_pair_record(
            frame_id=28,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult([FakePerson(1, (640, 240, 720, 520), 0.80)]),
            right_tracking_result=FakeTrackingResult([FakePerson(2, (608, 240, 688, 520), 0.80)]),
            timestamp_ms=1780899000000,
            target_stabilizer=stabilizer,
        )
        jumped = collector.build_stereo_bbox_pair_record(
            frame_id=29,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult([FakePerson(1, (640, 240, 720, 520), 0.80)]),
            right_tracking_result=FakeTrackingResult([FakePerson(2, (625, 240, 705, 520), 0.80)]),
            timestamp_ms=1780899000033,
            target_stabilizer=stabilizer,
        )

        self.assertFalse(jumped["selection"]["held_last_pose"])
        self.assertFalse(jumped["selection"]["depth_update_allowed"])
        self.assertEqual(jumped["selection"]["depth_gate_reason"], "depth_jump")
        self.assertEqual(jumped["selection"]["last_good_depth"], first["selection"]["last_good_depth"])
        self.assertGreater(
            abs(jumped["selection"]["estimated_depth_m"] - first["selection"]["last_good_depth"]),
            0.10,
        )

    def test_active_target_stabilizer_switches_after_sustained_better_candidate(self):
        collector = load_module(TOOL, "collect_stereo_bbox_pairs")
        stabilizer = collector.StereoActiveTargetStabilizer(
            switch_confirm_frames=2,
            switch_score_margin=0.05,
            hold_frames=6,
        )

        collector.build_stereo_bbox_pair_record(
            frame_id=30,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult([FakePerson(1, (640, 240, 720, 520), 0.70)]),
            right_tracking_result=FakeTrackingResult([FakePerson(2, (608, 240, 688, 520), 0.70)]),
            timestamp_ms=1780899000000,
            target_stabilizer=stabilizer,
        )
        kept = collector.build_stereo_bbox_pair_record(
            frame_id=31,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult(
                [FakePerson(1, (641, 240, 721, 520), 0.62), FakePerson(9, (420, 250, 500, 530), 0.96)]
            ),
            right_tracking_result=FakeTrackingResult(
                [FakePerson(2, (609, 240, 689, 520), 0.62), FakePerson(10, (388, 250, 468, 530), 0.96)]
            ),
            timestamp_ms=1780899000033,
            target_stabilizer=stabilizer,
        )
        switched = collector.build_stereo_bbox_pair_record(
            frame_id=32,
            left_frame=FakeFrame(),
            right_frame=FakeFrame(),
            left_tracking_result=FakeTrackingResult(
                [FakePerson(1, (642, 240, 722, 520), 0.61), FakePerson(9, (421, 250, 501, 530), 0.96)]
            ),
            right_tracking_result=FakeTrackingResult(
                [FakePerson(2, (610, 240, 690, 520), 0.61), FakePerson(10, (389, 250, 469, 530), 0.96)]
            ),
            timestamp_ms=1780899000066,
            target_stabilizer=stabilizer,
        )

        self.assertEqual(kept["selection"]["raw_left_track_id"], 1)
        self.assertEqual(switched["person_id"], "active-1")
        self.assertEqual(switched["selection"]["raw_left_track_id"], 9)
        self.assertEqual(switched["selection"]["raw_right_track_id"], 10)
        self.assertEqual(switched["selection"]["switch_reason"], "switch_confirmed")
        self.assertEqual(switched["selection"]["switch_count"], 1)
        self.assertEqual(switched["selection"]["active_age_frames"], 1)
        self.assertEqual(kept["selection"]["switch_block_reason"], "pending_switch_confirmation")
        self.assertEqual(switched["selection"]["switch_block_reason"], None)

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
