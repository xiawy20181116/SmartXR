import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MONITOR = ROOT / "tools" / "monitor_proxy_targets_live_stream.py"
HEALTH_MONITOR = ROOT / "tools" / "validate_proxy_targets_end_to_end_health.py"
DEPTH_VALIDATOR = ROOT / "tools" / "validate_proxy_targets_depth_confidence_stream.py"
RUNNER = ROOT / "tools" / "run_proxy_targets_live_monitor.ps1"
FAKE_PUBLISHER = ROOT / "tools" / "fake_proxy_targets_publisher.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ProxyTargetsLiveMonitorTests(unittest.TestCase):
    def test_analyzes_stable_contiguous_proxy_targets_stream(self):
        publisher = load_module(FAKE_PUBLISHER, "fake_proxy_targets_publisher")
        monitor = load_module(MONITOR, "monitor_proxy_targets_live_stream")

        messages = [
            publisher.build_proxy_targets_message(0.0, sequence=0),
            publisher.build_proxy_targets_message(0.1, sequence=1),
            publisher.build_proxy_targets_message(0.2, sequence=2),
        ]

        status = monitor.analyze_messages(messages, min_packets=3)

        self.assertTrue(status["ok"])
        self.assertEqual(status["packets"], 3)
        self.assertEqual(status["parsed"], 3)
        self.assertEqual(status["first_sequence"], 0)
        self.assertEqual(status["last_sequence"], 2)
        self.assertTrue(status["sequence_contiguous"])
        self.assertTrue(status["position_changed"])
        self.assertEqual(status["target_ids"], ["person-7"])
        self.assertEqual(status["errors"], [])

    def test_flags_sequence_gaps_and_schema_errors(self):
        publisher = load_module(FAKE_PUBLISHER, "fake_proxy_targets_publisher")
        monitor = load_module(MONITOR, "monitor_proxy_targets_live_stream")

        bad = publisher.build_proxy_targets_message(0.0, sequence=0)
        del bad["targets"][0]["transform"]["position"]
        messages = [
            bad,
            publisher.build_proxy_targets_message(0.1, sequence=2),
        ]

        status = monitor.analyze_messages(messages, min_packets=3)

        self.assertFalse(status["ok"])
        self.assertEqual(status["packets"], 2)
        self.assertFalse(status["sequence_contiguous"])
        self.assertIn("not enough packets: 2 < 3", status["errors"])
        self.assertTrue(any("$.targets[0].transform.position" in error for error in status["errors"]))

    def test_analyzes_depth_confidence_distribution(self):
        monitor = load_module(MONITOR, "monitor_proxy_targets_live_stream")
        messages = [
            {
                "type": "proxy_targets",
                "schema_version": 1,
                "sequence": 0,
                "targets": [
                    {
                        "target_id": "person-high",
                        "source": "vst",
                        "coordinate_space": "head",
                        "transform_space": "head",
                        "state": "tracked",
                        "confidence": 0.9,
                        "depth_source": "shoulder_midpoint",
                        "depth_confidence": "high",
                        "timestamp_ms": 1780911169157,
                        "transform": {
                            "position": [0.0, 0.0, -1.2],
                            "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                            "scale": [1.0, 1.0, 1.0],
                        },
                    }
                ],
                "cards": [{"card_id": "CardAnchor", "target_id": "person-high", "offset_rule": {}}],
            },
            {
                "type": "proxy_targets",
                "schema_version": 1,
                "sequence": 1,
                "targets": [
                    {
                        "target_id": "person-low",
                        "source": "vst",
                        "coordinate_space": "head",
                        "transform_space": "head",
                        "state": "tracked",
                        "confidence": 0.9,
                        "depth_source": "bbox_top_center_fallback",
                        "depth_confidence": "low",
                        "timestamp_ms": 1780911169167,
                        "transform": {
                            "position": [0.1, 0.0, -1.1],
                            "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                            "scale": [1.0, 1.0, 1.0],
                        },
                    }
                ],
                "cards": [{"card_id": "CardAnchor", "target_id": "person-low", "offset_rule": {}}],
            },
        ]

        status = monitor.analyze_messages(messages, min_packets=2)

        self.assertTrue(status["ok"])
        self.assertEqual(status["target_count"], 2)
        self.assertEqual(status["depth_confidences"], {"high": 1, "low": 1})
        self.assertEqual(status["depth_sources"], {"bbox_top_center_fallback": 1, "shoulder_midpoint": 1})
        self.assertEqual(status["missing_depth_confidence_count"], 0)
        self.assertEqual(status["missing_depth_source_count"], 0)

    def test_analyzes_realtime_rate_and_sequence_drops_against_45hz(self):
        monitor = load_module(MONITOR, "monitor_proxy_targets_live_stream")

        def message(sequence, timestamp_ms):
            return {
                "type": "proxy_targets",
                "schema_version": 1,
                "sequence": sequence,
                "targets": [
                    {
                        "target_id": "vst_stereo-active-1",
                        "source": "vst",
                        "coordinate_space": "head",
                        "transform_space": "head",
                        "state": "tracked",
                        "confidence": 0.9,
                        "depth_source": "bbox_top_center_fallback",
                        "depth_confidence": "low",
                        "timestamp_ms": timestamp_ms,
                        "transform": {
                            "position": [0.0, 0.0, -1.0 - sequence * 0.01],
                            "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                            "scale": [1.0, 1.0, 1.0],
                        },
                    }
                ],
                "cards": [{"card_id": "CardAnchor", "target_id": "vst_stereo-active-1", "offset_rule": {}}],
            }

        status = monitor.analyze_messages(
            [
                message(0, 1_000),
                message(1, 1_022),
                message(3, 1_088),
            ],
            min_packets=3,
            expected_source_hz=45.0,
        )

        self.assertFalse(status["ok"])
        self.assertEqual(status["realtime"]["expected_source_hz"], 45.0)
        self.assertEqual(status["realtime"]["sequence_gap_count"], 1)
        self.assertEqual(status["realtime"]["packet_drop_count"], 1)
        self.assertEqual(status["realtime"]["late_interval_count"], 1)
        self.assertAlmostEqual(status["realtime"]["observed_packet_hz"], 22.7, places=1)

    def test_depth_confidence_validator_requires_expected_distribution(self):
        validator = load_module(DEPTH_VALIDATOR, "validate_proxy_targets_depth_confidence_stream")
        status = {
            "ok": True,
            "depth_confidences": {"high": 3, "low": 2},
            "missing_depth_confidence_count": 0,
            "missing_depth_source_count": 0,
        }

        errors = validator.validate_depth_confidence_status(
            status,
            require_confidences=["high", "low"],
            forbid_confidences=["none"],
            require_depth_fields=True,
        )

        self.assertEqual(errors, [])

        bad_status = {
            "ok": True,
            "depth_confidences": {"high": 1, "none": 1},
            "missing_depth_confidence_count": 1,
            "missing_depth_source_count": 0,
        }
        bad_errors = validator.validate_depth_confidence_status(
            bad_status,
            require_confidences=["high", "low"],
            forbid_confidences=["none"],
            require_depth_fields=True,
        )

        self.assertIn("required depth_confidence missing: low", bad_errors)
        self.assertIn("forbidden depth_confidence present: none=1", bad_errors)
        self.assertIn("targets missing depth_confidence: 1", bad_errors)

    def test_end_to_end_health_flags_sample_fallback_despite_raw_stream_ok(self):
        health = load_module(HEALTH_MONITOR, "validate_proxy_targets_end_to_end_health")
        raw_status = {
            "ok": True,
            "packets": 10,
            "parsed": 10,
            "sequence_contiguous": True,
            "position_changed": True,
            "target_ids": ["vst_stereo-person-2-3"],
            "depth_confidences": {"high": 10},
            "depth_sources": {"pov_stereo_triangulation": 10},
            "missing_depth_confidence_count": 0,
            "missing_depth_source_count": 0,
        }
        pcmr_status = {
            "last_command": "proxy_sample",
            "ws_connected": False,
            "ws_subscribed": False,
            "packets": 0,
            "parsed": 0,
            "live": 0,
            "sequence": -1,
            "card_target_id": "person-7",
            "card_attach_target_id": "person-7",
            "proxy_target_ids": ["person-7"],
            "card_node_position": "0.50 0.25 -1.20",
            "card_resolved_position": "0.50 0.25 -1.20",
        }
        sender_log = "\n".join(
            [
                "stereo proxy_targets live publisher listening on ws://127.0.0.1:8766/proxy_targets",
                "sent stereo seq=20 target=vst_stereo-person-2-3 depth_source=pov_stereo_triangulation depth_confidence=high",
            ]
        )

        status = health.evaluate_health(sender_log, raw_status, pcmr_status, min_packets=10)

        self.assertFalse(status["ok"])
        self.assertIn("STREAM_OK", status["verdicts"])
        self.assertIn("GODOT_NOT_CONNECTED", status["verdicts"])
        self.assertIn("SAMPLE_FALLBACK_ACTIVE", status["verdicts"])
        self.assertNotIn("LOW_CONFIDENCE_DEPTH_ONLY", status["verdicts"])
        self.assertIn("PCMR/card is still on proxy_sample/person-7", status["errors"])

    def test_end_to_end_health_passes_when_card_binds_live_stereo_target(self):
        health = load_module(HEALTH_MONITOR, "validate_proxy_targets_end_to_end_health")
        raw_status = {
            "ok": True,
            "packets": 10,
            "parsed": 10,
            "sequence_contiguous": True,
            "position_changed": True,
            "target_ids": ["vst_stereo-person-2-3"],
            "depth_confidences": {"low": 10},
            "depth_sources": {"bbox_top_center_fallback": 10},
            "missing_depth_confidence_count": 0,
            "missing_depth_source_count": 0,
            "client_label": "monitor",
            "ws_connected": True,
            "ws_subscribed": True,
            "first_packet_seen": True,
            "packets_before_close": 10,
            "close_reason": "completed",
        }
        pcmr_status = {
            "last_command": "proxy_live",
            "ws_connected": True,
            "ws_subscribed": True,
            "packets": 12,
            "parsed": 12,
            "live": 12,
            "sequence": 11,
            "card_target_id": "vst_stereo-person-2-3",
            "card_attach_target_id": "vst_stereo-person-2-3",
            "proxy_target_ids": ["vst_stereo-person-2-3"],
            "proxy_local_position": "-0.04 0.11 -0.30",
            "proxy_world_position": "0.80 0.31 0.05",
            "card_node_position": "-0.04 0.11 -0.30",
            "card_resolved_position": "-0.04 0.11 -0.30",
            "source_coordinate": {
                "head_position_m": [-0.04, 0.11, -0.30],
                "camera_position_m": [-0.04, 0.11, 0.30],
            },
        }
        sender_log = "\n".join(
            [
                "stereo proxy_targets live publisher listening on ws://127.0.0.1:8766/proxy_targets",
                "sent stereo seq=20 target=vst_stereo-person-2-3 depth_source=bbox_top_center_fallback depth_confidence=low",
            ]
        )

        status = health.evaluate_health(sender_log, raw_status, pcmr_status, min_packets=10)

        self.assertTrue(status["ok"])
        self.assertIn("SENDER_READY", status["verdicts"])
        self.assertIn("STREAM_OK", status["verdicts"])
        self.assertIn("TRANSPORT_TO_GODOT_OK", status["verdicts"])
        self.assertIn("CARD_BOUND_TO_LIVE_TARGET", status["verdicts"])
        self.assertIn("LOW_CONFIDENCE_DEPTH_ONLY", status["verdicts"])
        self.assertEqual(status["raw"]["client_label"], "monitor")
        self.assertEqual(status["raw"]["close_reason"], "completed")
        self.assertEqual(status["raw"]["packets_before_close"], 10)
        self.assertEqual(status["pcmr"]["proxy_world_position"], "0.80 0.31 0.05")
        self.assertEqual(status["pcmr"]["card_minus_proxy_world"], [-0.84, -0.2, -0.35])
        self.assertEqual(status["pcmr"]["head_z_sign"], "negative")
        self.assertEqual(status["pcmr"]["camera_z_sign"], "positive")
        self.assertEqual(status["pcmr"]["world_z_sign"], "positive")
        self.assertEqual(status["errors"], [])

    def test_end_to_end_health_reports_when_godot_client_is_not_active(self):
        health = load_module(HEALTH_MONITOR, "validate_proxy_targets_end_to_end_health")
        raw_status = {
            "ok": True,
            "packets": 10,
            "parsed": 10,
            "sequence_contiguous": True,
            "position_changed": True,
            "target_ids": ["vst_stereo-active-1"],
            "depth_confidences": {"low": 10},
            "depth_sources": {"bbox_top_center_fallback": 10},
            "missing_depth_confidence_count": 0,
            "missing_depth_source_count": 0,
        }
        pcmr_status = {
            "last_command": "proxy_live",
            "ws_connected": True,
            "ws_subscribed": True,
            "packets": 5,
            "parsed": 5,
            "live": 5,
            "card_target_id": "vst_stereo-active-1",
            "card_attach_target_id": "vst_stereo-active-1",
            "proxy_target_ids": ["vst_stereo-active-1"],
            "card_node_position": "0.20 0.10 -0.50",
            "card_resolved_position": "0.20 0.10 -0.50",
        }
        sender_log = "\n".join(
            [
                "stereo proxy_targets live publisher listening on ws://127.0.0.1:8766/proxy_targets",
                "sent stereo seq=20 target=vst_stereo-active-1 depth_source=bbox_top_center_fallback depth_confidence=low",
            ]
        )
        depth_trace_summary = {
            "clients": {
                "active_client_count": 1,
                "active_clients": ["client-2=monitor@127.0.0.1:13285"],
                "last_disconnect": {"client_id": "client-1", "label": "godot", "reason": "client_closed"},
            }
        }

        status = health.evaluate_health(
            sender_log,
            raw_status,
            pcmr_status,
            min_packets=10,
            depth_trace_summary=depth_trace_summary,
        )

        self.assertFalse(status["ok"])
        self.assertIn("GODOT_CLIENT_NOT_ACTIVE", status["verdicts"])
        self.assertEqual(status["tracking"]["clients"]["last_disconnect"]["label"], "godot")
        self.assertTrue(any("Godot client is not currently active" in error for error in status["errors"]))

    def test_end_to_end_health_accepts_decoupled_published_logs_and_sustained_pcmr_live(self):
        health = load_module(HEALTH_MONITOR, "validate_proxy_targets_end_to_end_health")
        raw_status = {
            "ok": True,
            "packets": 10,
            "parsed": 10,
            "sequence_contiguous": True,
            "position_changed": True,
            "target_ids": ["vst_stereo-active-1"],
            "depth_confidences": {"low": 10},
            "depth_sources": {"bbox_top_center_fallback": 10},
            "missing_depth_confidence_count": 0,
            "missing_depth_source_count": 0,
        }
        pcmr_status = {
            "last_command": "proxy_live",
            "ws_connected": True,
            "ws_subscribed": True,
            "packets": 1146,
            "parsed": 1146,
            "live": 1146,
            "sequence": 1257,
            "card_target_id": "vst_stereo-active-1",
            "card_attach_target_id": "vst_stereo-active-1",
            "proxy_target_ids": ["vst_stereo-active-1"],
            "card_node_position": "0.20 0.10 -0.50",
            "card_resolved_position": "0.20 0.10 -0.50",
        }
        sender_log = "\n".join(
            [
                "stereo proxy_targets live publisher listening on ws://127.0.0.1:8766/proxy_targets",
                "updated stereo detector seq=298 target=vst_stereo-active-1 depth_source=bbox_top_center_fallback depth_confidence=low clients=2",
                "published stereo seq=694 target=vst_stereo-active-1 freshness=stale depth_source=bbox_top_center_fallback depth_confidence=low clients=1",
            ]
        )
        depth_trace_summary = {
            "clients": {
                "active_client_count": 1,
                "active_clients": ["client-2=monitor@127.0.0.1:13285"],
                "last_disconnect": {"client_id": "client-1", "label": "godot", "reason": "client_closed"},
            }
        }

        status = health.evaluate_health(
            sender_log,
            raw_status,
            pcmr_status,
            min_packets=10,
            depth_trace_summary=depth_trace_summary,
        )

        self.assertTrue(status["ok"])
        self.assertIn("SENDER_STEREO_TARGETS", status["verdicts"])
        self.assertIn("GODOT_CLIENT_STATUS_AMBIGUOUS", status["verdicts"])
        self.assertNotIn("GODOT_CLIENT_NOT_ACTIVE", status["verdicts"])
        self.assertEqual(status["sender"]["last_target_id"], "vst_stereo-active-1")
        self.assertEqual(status["errors"], [])

    def test_end_to_end_health_does_not_flag_sample_when_card_is_live_but_sample_target_remains_registered(self):
        health = load_module(HEALTH_MONITOR, "validate_proxy_targets_end_to_end_health")
        raw_status = {
            "ok": True,
            "packets": 10,
            "parsed": 10,
            "sequence_contiguous": True,
            "position_changed": True,
            "target_ids": ["vst_stereo-person-6-7"],
            "depth_confidences": {"low": 10},
            "depth_sources": {"bbox_top_center_fallback": 10},
            "missing_depth_confidence_count": 0,
            "missing_depth_source_count": 0,
        }
        pcmr_status = {
            "last_command": "proxy_live",
            "ws_connected": True,
            "ws_subscribed": True,
            "packets": 3,
            "parsed": 3,
            "live": 3,
            "sequence": 2,
            "card_target_id": "vst_stereo-person-6-7",
            "card_attach_target_id": "vst_stereo-person-6-7",
            "proxy_target_ids": ["person-7", "vst_stereo-person-6-7"],
            "card_node_position": "1.20 0.58 0.08",
            "card_resolved_position": "1.20 0.58 0.08",
        }
        sender_log = "\n".join(
            [
                "stereo proxy_targets live publisher listening on ws://127.0.0.1:8766/proxy_targets",
                "sent stereo seq=0 target=vst_stereo-person-6-7 depth_source=bbox_top_center_fallback depth_confidence=low",
            ]
        )

        status = health.evaluate_health(sender_log, raw_status, pcmr_status, min_packets=10)

        self.assertTrue(status["ok"])
        self.assertIn("CARD_BOUND_TO_LIVE_TARGET", status["verdicts"])
        self.assertNotIn("SAMPLE_FALLBACK_ACTIVE", status["verdicts"])

    def test_wait_for_health_uses_latest_pcmr_status_until_timeout(self):
        health = load_module(HEALTH_MONITOR, "validate_proxy_targets_end_to_end_health")
        raw_status = {
            "ok": True,
            "packets": 10,
            "parsed": 10,
            "sequence_contiguous": True,
            "position_changed": True,
            "target_ids": ["vst_stereo-person-2-3"],
            "depth_confidences": {"low": 10},
            "depth_sources": {"bbox_top_center_fallback": 10},
            "missing_depth_confidence_count": 0,
            "missing_depth_source_count": 0,
        }
        pcmr_status = {
            "last_command": "proxy_live",
            "ws_connected": True,
            "ws_subscribed": True,
            "packets": 12,
            "parsed": 12,
            "live": 12,
            "card_target_id": "vst_stereo-person-2-3",
            "card_attach_target_id": "vst_stereo-person-2-3",
            "proxy_target_ids": ["vst_stereo-person-2-3"],
            "card_node_position": "-0.04 0.11 -0.30",
            "card_resolved_position": "-0.04 0.11 -0.30",
        }
        sender_log = (
            "stereo proxy_targets live publisher listening on ws://127.0.0.1:8766/proxy_targets\n"
            "sent stereo seq=20 target=vst_stereo-person-2-3 depth_source=bbox_top_center_fallback depth_confidence=low\n"
        )
        with mock.patch.object(Path, "exists", return_value=True), mock.patch.object(
            health, "read_log_text", return_value=sender_log
        ), mock.patch.object(health, "load_json", side_effect=[raw_status, pcmr_status]):
            status = health.wait_for_health(Path("sender.log"), Path("raw.json"), Path("pcmr.json"), min_packets=10, timeout_s=0.1, interval_s=0.01)

        self.assertTrue(status["ok"])
        self.assertIn("CARD_BOUND_TO_LIVE_TARGET", status["verdicts"])

    def test_health_decodes_utf16_sender_log_bytes(self):
        health = load_module(HEALTH_MONITOR, "validate_proxy_targets_end_to_end_health")
        raw_status = {
            "ok": True,
            "packets": 10,
            "parsed": 10,
            "sequence_contiguous": True,
            "position_changed": True,
            "target_ids": ["vst_stereo-person-2-3"],
            "depth_confidences": {"low": 10},
            "depth_sources": {"bbox_top_center_fallback": 10},
            "missing_depth_confidence_count": 0,
            "missing_depth_source_count": 0,
        }
        pcmr_status = {
            "last_command": "proxy_live",
            "ws_connected": True,
            "ws_subscribed": True,
            "packets": 12,
            "parsed": 12,
            "live": 12,
            "card_target_id": "vst_stereo-person-2-3",
            "card_attach_target_id": "vst_stereo-person-2-3",
            "proxy_target_ids": ["vst_stereo-person-2-3"],
            "card_node_position": "-0.04 0.11 -0.30",
            "card_resolved_position": "-0.04 0.11 -0.30",
        }
        sender_log = (
            "stereo proxy_targets live publisher listening on ws://127.0.0.1:8766/proxy_targets\n"
            "sent stereo seq=20 target=vst_stereo-person-2-3 depth_source=bbox_top_center_fallback depth_confidence=low\n"
        )
        decoded = health.decode_log_text(sender_log.encode("utf-16"))
        status = health.evaluate_health(decoded, raw_status, pcmr_status, min_packets=10)

        self.assertTrue(status["ok"])
        self.assertIn("SENDER_READY", status["verdicts"])
        self.assertIn("SENDER_STEREO_TARGETS", status["verdicts"])

    def test_health_flags_sender_no_frames_when_stereo_inputs_are_empty(self):
        health = load_module(HEALTH_MONITOR, "validate_proxy_targets_end_to_end_health")
        raw_status = {
            "ok": False,
            "packets": 0,
            "parsed": 0,
            "target_ids": [],
            "errors": ["timed out"],
        }
        pcmr_status = {
            "last_command": "proxy_sample",
            "ws_connected": True,
            "ws_subscribed": True,
            "packets": 0,
            "parsed": 0,
            "live": 0,
            "card_target_id": "person-7",
            "card_attach_target_id": "person-7",
            "proxy_target_ids": ["person-7"],
            "card_node_position": "0.50 0.25 -1.20",
            "card_resolved_position": "0.50 0.25 -1.20",
        }
        sender_log = "\n".join(
            [
                "stereo proxy_targets live publisher listening on ws://127.0.0.1:8766/proxy_targets",
                "client connected from ('127.0.0.1', 10172): GET /proxy_targets HTTP/1.1",
                "No stereo target frames available from Left/Right VST SHM + HumanTrackor",
                "stereo diagnostics: reason=no_pair reads=120 left_frames=0 right_frames=0 last_pair_frame_id=-1 left_pending=0 right_pending=0 stereo_rejection=-",
            ]
        )

        status = health.evaluate_health(sender_log, raw_status, pcmr_status, min_packets=10)

        self.assertFalse(status["ok"])
        self.assertIn("SENDER_READY", status["verdicts"])
        self.assertIn("SENDER_NO_FRAMES", status["verdicts"])
        self.assertEqual(status["sender"]["last_empty_reason"], "no_pair")
        self.assertEqual(status["sender"]["last_left_frames"], 0)
        self.assertEqual(status["sender"]["last_right_frames"], 0)

    def test_health_summarizes_depth_trace_tracking_stability_fields(self):
        health = load_module(HEALTH_MONITOR, "validate_proxy_targets_end_to_end_health")
        trace_path = ROOT / ".tmp" / "tests" / "depth_trace_tracking.jsonl"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "event": "accepted",
                            "sequence": 1,
                            "target_id": "vst_stereo-active-1",
                            "active_target_id": "active-1",
                            "raw_left_track_id": 1,
                            "raw_right_track_id": 2,
                            "candidate_count": 3,
                            "selected_score": 0.7,
                            "switch_count": 0,
                            "switch_reason": "initial",
                            "active_age_frames": 1,
                            "held_last_pose": False,
                            "sync": {
                                "pairing_strategy": "capture_timestamp",
                                "temporal_mismatch_count": 1,
                                "dropped_left_frames": 1,
                                "dropped_right_frames": 0,
                            },
                            "realtime": {
                                "target_source_hz": 45.0,
                                "frames_seen_left": 10,
                                "frames_seen_right": 9,
                                "estimated_left_dropped_frames": 2,
                                "estimated_right_dropped_frames": 3,
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "event": "accepted",
                            "sequence": 2,
                            "target_id": "vst_stereo-active-1",
                            "active_target_id": "active-1",
                            "raw_left_track_id": 1,
                            "raw_right_track_id": 2,
                            "candidate_count": 4,
                            "selected_score": 0.62,
                            "switch_count": 0,
                            "switch_reason": "active_continuity",
                            "active_age_frames": 2,
                            "held_last_pose": False,
                        }
                    ),
                    json.dumps(
                        {
                            "event": "accepted",
                            "sequence": 3,
                            "target_id": "vst_stereo-active-1",
                            "active_target_id": "active-1",
                            "raw_left_track_id": 9,
                            "raw_right_track_id": 10,
                            "candidate_count": 4,
                            "selected_score": 0.96,
                            "switch_count": 1,
                            "switch_reason": "switch_confirmed",
                            "active_age_frames": 1,
                            "held_last_pose": False,
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        summary = health.summarize_depth_trace(trace_path)
        status = health.evaluate_health(
            "stereo proxy_targets live publisher listening\nsent stereo seq=2 target=vst_stereo-active-1 depth_source=bbox_top_center_fallback depth_confidence=low\n",
            {
                "ok": True,
                "packets": 10,
                "parsed": 10,
                "sequence_contiguous": True,
                "position_changed": True,
                "target_ids": ["vst_stereo-active-1"],
                "depth_confidences": {"low": 10},
                "depth_sources": {"bbox_top_center_fallback": 10},
            },
            {
                "last_command": "proxy_live",
                "ws_connected": True,
                "ws_subscribed": True,
                "packets": 10,
                "parsed": 10,
                "live": 10,
                "card_target_id": "vst_stereo-active-1",
                "card_attach_target_id": "vst_stereo-active-1",
                "proxy_target_ids": ["vst_stereo-active-1"],
                "card_node_position": "1.20 0.58 0.08",
                "card_resolved_position": "1.20 0.58 0.08",
            },
            min_packets=10,
            depth_trace_summary=summary,
        )

        trace_path.unlink(missing_ok=True)
        self.assertEqual(status["tracking"]["accepted_count"], 3)
        self.assertEqual(status["tracking"]["active_target_ids"], ["active-1"])
        self.assertEqual(status["tracking"]["raw_track_pairs"], ["1-2", "9-10"])
        self.assertEqual(status["tracking"]["target_switch_count"], 0)
        self.assertEqual(status["tracking"]["raw_track_switch_count"], 1)
        self.assertEqual(status["tracking"]["last_switch_reason"], "switch_confirmed")
        self.assertEqual(status["tracking"]["last_active_age_frames"], 1)
        self.assertEqual(status["tracking"]["sync"]["pairing_strategy"], "capture_timestamp")
        self.assertEqual(status["tracking"]["sync"]["temporal_mismatch_count"], 1)
        self.assertEqual(status["tracking"]["realtime"]["target_source_hz"], 45.0)
        self.assertEqual(status["tracking"]["realtime"]["estimated_left_dropped_frames"], 2)
        self.assertEqual(status["tracking"]["realtime"]["estimated_right_dropped_frames"], 3)

    def test_classifies_connection_refused_with_actionable_hint(self):
        monitor = load_module(MONITOR, "monitor_proxy_targets_live_stream")

        status = monitor.status_from_exception(ConnectionRefusedError(10061, "actively refused"), "ws://127.0.0.1:8766/proxy_targets", 10.0)

        self.assertFalse(status["ok"])
        self.assertEqual(status["reason"], "connection_refused")
        self.assertIn("publisher is not listening", status["hint"])
        self.assertIn("run_antman_vst_proxy_targets_live_publisher.ps1", status["hint"])

    def test_classifies_connection_reset_with_stage_and_packet_counts(self):
        monitor = load_module(MONITOR, "monitor_proxy_targets_live_stream")

        status = monitor.status_from_exception(
            ConnectionResetError(10054, "remote host reset"),
            "ws://127.0.0.1:8766/proxy_targets",
            20.0,
            ws_connected=True,
            ws_subscribed=True,
            packets_before_close=3,
            first_sequence=0,
            last_sequence=2,
            client_label="monitor",
        )

        self.assertFalse(status["ok"])
        self.assertEqual(status["reason"], "connection_reset")
        self.assertTrue(status["ws_connected"])
        self.assertTrue(status["ws_subscribed"])
        self.assertTrue(status["first_packet_seen"])
        self.assertEqual(status["packets_before_close"], 3)
        self.assertEqual(status["first_sequence"], 0)
        self.assertEqual(status["last_sequence"], 2)
        self.assertEqual(status["client_label"], "monitor")

    def test_runner_invokes_monitor_only(self):
        self.assertTrue(RUNNER.exists())
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("monitor_proxy_targets_live_stream.py", source)
        self.assertIn("SmartXR proxy_targets live stream monitor", source)
        self.assertIn("--url", source)
        self.assertIn("--min-packets", source)
        self.assertIn("--timeout-seconds", source)
        self.assertNotIn("fake_proxy_targets_publisher.py", source)
        self.assertNotIn("antman_vst_proxy_targets_live_publisher.py", source)


if __name__ == "__main__":
    unittest.main()
