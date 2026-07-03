import json
import shutil
import unittest
from pathlib import Path

from smartxr.pose_recording import (
    frame_mid_exposure_us,
    normalize_pose_row,
    sync_quality,
)

ROOT = Path(__file__).resolve().parents[1]
POSE_RECORDING_DOC = ROOT / "docs" / "pose_recording.md"
IDENTITY_WORLD_FROM_HEAD = [
    [1, 0, 0, 0],
    [0, 1, 0, 0],
    [0, 0, 1, 0],
    [0, 0, 0, 1],
]


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def pose_row(sample_index: int, pose_time_us: int) -> dict:
    return {
        "schema_version": 1,
        "timestamp_kind": "godot_sample_time",
        "pose_time_clock": "system_unix_time_usec",
        "pose_time_us": pose_time_us,
        "godot_ticks_usec": pose_time_us + 1,
        "system_unix_time_usec": pose_time_us,
        "sample_index": sample_index,
        "xr_active": True,
        "reference_space": "local_floor",
        "camera_node": "XRCamera3D",
        "world_from_head": IDENTITY_WORLD_FROM_HEAD,
        "head_position_m": [0, 0, 0],
        "head_basis_rows": [
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
        ],
        "tracking_valid": True,
    }


class PoseRecordingTests(unittest.TestCase):
    def _tmp_dir(self, name: str) -> Path:
        out_dir = ROOT / ".tmp" / "test_pose_recording" / name
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True)
        return out_dir

    def test_pose_recording_doc_covers_operator_workflow_and_v1_thresholds(self):
        doc = POSE_RECORDING_DOC.read_text(encoding="utf-8")

        self.assertIn(
            r'$dir = "C:\Users\wyxia\SmartXR_recordings\YAN-115\pose_sync_$(Get-Date -Format yyyyMMdd-HHmmss)"',
            doc,
        )
        self.assertIn(
            r'./tools/run_antman_vst_stereo_package_recorder_with_pose.ps1 -OutDir $dir -DurationSeconds 30 -SmartXROptionsPath "config\smartxr_options.json"',
            doc,
        )
        for output_name in (
            "xr_pose_trace.jsonl",
            "xr_pose_trace_status.json",
            "left/metadata.json",
            "right/metadata.json",
            "frame_pose_assoc.jsonl",
        ):
            self.assertIn(output_name, doc)
        for threshold in (
            "pose_sample_hz >= 90Hz",
            "pose_flush_drops == 0",
            "matched_pose_delta_ms p50 <= 3ms",
            "p95 <= 8ms",
            "max <= 15ms",
            "timestamp_kind = godot_sample_time or better",
        ):
            self.assertIn(threshold, doc)
        self.assertIn("timing summary", doc.lower())
        self.assertIn('$poseRows = Get-Content "$dir\\xr_pose_trace.jsonl"', doc)
        self.assertIn('$poseStatus = Get-Content "$dir\\xr_pose_trace_status.json"', doc)
        self.assertIn("$durationSeconds = ($lastPoseUs - $firstPoseUs) / 1000000.0", doc)
        self.assertIn("$poseSampleHz = ($poseRows.Count - 1) / $durationSeconds", doc)
        self.assertIn("$poseFlushDrops = [int]$poseStatus.flush_drops", doc)
        self.assertIn('"pose_sample_hz=$poseSampleHz pose_flush_drops=$poseFlushDrops"', doc)
        self.assertIn('$rows = Get-Content "$dir\\frame_pose_assoc.jsonl"', doc)
        self.assertIn('$d = @($rows | ForEach-Object { [double]$_.matched_pose_delta_ms } | Sort-Object)', doc)
        self.assertIn('$p50 = $d[[math]::Floor(($d.Count - 1) * 0.50)]', doc)
        self.assertIn('$p95 = $d[[math]::Floor(($d.Count - 1) * 0.95)]', doc)
        self.assertIn("$rows | Group-Object frame_match_time_source", doc)
        self.assertIn("$rows | Group-Object timestamp_kind", doc)
        self.assertIn("read_system_unix_time_us", doc)
        self.assertIn("exposure", doc)
        self.assertIn("V1", doc)
        self.assertIn("V2", doc)
        self.assertIn("native OpenXR/QPC timestamp", doc)
        self.assertIn("old recordings", doc.lower())
        self.assertIn("cannot reconstruct true historical head pose", doc)

    def test_merge_pose_trace_prefers_read_system_time_midpoint(self):
        from tools.merge_stereo_pose_trace import merge_pose_trace

        root = self._tmp_dir("merge_prefers_read_system_time_midpoint")
        try:
            package_dir = root / "package"
            write_json(
                package_dir / "left" / "metadata.json",
                {
                    "frame_ids": [10],
                    "timestamps_us": [1_000_000],
                    "read_system_unix_time_us": [5_000_000],
                },
            )
            write_json(
                package_dir / "right" / "metadata.json",
                {
                    "frame_ids": [10],
                    "timestamps_us": [1_000_400],
                    "read_system_unix_time_us": [5_000_200],
                },
            )
            pose_trace = root / "pose_trace.jsonl"
            write_jsonl(
                pose_trace,
                [
                    pose_row(0, 4_999_000),
                    pose_row(1, 5_000_105),
                ],
            )

            summary = merge_pose_trace(package_dir, pose_trace, root / "frame_pose_assoc.jsonl")

            self.assertEqual(summary, {"rows_written": 1})
            rows = read_jsonl(root / "frame_pose_assoc.jsonl")
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["schema_version"], 1)
            self.assertEqual(
                normalize_pose_row(pose_row(99, 5_000_100))["pose_time_clock"],
                "system_unix_time_usec",
            )
            self.assertEqual(row["pair_id"], "pair-000010")
            self.assertEqual(row["frame_id"], 10)
            self.assertEqual(row["left_exposure_us"], 1_000_000)
            self.assertEqual(row["right_exposure_us"], 1_000_400)
            self.assertEqual(row["frame_mid_exposure_us"], 1_000_200)
            self.assertEqual(row["frame_match_time_source"], "read_system_unix_time_us_midpoint")
            self.assertEqual(row["frame_match_time_us"], 5_000_100)
            self.assertEqual(row["matched_pose_sample_index"], 1)
            self.assertEqual(row["matched_pose_time_us"], 5_000_105)
            self.assertEqual(row["matched_pose_delta_ms"], 0.005)
            self.assertEqual(row["timestamp_kind"], "godot_sample_time")
            self.assertEqual(row["pose_time_clock"], "system_unix_time_usec")
            self.assertEqual(row["sync_quality"], "good")
            self.assertEqual(row["world_from_head"], IDENTITY_WORLD_FROM_HEAD)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_merge_pose_trace_falls_back_to_exposure_midpoint_for_legacy_metadata(self):
        from tools.merge_stereo_pose_trace import merge_pose_trace

        root = self._tmp_dir("merge_falls_back_to_exposure_midpoint")
        try:
            package_dir = root / "package"
            write_json(
                package_dir / "left" / "metadata.json",
                {"frame_ids": [7], "timestamps_us": [2_000_000]},
            )
            write_json(
                package_dir / "right" / "metadata.json",
                {"frame_ids": [7], "timestamps_us": [2_000_800]},
            )
            pose_trace = root / "pose_trace.jsonl"
            write_jsonl(
                pose_trace,
                [
                    pose_row(2, 2_000_390),
                    pose_row(3, 2_100_000),
                ],
            )

            summary = merge_pose_trace(package_dir, pose_trace, root / "frame_pose_assoc.jsonl")

            self.assertEqual(summary, {"rows_written": 1})
            rows = read_jsonl(root / "frame_pose_assoc.jsonl")
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["pair_id"], "pair-000007")
            self.assertEqual(row["frame_id"], 7)
            self.assertEqual(row["left_exposure_us"], 2_000_000)
            self.assertEqual(row["right_exposure_us"], 2_000_800)
            self.assertEqual(row["frame_mid_exposure_us"], 2_000_400)
            self.assertEqual(row["frame_match_time_source"], "exposure_midpoint")
            self.assertEqual(row["frame_match_time_us"], 2_000_400)
            self.assertEqual(row["matched_pose_sample_index"], 2)
            self.assertEqual(row["matched_pose_time_us"], 2_000_390)
            self.assertEqual(row["matched_pose_delta_ms"], 0.01)
            self.assertEqual(row["timestamp_kind"], "godot_sample_time")
            self.assertEqual(row["sync_quality"], "good")
            self.assertEqual(row["world_from_head"], IDENTITY_WORLD_FROM_HEAD)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_merge_pose_trace_rejects_pose_rows_without_system_unix_time_clock(self):
        from tools.merge_stereo_pose_trace import merge_pose_trace

        root = self._tmp_dir("merge_rejects_pose_clock_mismatch")
        try:
            package_dir = root / "package"
            write_json(
                package_dir / "left" / "metadata.json",
                {"frame_ids": [1], "timestamps_us": [1_000_000]},
            )
            write_json(
                package_dir / "right" / "metadata.json",
                {"frame_ids": [1], "timestamps_us": [1_000_200]},
            )
            pose_trace = root / "pose_trace.jsonl"
            write_jsonl(
                pose_trace,
                [dict(pose_row(0, 1_000_100), pose_time_clock="godot_ticks")],
            )

            with self.assertRaisesRegex(ValueError, "pose_time_clock.*system_unix_time_usec"):
                merge_pose_trace(package_dir, pose_trace, root / "frame_pose_assoc.jsonl")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_merge_pose_trace_rejects_pose_rows_without_v1_schema(self):
        from tools.merge_stereo_pose_trace import merge_pose_trace

        root = self._tmp_dir("merge_rejects_pose_schema_mismatch")
        try:
            package_dir = root / "package"
            write_json(
                package_dir / "left" / "metadata.json",
                {"frame_ids": [1], "timestamps_us": [1_000_000]},
            )
            write_json(
                package_dir / "right" / "metadata.json",
                {"frame_ids": [1], "timestamps_us": [1_000_200]},
            )
            pose_trace = root / "pose_trace.jsonl"
            write_jsonl(
                pose_trace,
                [dict(pose_row(0, 1_000_100), schema_version=2)],
            )

            with self.assertRaisesRegex(ValueError, "schema_version.*1"):
                merge_pose_trace(package_dir, pose_trace, root / "frame_pose_assoc.jsonl")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_merge_pose_trace_rejects_pose_rows_without_godot_sample_timestamp_kind(self):
        from tools.merge_stereo_pose_trace import merge_pose_trace

        root = self._tmp_dir("merge_rejects_timestamp_kind_mismatch")
        try:
            package_dir = root / "package"
            write_json(
                package_dir / "left" / "metadata.json",
                {"frame_ids": [1], "timestamps_us": [1_000_000]},
            )
            write_json(
                package_dir / "right" / "metadata.json",
                {"frame_ids": [1], "timestamps_us": [1_000_200]},
            )
            pose_trace = root / "pose_trace.jsonl"
            write_jsonl(
                pose_trace,
                [dict(pose_row(0, 1_000_100), timestamp_kind="system_unix_time_us")],
            )

            with self.assertRaisesRegex(ValueError, "timestamp_kind.*godot_sample_time"):
                merge_pose_trace(package_dir, pose_trace, root / "frame_pose_assoc.jsonl")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_merge_pose_trace_tie_selects_earlier_pose_sample(self):
        from tools.merge_stereo_pose_trace import merge_pose_trace

        root = self._tmp_dir("merge_tie_selects_earlier_pose")
        try:
            package_dir = root / "package"
            write_json(
                package_dir / "left" / "metadata.json",
                {"frame_ids": [2], "timestamps_us": [1_000_000]},
            )
            write_json(
                package_dir / "right" / "metadata.json",
                {"frame_ids": [2], "timestamps_us": [1_000_200]},
            )
            pose_trace = root / "pose_trace.jsonl"
            write_jsonl(
                pose_trace,
                [
                    pose_row(4, 1_000_090),
                    pose_row(5, 1_000_110),
                ],
            )

            merge_pose_trace(package_dir, pose_trace, root / "frame_pose_assoc.jsonl")

            rows = read_jsonl(root / "frame_pose_assoc.jsonl")
            self.assertEqual(rows[0]["frame_match_time_us"], 1_000_100)
            self.assertEqual(rows[0]["matched_pose_sample_index"], 4)
            self.assertEqual(rows[0]["matched_pose_time_us"], 1_000_090)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_merge_pose_trace_nearest_lookup_uses_sorted_index(self):
        import inspect
        import tools.merge_stereo_pose_trace as merge_tool

        self.assertIn("bisect_left", inspect.getsource(merge_tool._nearest_pose))

    def test_normalize_pose_row_returns_predictable_types(self):
        row = {
            "schema_version": "1",
            "timestamp_kind": 123,
            "pose_time_clock": "godot_ticks",
            "pose_time_us": "1000001",
            "godot_ticks_usec": 1000002.0,
            "system_unix_time_usec": "1760000000000000",
            "sample_index": "42",
            "xr_active": "true",
            "reference_space": 77,
            "camera_node": "XRCamera3D",
            "world_from_head": [
                ["1", 0, 0, "0.1"],
                [0, "1", 0, "0.2"],
                [0, 0, "1", "0.3"],
                [0, 0, 0, "1"],
            ],
            "head_position_m": ["0.1", 0.2, 0],
            "head_basis_rows": [
                ["1", 0, 0],
                [0, "1", 0],
                [0, 0, "1"],
            ],
            "tracking_valid": 1,
            "flush_drops": "2",
        }

        normalized = normalize_pose_row(row)

        self.assertEqual(normalized["schema_version"], 1)
        self.assertIsInstance(normalized["schema_version"], int)
        self.assertEqual(normalized["timestamp_kind"], "123")
        self.assertEqual(normalized["pose_time_clock"], "godot_ticks")
        self.assertEqual(normalized["pose_time_us"], 1000001)
        self.assertEqual(normalized["godot_ticks_usec"], 1000002)
        self.assertEqual(normalized["system_unix_time_usec"], 1760000000000000)
        self.assertEqual(normalized["sample_index"], 42)
        self.assertIs(normalized["xr_active"], True)
        self.assertEqual(normalized["reference_space"], "77")
        self.assertEqual(normalized["camera_node"], "XRCamera3D")
        self.assertEqual(
            normalized["world_from_head"],
            [
                [1.0, 0.0, 0.0, 0.1],
                [0.0, 1.0, 0.0, 0.2],
                [0.0, 0.0, 1.0, 0.3],
                [0.0, 0.0, 0.0, 1.0],
            ],
        )
        self.assertEqual(normalized["head_position_m"], [0.1, 0.2, 0.0])
        self.assertEqual(
            normalized["head_basis_rows"],
            [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ],
        )
        self.assertIs(normalized["tracking_valid"], True)
        self.assertEqual(normalized["flush_drops"], 2)

    def test_normalize_pose_row_rejects_invalid_pose_shapes(self):
        valid = {
            "schema_version": 1,
            "timestamp_kind": "capture",
            "pose_time_clock": "godot_ticks",
            "pose_time_us": 100,
            "godot_ticks_usec": 100,
            "system_unix_time_usec": 200,
            "sample_index": 0,
            "xr_active": True,
            "reference_space": "local_floor",
            "camera_node": "XRCamera3D",
            "world_from_head": [
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ],
            "head_position_m": [0, 0, 0],
            "head_basis_rows": [
                [1, 0, 0],
                [0, 1, 0],
                [0, 0, 1],
            ],
            "tracking_valid": True,
        }

        bad_matrix = dict(valid, world_from_head=[[1, 0, 0, 0]])
        with self.assertRaisesRegex(ValueError, "world_from_head must be a 4x4"):
            normalize_pose_row(bad_matrix)

        bad_position = dict(valid, head_position_m=[0, 0])
        with self.assertRaisesRegex(ValueError, "head_position_m must be a vec3"):
            normalize_pose_row(bad_position)

    def test_normalize_pose_row_rejects_non_finite_pose_values(self):
        valid = {
            "schema_version": 1,
            "timestamp_kind": "capture",
            "pose_time_clock": "godot_ticks",
            "pose_time_us": 100,
            "godot_ticks_usec": 100,
            "system_unix_time_usec": 200,
            "sample_index": 0,
            "xr_active": True,
            "reference_space": "local_floor",
            "camera_node": "XRCamera3D",
            "world_from_head": [
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ],
            "head_position_m": [0, 0, 0],
            "head_basis_rows": [
                [1, 0, 0],
                [0, 1, 0],
                [0, 0, 1],
            ],
            "tracking_valid": True,
        }

        bad_world = dict(
            valid,
            world_from_head=[
                [1, 0, 0, 0],
                [0, float("nan"), 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ],
        )
        with self.assertRaisesRegex(ValueError, "world_from_head.*finite"):
            normalize_pose_row(bad_world)

        bad_position = dict(valid, head_position_m=[0, float("inf"), 0])
        with self.assertRaisesRegex(ValueError, "head_position_m.*finite"):
            normalize_pose_row(bad_position)

        bad_basis = dict(
            valid,
            head_basis_rows=[
                [1, 0, 0],
                [0, 1, "-inf"],
                [0, 0, 1],
            ],
        )
        with self.assertRaisesRegex(ValueError, "head_basis_rows.*finite"):
            normalize_pose_row(bad_basis)

    def test_normalize_pose_row_accepts_missing_head_basis_rows(self):
        row = {
            "schema_version": "1",
            "timestamp_kind": "capture",
            "pose_time_clock": "godot_ticks",
            "pose_time_us": "100",
            "godot_ticks_usec": "101",
            "system_unix_time_usec": "200",
            "sample_index": "3",
            "xr_active": "false",
            "reference_space": "local_floor",
            "camera_node": "XRCamera3D",
            "world_from_head": [
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ],
            "head_position_m": ["0.5", "1.5", "2.5"],
            "tracking_valid": "true",
        }

        normalized = normalize_pose_row(row)

        self.assertEqual(normalized["schema_version"], 1)
        self.assertEqual(normalized["pose_time_us"], 100)
        self.assertEqual(normalized["godot_ticks_usec"], 101)
        self.assertEqual(normalized["system_unix_time_usec"], 200)
        self.assertEqual(normalized["sample_index"], 3)
        self.assertIs(normalized["xr_active"], False)
        self.assertIs(normalized["tracking_valid"], True)
        self.assertEqual(
            normalized["world_from_head"],
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
        )
        self.assertEqual(normalized["head_position_m"], [0.5, 1.5, 2.5])
        self.assertNotIn("head_basis_rows", normalized)

    def test_frame_mid_exposure_us_uses_timestamp_midpoint(self):
        self.assertEqual(
            frame_mid_exposure_us({"timestamp_us": "1000"}, {"timestamp_us": 1020}),
            1010,
        )

    def test_frame_mid_exposure_us_falls_back_to_exposure_us(self):
        self.assertEqual(
            frame_mid_exposure_us({"exposure_us": 5000}, {"exposure_us": "5010"}),
            5005,
        )

    def test_frame_mid_exposure_us_rejects_missing_or_non_numeric_inputs(self):
        with self.assertRaisesRegex(ValueError, "timestamp_us or exposure_us"):
            frame_mid_exposure_us({"timestamp_us": 1000}, {})
        with self.assertRaisesRegex(ValueError, "must be numeric"):
            frame_mid_exposure_us({"timestamp_us": True}, {"timestamp_us": 1000})

    def test_sync_quality_thresholds(self):
        self.assertEqual(sync_quality(8), "good")
        self.assertEqual(sync_quality(8.1), "usable")
        self.assertEqual(sync_quality(15), "usable")
        self.assertEqual(sync_quality(15.1), "bad")

    def test_sync_quality_rejects_invalid_deltas(self):
        for delta_ms in (-0.1, float("nan"), float("inf"), "8"):
            with self.subTest(delta_ms=delta_ms):
                with self.assertRaisesRegex(ValueError, "delta_ms"):
                    sync_quality(delta_ms)


if __name__ == "__main__":
    unittest.main()
