from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
GODOT_ANDROID = ROOT / "godot-android"
PROBE = GODOT_ANDROID / "tests" / "script_only_tcp_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_script_only_tcp_probe.ps1"


class GodotScriptOnlyTcpProbeTests(unittest.TestCase):
    def test_probe_uses_stream_peer_tcp_without_project_or_xr(self):
        self.assertTrue(PROBE.exists())
        source = PROBE.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", source)
        self.assertIn("StreamPeerTCP.new()", source)
        self.assertIn("connect_to_host(_host, _port)", source)
        self.assertIn("poll()", source)
        self.assertIn("StreamPeerTCP.STATUS_CONNECTED", source)
        self.assertIn('"tcp_status": _tcp.get_status()', source)
        self.assertIn('"connect_error": _connect_error', source)
        self.assertIn("FileAccess.open(_status_res, FileAccess.WRITE)", source)
        self.assertIn("quit(0)", source)
        self.assertIn("quit(1)", source)

        self.assertNotIn("WebSocketPeer", source)
        self.assertNotIn("OpenXR", source)
        self.assertNotIn("XRServer", source)

    def test_runner_starts_fake_publisher_and_runs_godot_script_only(self):
        self.assertTrue(RUNNER.exists())
        source = RUNNER.read_text(encoding="utf-8")

        self.assertIn("fake_proxy_targets_publisher.py", source)
        self.assertIn("script_only_tcp_probe.gd", source)
        self.assertIn("PROXY_TARGETS_TCP_HOST", source)
        self.assertIn("PROXY_TARGETS_TCP_PORT", source)
        self.assertIn("PROXY_TARGETS_TCP_STATUS_RES", source)
        self.assertIn("Wait-ForLogText", source)
        self.assertIn("proxy_targets fake publisher listening", source)
        self.assertIn("--headless", source)
        self.assertIn("--script", source)
        self.assertNotIn("--path", source)
        self.assertNotIn("OpenXR", source)
        self.assertNotIn("XRServer", source)


if __name__ == "__main__":
    unittest.main()
