import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MONITOR = ROOT / "tools" / "monitor_proxy_targets_live_stream.py"
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

    def test_classifies_connection_refused_with_actionable_hint(self):
        monitor = load_module(MONITOR, "monitor_proxy_targets_live_stream")

        status = monitor.status_from_exception(ConnectionRefusedError(10061, "actively refused"), "ws://127.0.0.1:8766/proxy_targets", 10.0)

        self.assertFalse(status["ok"])
        self.assertEqual(status["reason"], "connection_refused")
        self.assertIn("publisher is not listening", status["hint"])
        self.assertIn("run_antman_vst_proxy_targets_live_publisher.ps1", status["hint"])

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
