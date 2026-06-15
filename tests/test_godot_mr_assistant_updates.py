from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RECEIVER = ROOT / "apps" / "godot_mr" / "scripts" / "assistant_updates_receiver.gd"
PROBE = ROOT / "apps" / "godot_mr" / "tests" / "script_only_assistant_updates_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_mr_assistant_updates_probe.ps1"
PUBLISHER = ROOT / "tools" / "fake_assistant_updates_publisher.py"
PUBLISHER_CLI = ROOT / "smartxr" / "cli" / "assistant_updates_publisher.py"


class GodotMRAssistantUpdatesTests(unittest.TestCase):
    def test_receiver_binds_transport_state_and_view(self):
        source = RECEIVER.read_text(encoding="utf-8")

        self.assertIn("extends Node", source)
        self.assertIn("class_name AssistantUpdatesReceiver", source)
        self.assertIn('const STREAM_NAME := "assistant_updates"', source)
        self.assertIn("func bind(assistant_state, assistant_view = null) -> void:", source)
        self.assertIn("func set_transport(transport) -> void:", source)
        self.assertIn("func connect_to(url: String) -> int:", source)
        self.assertIn("func poll(delta: float) -> void:", source)
        self.assertIn("func apply_packet(payload: String) -> bool:", source)
        self.assertIn("func packets_received() -> int:", source)
        self.assertIn("func packets_applied() -> int:", source)
        self.assertIn("func last_error() -> String:", source)
        self.assertIn("_transport.set_on_packet(_on_packet)", source)
        self.assertIn('JSON.stringify({"type": "subscribe", "stream": STREAM_NAME})', source)
        self.assertIn('apply_assistant_card_json(payload)', source)
        self.assertIn("update_from_snapshot", source)
        self.assertNotIn("WebSocketPeer.new()", source)
        self.assertNotIn("OS.get_environment", source)

    def test_script_only_probe_and_runner_cover_live_assistant_updates(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        self.assertIn('OS.get_environment("SMARTXR_ASSISTANT_UPDATES_RECEIVER_SCRIPT")', probe)
        self.assertIn('OS.get_environment("SMARTXR_ASSISTANT_CARD_STATE_SCRIPT")', probe)
        self.assertIn('OS.get_environment("SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT")', probe)
        self.assertIn('OS.get_environment("SMARTXR_WS_TRANSPORT_SCRIPT")', probe)
        self.assertIn('OS.get_environment("SMARTXR_ASSISTANT_UPDATES_LIVE_WS_URL")', probe)
        self.assertIn("SMARTXR_ASSISTANT_UPDATES_PROBE_STATUS_PATH", probe)
        self.assertIn("invalid_payload_sets_error", probe)
        self.assertIn("live_payload_updates_snapshot", probe)
        self.assertIn("view_renders_live_response", probe)
        self.assertIn("receiver_subscribed_once_open", probe)
        self.assertIn("receiver_packets_applied", probe)
        self.assertIn("fake_assistant_updates_publisher.py", runner)
        self.assertIn("assistant_updates fake publisher listening", runner)
        self.assertIn("SMARTXR_ASSISTANT_UPDATES_RECEIVER_SCRIPT", runner)
        self.assertIn("SMARTXR_ASSISTANT_UPDATES_LIVE_WS_URL", runner)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)

    def test_fake_assistant_updates_publisher_serves_canonical_card_payloads(self):
        wrapper = PUBLISHER.read_text(encoding="utf-8")
        cli = PUBLISHER_CLI.read_text(encoding="utf-8")

        self.assertIn("from smartxr.cli.assistant_updates_publisher import", wrapper)
        self.assertIn("def is_assistant_updates_request(first_line: str) -> bool:", cli)
        self.assertIn('return path == "/assistant_updates"', cli)
        self.assertIn("build_assistant_card_payload", cli)
        self.assertIn("drain_client_frames", cli)
        self.assertIn("encode_websocket_text_frame", cli)
        self.assertIn("serve_single_client", cli)
        self.assertIn("assistant_updates fake publisher listening", cli)
        self.assertIn("Ada is working on XR-42.", cli)


if __name__ == "__main__":
    unittest.main()
