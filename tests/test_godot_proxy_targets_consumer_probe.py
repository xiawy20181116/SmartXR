from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "run_godot_proxy_targets_consumer_probe.ps1"
PROBE = ROOT / "godot-android" / "tests" / "script_only_proxy_targets_consumer_probe.gd"


class GodotProxyTargetsConsumerProbeTests(unittest.TestCase):
    def test_probe_covers_dynamic_stale_world_hold(self):
        self.assertTrue(RUNNER.exists())
        self.assertTrue(PROBE.exists())
        runner = RUNNER.read_text(encoding="utf-8")
        probe = PROBE.read_text(encoding="utf-8")

        self.assertIn("script_only_proxy_targets_consumer_probe.gd", runner)
        self.assertIn("proxy_targets_consumer.gd", runner)
        self.assertIn("PROXY_TARGETS_CONSUMER_SCRIPT", runner)
        self.assertIn("PROXY_TARGETS_CONSUMER_PROBE_STATUS_PATH", runner)
        self.assertIn("dynamic_stale_holds_previous_world_position", probe)
        self.assertIn("dynamic_stale_reports_held_state", probe)
        self.assertIn("fresh_after_stale_updates_to_current_head_pose", probe)


if __name__ == "__main__":
    unittest.main()
