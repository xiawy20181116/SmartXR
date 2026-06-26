from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
GODOT_ANDROID = ROOT / "godot-android"
PROBE = GODOT_ANDROID / "tests" / "script_only_websocket_staged_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_script_only_staged_probe.ps1"


class GodotScriptOnlyStagedProbeTests(unittest.TestCase):
    def test_staged_probe_has_ordered_isolation_stages(self):
        self.assertTrue(PROBE.exists())
        source = PROBE.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", source)
        self.assertIn("WebSocketPeer.new()", source)
        self.assertIn('STAGE_CONSUMER_LOAD := "consumer_load"', source)
        self.assertIn('STAGE_CONSUMER_INSTANCE := "consumer_instance"', source)
        self.assertIn('STAGE_ADAPTER_INSTANCE := "adapter_instance"', source)
        self.assertIn('STAGE_APPLY := "apply"', source)
        self.assertIn("PROXY_TARGETS_STAGE", source)
        self.assertIn("PROXY_TARGETS_CONSUMER_SCRIPT", source)
        self.assertIn("PROXY_TARGETS_CARD_ADAPTER_SCRIPT", source)
        self.assertIn("GDScript.new()", source)
        self.assertIn("FileAccess.get_file_as_string", source)
        self.assertIn("apply_proxy_targets_message", source)
        self.assertIn('"stage": _stage', source)
        self.assertIn('"setup_ok": _setup_ok', source)
        self.assertIn('"packets": _packets', source)
        self.assertIn('"parsed": _parsed', source)
        self.assertIn('"live": _live', source)
        self.assertIn('"depth_source": _last_depth_source', source)
        self.assertIn('"depth_confidence": _last_depth_confidence', source)

        self.assertNotIn("OpenXR", source)
        self.assertNotIn("XRServer", source)

    def test_staged_runner_executes_all_stages_script_only(self):
        self.assertTrue(RUNNER.exists())
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("script_only_websocket_staged_probe.gd", source)
        self.assertIn("consumer_load", source)
        self.assertIn("consumer_instance", source)
        self.assertIn("adapter_instance", source)
        self.assertIn("apply", source)
        self.assertIn("PROXY_TARGETS_STAGE", source)
        self.assertIn("PROXY_TARGETS_CONSUMER_SCRIPT", source)
        self.assertIn("PROXY_TARGETS_CARD_ADAPTER_SCRIPT", source)
        self.assertIn("--headless", source)
        self.assertIn("--script", source)
        self.assertNotIn("--path", source)
        self.assertIn("fake_proxy_targets_publisher.py", source)
        self.assertIn("Wait-ForLogText", source)


if __name__ == "__main__":
    unittest.main()
