from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "analyze_depth_stability.py"
TMP = ROOT / ".tmp" / "test_analyze_depth_stability"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )


def live_trace_row(
    sequence: int,
    depth_m: float,
    disparity_px: float,
    *,
    target_id: str = "vst_stereo-active-1",
    raw_left_track_id: int = 1,
    raw_right_track_id: int = 2,
    depth_confidence: str = "low",
    pair_capture_delta_ms: float | None = None,
    pair_receive_delta_ms: float | None = None,
) -> dict:
    row = {
        "event": "accepted",
        "sequence": sequence,
        "target_id": target_id,
        "depth_m": depth_m,
        "depth_source": "bbox_top_center_fallback",
        "depth_confidence": depth_confidence,
        "raw_left_track_id": raw_left_track_id,
        "raw_right_track_id": raw_right_track_id,
        "stereo": {
            "frame_id": 100 + sequence,
            "disparity_px": disparity_px,
            "vertical_error_px": -2.0,
            "left_anchor_px": [400.0, 200.0],
            "right_anchor_px": [400.0 - disparity_px, 202.0],
        },
    }
    if pair_capture_delta_ms is not None:
        row["pair_capture_delta_ms"] = pair_capture_delta_ms
    if pair_receive_delta_ms is not None:
        row["pair_receive_delta_ms"] = pair_receive_delta_ms
    return row


def per_frame_record(frame_id: int, near_left: list[float], near_right: list[float], far_left: list[float], far_right: list[float]) -> dict:
    return {
        "schema_version": 1,
        "pair_id": f"pair-{frame_id:06d}",
        "frame_id": frame_id,
        "bbox_candidates": [
            {
                "person_id": "left-1:right-2",
                "target_label": "rank_1_near",
                "left_bbox_xyxy": near_left,
                "right_bbox_xyxy": near_right,
                "confidence": 0.70,
                "stereo_ok": True,
                "depth_m": 0.8,
                "disparity_px": near_left[0] - near_right[0],
                "vertical_error_px": 0.0,
            },
            {
                "person_id": "left-9:right-10",
                "target_label": "rank_2_far",
                "left_bbox_xyxy": far_left,
                "right_bbox_xyxy": far_right,
                "confidence": 0.95,
                "stereo_ok": True,
                "depth_m": 1.4,
                "disparity_px": far_left[0] - far_right[0],
                "vertical_error_px": 0.0,
            },
        ],
    }


class AnalyzeDepthStabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp_path = TMP / uuid.uuid4().hex
        self.tmp_path.mkdir(parents=True, exist_ok=True)

    def test_summarizes_live_depth_trace_jumps_and_switches(self):
        analyzer = load_module(TOOL, "analyze_depth_stability")
        trace_path = self.tmp_path / "depth_estimation_trace.jsonl"
        write_jsonl(
            trace_path,
            [
                {"event": "rejected", "sequence": 0, "reason": "no_target"},
                live_trace_row(1, 0.8, 25.0, pair_capture_delta_ms=1.0, pair_receive_delta_ms=2.0),
                live_trace_row(2, 4.2, 5.0, pair_capture_delta_ms=18.0, pair_receive_delta_ms=22.0),
                live_trace_row(3, 1.0, 21.0, raw_right_track_id=4, pair_capture_delta_ms=4.0, pair_receive_delta_ms=5.0),
            ],
        )

        report = analyzer.analyze_depth_stability(
            inputs=[analyzer.AnalysisInput(name="live", path=trace_path, kind="live_trace")],
            out_dir=self.tmp_path / "out",
            top_n=2,
        )

        live = report["datasets"]["live"]
        self.assertEqual(live["input_kind"], "live_trace")
        self.assertEqual(live["accepted_count"], 3)
        self.assertEqual(live["rejected_count"], 1)
        self.assertEqual(live["depth_m"]["min"], 0.8)
        self.assertEqual(live["depth_m"]["max"], 4.2)
        self.assertEqual(live["jump_counts"]["gt_0.2m"], 2)
        self.assertEqual(live["jump_counts"]["gt_0.5m"], 2)
        self.assertEqual(live["jump_counts"]["gt_1.0m"], 2)
        self.assertEqual(live["stable_target_switch_count"], 0)
        self.assertEqual(live["raw_track_switch_count"], 1)
        self.assertEqual(live["low_confidence_ratio"], 1.0)
        self.assertEqual(live["top_depth_jumps"][0]["from"]["disparity_px"], 25.0)
        self.assertEqual(live["top_depth_jumps"][0]["to"]["disparity_px"], 5.0)
        self.assertEqual(live["temporal"]["pair_capture_delta_ms"]["max"], 18.0)
        self.assertEqual(live["temporal"]["pair_receive_delta_ms"]["p50"], 5.0)
        self.assertEqual(live["temporal"]["jump_gt_0.5m_by_capture_delta_bucket"], {"lt_5ms": 1, "gte_10ms": 1})

    def test_replays_recorded_per_frame_candidates_through_active_target_logic(self):
        analyzer = load_module(TOOL, "analyze_depth_stability")
        per_frame_path = self.tmp_path / "per_frame.jsonl"
        write_jsonl(
            per_frame_path,
            [
                per_frame_record(
                    10,
                    [640, 240, 720, 520],
                    [608, 240, 688, 520],
                    [420, 250, 500, 530],
                    [388, 250, 468, 530],
                ),
                per_frame_record(
                    11,
                    [641, 240, 721, 520],
                    [609, 240, 689, 520],
                    [421, 250, 501, 530],
                    [389, 250, 469, 530],
                ),
            ],
        )

        report = analyzer.analyze_depth_stability(
            inputs=[analyzer.AnalysisInput(name="recorded", path=per_frame_path, kind="per_frame")],
            out_dir=self.tmp_path / "out",
            top_n=5,
        )

        recorded = report["datasets"]["recorded"]
        self.assertEqual(recorded["input_kind"], "per_frame")
        self.assertEqual(recorded["accepted_count"], 2)
        self.assertEqual(recorded["candidate_count"]["max"], 2)
        self.assertTrue(recorded["active_replay"]["available"])
        self.assertEqual(recorded["active_replay"]["accepted_count"], 2)
        self.assertEqual(recorded["active_replay"]["stable_target_switch_count"], 0)
        self.assertEqual(recorded["active_replay"]["raw_track_switch_count"], 0)
        self.assertEqual(recorded["active_replay"]["switch_reasons"], {"initial": 1, "active_continuity": 1})
        self.assertEqual(recorded["active_replay"]["raw_track_pairs"], ["9-10"])

    def test_shift_replay_pairs_recorded_left_with_shifted_right_frames(self):
        analyzer = load_module(TOOL, "analyze_depth_stability")
        per_frame_path = self.tmp_path / "per_frame.jsonl"
        write_jsonl(
            per_frame_path,
            [
                per_frame_record(
                    10,
                    [640, 240, 720, 520],
                    [608, 240, 688, 520],
                    [420, 250, 500, 530],
                    [388, 250, 468, 530],
                ),
                per_frame_record(
                    11,
                    [667, 240, 747, 520],
                    [635, 240, 715, 520],
                    [420, 250, 500, 530],
                    [388, 250, 468, 530],
                ),
                per_frame_record(
                    12,
                    [640, 240, 720, 520],
                    [608, 240, 688, 520],
                    [420, 250, 500, 530],
                    [388, 250, 468, 530],
                ),
            ],
        )

        report = analyzer.analyze_depth_stability(
            inputs=[analyzer.AnalysisInput(name="recorded", path=per_frame_path, kind="per_frame")],
            out_dir=self.tmp_path / "out",
            top_n=5,
            shift_window=1,
        )

        shifts = report["datasets"]["recorded"]["shift_replay"]["shifts"]
        self.assertEqual(shifts["0"]["accepted_count"], 3)
        self.assertEqual(shifts["1"]["accepted_count"], 2)
        self.assertEqual(shifts["1"]["shift_frames"], 1)
        self.assertGreater(shifts["1"]["jump_counts"]["gt_0.5m"], shifts["0"]["jump_counts"]["gt_0.5m"])
        self.assertEqual(shifts["1"]["temporal_shift"]["right_frame_offset"], 1)

    def test_cli_writes_depth_stability_report(self):
        trace_path = self.tmp_path / "depth_estimation_trace.jsonl"
        out_dir = self.tmp_path / "out"
        write_jsonl(trace_path, [live_trace_row(1, 1.0, 20.0), live_trace_row(2, 1.3, 15.0)])

        completed = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--input",
                f"live={trace_path}",
                "--out-dir",
                str(out_dir),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )

        status = json.loads(completed.stdout)
        report_path = Path(status["depth_stability_report_json"])
        self.assertTrue(report_path.exists())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["datasets"]["live"]["accepted_count"], 2)


if __name__ == "__main__":
    unittest.main()
