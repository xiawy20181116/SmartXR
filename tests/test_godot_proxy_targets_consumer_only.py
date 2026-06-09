from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "run_godot_proxy_targets_consumer_only.ps1"


class GodotProxyTargetsConsumerOnlyRunnerTests(unittest.TestCase):
    def test_runner_starts_only_godot_staged_apply_consumer(self):
        self.assertTrue(RUNNER.exists())
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("SmartXR Godot proxy_targets consumer-only staged apply", source)
        self.assertIn("script_only_websocket_staged_probe.gd", source)
        self.assertIn("proxy_targets_consumer.gd", source)
        self.assertIn("proxy_targets_card_adapter.gd", source)
        self.assertIn("PROXY_TARGETS_WS_URL", source)
        self.assertIn("PROXY_TARGETS_STAGE", source)
        self.assertIn('"apply"', source)
        self.assertIn("PROXY_TARGETS_STAGE_STATUS_RES", source)
        self.assertIn("PROXY_TARGETS_CONSUMER_SCRIPT", source)
        self.assertIn("PROXY_TARGETS_CARD_ADAPTER_SCRIPT", source)
        self.assertIn("--headless", source)
        self.assertIn("--script", source)
        self.assertIn("packets", source)
        self.assertIn("parsed", source)
        self.assertIn("registered_targets", source)

        self.assertNotIn("Start-Process `\n        -FilePath $PythonExe", source)
        self.assertNotIn("fake_proxy_targets_publisher.py", source)
        self.assertNotIn("antman_vst_proxy_targets_live_publisher.py", source)


if __name__ == "__main__":
    unittest.main()
