from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "analyze_live_run_diagnostics.py"
RUNNER = ROOT / "tools" / "run_windows_pcmr_stereo_proxy_targets_live.ps1"
TMP = ROOT / ".tmp" / "test_live_run_diagnostics"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )


def accepted_row(
    sequence: int,
    depth_m: float,
    *,
    left_frame_id: int | None = None,
    right_frame_id: int | None = None,
    capture_us: int | None = None,
    raw_left_track_id: int = 1,
    raw_right_track_id: int = 2,
    switch_reason: str = "active_continuity",
    held_last_pose: bool = False,
    clients: dict | None = None,
) -> dict:
    frame_id = sequence if left_frame_id is None else left_frame_id
    right_id = frame_id if right_frame_id is None else right_frame_id
    timestamp = 1_000_000 + sequence * 22_222 if capture_us is None else capture_us
    return {
        "event": "accepted",
        "sequence": sequence,
        "target_id": "vst_stereo-active-1",
        "active_target_id": "active-1",
        "depth_m": depth_m,
        "depth_source": "bbox_top_center_fallback",
        "depth_confidence": "low",
        "raw_left_track_id": raw_left_track_id,
        "raw_right_track_id": raw_right_track_id,
        "switch_reason": switch_reason,
        "held_last_pose": held_last_pose,
        "active_age_frames": sequence + 1,
        "candidate_count": 1,
        "selected_score": 0.8,
        "left_frame_id": frame_id,
        "right_frame_id": right_id,
        "transform": {"position": [0.1 * sequence, -0.01, -depth_m]},
        "temporal": {
            "left_frame_id": frame_id,
            "right_frame_id": right_id,
            "left_capture_timestamp_us": timestamp,
            "right_capture_timestamp_us": timestamp + 120,
            "left_capture_timestamp_source": "frame_exposure_us",
            "right_capture_timestamp_source": "frame_exposure_us",
            "pair_capture_delta_ms": 0.12,
            "pair_receive_delta_ms": 0.0,
        },
        "sync": {
            "pairing_strategy": "capture_timestamp",
            "temporal_mismatch_count": 0,
            "dropped_left_frames": 0,
            "dropped_right_frames": 0,
        },
        "clients": clients
        or {
            "active_client_count": 1,
            "active_clients": ["client-2=monitor@127.0.0.1:4386"],
            "last_disconnect": {"client_id": "client-1", "label": "godot", "reason": "client_closed"},
        },
    }


class LiveRunDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp_path = TMP / uuid.uuid4().hex
        self.tmp_path.mkdir(parents=True, exist_ok=True)

    def test_generates_run_level_diagnostics_with_verdicts_and_segments(self):
        analyzer = load_module(TOOL, "analyze_live_run_diagnostics")
        trace_path = self.tmp_path / "depth_estimation_trace.jsonl"
        raw_status_path = self.tmp_path / "raw_status.json"
        pcmr_status_path = self.tmp_path / "pcmr_status.json"
        sender_log_path = self.tmp_path / "sender.log"
        output_path = self.tmp_path / "live_run_diagnostics.json"

        rows = [
            accepted_row(0, 0.60, capture_us=1_000_000, raw_left_track_id=1, raw_right_track_id=2),
            accepted_row(1, 0.64, capture_us=1_100_000, raw_left_track_id=1, raw_right_track_id=2),
            accepted_row(2, 1.02, capture_us=1_200_000, raw_left_track_id=3, raw_right_track_id=4),
            accepted_row(3, 0.80, capture_us=1_300_000, raw_left_track_id=3, raw_right_track_id=4, held_last_pose=True, switch_reason="held_missing"),
            accepted_row(4, 0.61, capture_us=1_400_000, raw_left_track_id=3, raw_right_track_id=4, held_last_pose=True, switch_reason="held_missing"),
            {
                "event": "rejected",
                "sequence": 5,
                "reason": "no_target",
                "temporal": {
                    "left_frame_id": 5,
                    "right_frame_id": 5,
                    "left_capture_timestamp_us": 1_500_000,
                    "right_capture_timestamp_us": 1_500_200,
                    "pair_capture_delta_ms": 0.2,
                },
                "clients": {"active_client_count": 1},
            },
            {
                "event": "rejected",
                "sequence": 6,
                "reason": "temporal_mismatch",
                "sync": {"pairing_strategy": "capture_timestamp", "temporal_mismatch_count": 1},
                "temporal": {"left_frame_id": 6, "right_frame_id": 8, "pair_capture_delta_ms": 12.0},
            },
        ]
        write_jsonl(trace_path, rows)
        write_json(
            raw_status_path,
            {
                "ok": True,
                "packets": 10,
                "parsed": 10,
                "target_ids": ["vst_stereo-active-1"],
                "realtime": {
                    "expected_source_hz": 45.0,
                    "observed_packet_hz": 11.25,
                    "mean_interval_ms": 88.8,
                    "late_interval_count": 9,
                    "sequence_gap_count": 1,
                    "packet_drop_count": 2,
                },
                "depth_confidences": {"low": 10},
                "depth_sources": {"bbox_top_center_fallback": 10},
            },
        )
        write_json(
            pcmr_status_path,
            {
                "last_command": "proxy_live",
                "packets": 612,
                "live": 612,
                "sequence": 617,
                "card_apply_count": 4398,
                "card_target_id": "vst_stereo-active-1",
                "card_attach_target_id": "vst_stereo-active-1",
                "proxy_world_position": "0.29 0.28 -0.82",
                "card_node_position": "0.64 0.53 -0.83",
                "card_resolved_position": "0.64 0.53 -0.83",
            },
        )
        sender_log_path.write_text(
            "\n".join(
                [
                    "client connected: id=client-1 label=godot address=127.0.0.1:4381 request=GET /proxy_targets HTTP/1.1",
                    "client text: {\"type\":\"subscribe\",\"stream\":\"proxy_targets\",\"client_label\":\"monitor\"}",
                    "client disconnected: id=client-1 label=godot address=127.0.0.1:4381 reason=client_closed",
                    "client connected: id=client-2 label=monitor address=127.0.0.1:4386 request=GET /proxy_targets HTTP/1.1",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        report = analyzer.analyze_live_run_diagnostics(
            depth_trace_path=trace_path,
            raw_status_path=raw_status_path,
            pcmr_status_path=pcmr_status_path,
            sender_log_path=sender_log_path,
            output_path=output_path,
            top_n=3,
            context_radius=2,
        )

        self.assertTrue(output_path.exists())
        self.assertEqual(report["trace"]["accepted_count"], 5)
        self.assertEqual(report["trace"]["rejected_count"], 2)
        self.assertIn("TIMESTAMP_SYNC_OK", report["verdicts"])
        self.assertIn("PUBLISH_RATE_LOW", report["verdicts"])
        self.assertIn("LOW_CONFIDENCE_DEPTH_ONLY", report["verdicts"])
        self.assertIn("HELD_POSE_TOO_MUCH", report["verdicts"])
        self.assertIn("RAW_PAIR_SWITCHING", report["verdicts"])
        self.assertIn("GODOT_CLIENT_DISCONNECTED_OR_LABEL_AMBIGUOUS", report["verdicts"])
        self.assertEqual(report["timeline"]["accepted_hz"], 12.5)
        self.assertEqual(report["timeline"]["raw_stream"]["observed_packet_hz"], 11.25)
        self.assertEqual(report["timeline"]["packet_gap"]["raw_sequence_gap_count"], 1)
        self.assertEqual(report["timeline"]["godot_card"]["packets"], 612)
        self.assertEqual(report["timeline"]["godot_card"]["card_apply_count"], 4398)
        self.assertGreaterEqual(len(report["segments"]["depth_jump"]), 1)
        self.assertEqual(report["segments"]["depth_jump"][0]["sequence"], 2)
        self.assertEqual(len(report["segments"]["depth_jump"][0]["context"]), 5)
        context_item = report["segments"]["depth_jump"][0]["context"][2]
        self.assertEqual(context_item["sequence"], 2)
        self.assertEqual(context_item["left_frame_id"], 2)
        self.assertEqual(context_item["left_capture_timestamp_us"], 1_200_000)
        self.assertEqual(context_item["raw_left_track_id"], 3)
        self.assertEqual(context_item["godot_sequence"], 617)
        self.assertIn("held_missing", [item["reason"] for item in report["segments"]["held_missing"]])
        self.assertEqual(report["segments"]["temporal_mismatch"][0]["temporal_mismatch_count"], 1)
        self.assertEqual(report["sender_clients"]["last_disconnect"]["label"], "godot")

    def test_cli_writes_default_live_run_diagnostics_json(self):
        trace_path = self.tmp_path / "depth_estimation_trace.jsonl"
        raw_status_path = self.tmp_path / "raw_status.json"
        pcmr_status_path = self.tmp_path / "pcmr_status.json"
        sender_log_path = self.tmp_path / "sender.log"
        output_path = self.tmp_path / "live_run_diagnostics.json"

        write_jsonl(trace_path, [accepted_row(0, 0.7), accepted_row(1, 0.72)])
        write_json(raw_status_path, {"ok": True, "packets": 2, "realtime": {"expected_source_hz": 45.0}})
        write_json(pcmr_status_path, {"packets": 2, "live": 2, "sequence": 1, "card_apply_count": 2})
        sender_log_path.write_text("client connected: id=client-1 label=godot address=127.0.0.1:1\n", encoding="utf-8")

        completed = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--depth-trace",
                str(trace_path),
                "--raw-status",
                str(raw_status_path),
                "--pcmr-status",
                str(pcmr_status_path),
                "--sender-log",
                str(sender_log_path),
                "--output",
                str(output_path),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )

        status = json.loads(completed.stdout)
        self.assertEqual(Path(status["live_run_diagnostics_json"]), output_path)
        self.assertTrue(output_path.exists())

    def test_windows_stereo_wrapper_generates_run_diagnostics(self):
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("analyze_live_run_diagnostics.py", source)
        self.assertIn("live_run_diagnostics.json", source)
        self.assertIn("--depth-trace", source)
        self.assertIn("--raw-status", source)
        self.assertIn("--pcmr-status", source)
        self.assertIn("--sender-log", source)


if __name__ == "__main__":
    unittest.main()
