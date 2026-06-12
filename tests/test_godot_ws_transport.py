from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = ROOT / "godot-android" / "scripts" / "ws_transport.gd"
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_ws_transport_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_ws_transport_probe.ps1"


class GodotWSTransportTests(unittest.TestCase):
    def test_ws_transport_owns_peer_retry_and_subscribe(self):
        source = TRANSPORT.read_text(encoding="utf-8")

        self.assertIn("extends RefCounted", source)
        self.assertIn("class_name WSTransport", source)
        # No self-reference to the class_name: the script must stay loadable
        # in no-project (script-only) mode, like target_registry.gd and
        # smartxr_options.gd.
        self.assertNotIn("WSTransport.new()", source)
        self.assertNotIn(": WSTransport", source)
        # One peer, the historical 2.0 s retry-on-close interval, and the
        # subscribe-once flag per connection.
        self.assertIn("const RETRY_ON_CLOSE_SECONDS := 2.0", source)
        self.assertIn("var _ws := WebSocketPeer.new()", source)
        self.assertIn("var _subscribed := false", source)
        self.assertIn("var _packets_seen := 0", source)
        self.assertIn("var _last_packet_bytes := 0", source)
        self.assertIn("func connect_to(url: String) -> int:", source)
        self.assertIn("func poll(delta: float) -> void:", source)
        self.assertIn("connect_to_url(url)", source)
        # connect_to resets connection state exactly like the old loops did.
        self.assertIn("_connected = false", source)
        self.assertIn("_subscribed = false", source)
        self.assertIn("_retry_seconds = 0.0", source)
        # Poll: subscribe before draining packets, retry only while CLOSED.
        self.assertIn("_connected = state == WebSocketPeer.STATE_OPEN", source)
        self.assertIn("_send_subscribe_once()", source)
        self.assertIn("func _send_subscribe_once() -> void:", source)
        self.assertIn("if _subscribe_payload.is_empty() or _subscribed:", source)
        # send_text is the Godot 4 TEXT-frame API. The pre-extraction card
        # called the nonexistent WebSocketPeer.set_write_mode(), which made
        # the subscribe a runtime no-op; this extraction fixed that.
        self.assertIn("_ws.send_text(_subscribe_payload)", source)
        self.assertNotIn("set_write_mode", source)
        self.assertIn("elif state == WebSocketPeer.STATE_CLOSED:", source)
        self.assertIn("_retry_seconds += delta", source)
        self.assertIn("if _retry_seconds >= RETRY_ON_CLOSE_SECONDS:", source)
        # Packet path: count, record bytes, hand the decoded payload to the
        # card via the per-packet Callable.
        self.assertIn("_packets_seen += 1", source)
        self.assertIn("_last_packet_bytes = packet.size()", source)
        self.assertIn("_on_packet.call(packet.get_string_from_utf8())", source)
        # Retries re-resolve the URL through the card when a provider is set
        # (ADR-4: state resolution stays in the card).
        self.assertIn("func set_url_provider(url_provider: Callable) -> void:", source)
        self.assertIn("if _url_provider.is_valid():", source)
        # Read-only state surface the card snapshots from.
        self.assertIn("func ws_connected() -> bool:", source)
        self.assertIn("func ws_subscribed() -> bool:", source)
        self.assertIn("func packets_seen() -> int:", source)
        self.assertIn("func last_packet_bytes() -> int:", source)
        # The transport is dependency-free: it resolves no configuration and
        # loads no sibling scripts (the card passes everything in).
        self.assertNotIn("preload(", source)
        self.assertNotIn("OS.get_environment", source)
        self.assertNotIn("get_tree()", source)

    def test_moving_card_delegates_both_ws_loops(self):
        card = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('const WSTransportScript := preload("res://scripts/ws_transport.gd")', card)
        # Two transports, untyped `=` (no class_name reference) like _options.
        self.assertIn("var _control_ws = WSTransportScript.new()", card)
        self.assertIn("var _proxy_targets_ws = WSTransportScript.new()", card)
        # The card wires callbacks and keeps URL/enable resolution + packet
        # handling + error formatting (ADR-4).
        self.assertIn("func _setup_ws_transports() -> void:", card)
        self.assertIn("_control_ws.set_on_packet(_handle_packet)", card)
        self.assertIn("_control_ws.set_url_provider(_control_ws_url)", card)
        self.assertIn("_proxy_targets_ws.set_on_packet(_on_proxy_targets_ws_packet)", card)
        self.assertIn(
            '_proxy_targets_ws.set_subscribe_payload(JSON.stringify({"type": "subscribe", "stream": "proxy_targets"}))',
            card,
        )
        self.assertIn("_proxy_targets_ws.set_url_provider(_proxy_targets_ws_url)", card)
        self.assertIn('_last_command = "ws connect err " + str(result)', card)
        self.assertIn('_last_command = "proxy_ws_connect_err_" + str(result)', card)
        self.assertIn("_control_ws.connect_to(_control_ws_url())", card)
        self.assertIn("_proxy_targets_ws.connect_to(_proxy_targets_ws_url())", card)
        self.assertIn("_control_ws.poll(delta)", card)
        self.assertIn("_proxy_targets_ws.poll(delta)", card)
        # The card reads connection state from the transports for the
        # status snapshot (same keys and values as before the extraction).
        self.assertIn('"ws_connected": _control_ws.ws_connected()', card)
        self.assertIn('"ws_connected": _proxy_targets_ws.ws_connected()', card)
        self.assertIn('"ws_subscribed": _proxy_targets_ws.ws_subscribed()', card)
        self.assertIn('"packets": _proxy_targets_ws.packets_seen()', card)
        self.assertIn('"packet_bytes": _proxy_targets_ws.last_packet_bytes()', card)
        # The duplicated WebSocketPeer loops moved out of the card: no peer
        # is constructed or driven there anymore.
        self.assertNotIn("WebSocketPeer.new()", card)
        self.assertNotIn("WebSocketPeer.STATE_OPEN", card)
        self.assertNotIn("WebSocketPeer.STATE_CLOSED", card)
        self.assertNotIn("func _send_proxy_targets_subscribe", card)
        self.assertNotIn("_ws_retry_seconds", card)
        self.assertNotIn("_proxy_targets_ws_retry_seconds", card)
        self.assertNotIn("get_available_packet_count", card)

    def test_runtime_probe_and_runner_exist(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        # No-project mode: the script under test is injected via env vars,
        # and quit() must happen in _process, not _initialize.
        self.assertIn('OS.get_environment("SMARTXR_WS_TRANSPORT_SCRIPT")', probe)
        self.assertIn("SMARTXR_WS_TRANSPORT_PROBE_STATUS_PATH", probe)
        self.assertIn("SMARTXR_WS_TRANSPORT_LIVE_WS_URL", probe)
        self.assertIn("SMARTXR_WS_TRANSPORT_OFFLINE_WS_URL", probe)
        self.assertIn("func _process(delta: float) -> bool:", probe)
        self.assertIn("offline_retry_accumulates_while_closed", probe)
        self.assertIn("offline_reconnect_uses_url_provider", probe)
        self.assertIn("idle_subscribe_stays_false_without_open", probe)
        self.assertIn("live_packet_delivered_via_callable", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_WS_TRANSPORT_SCRIPT", runner)
        # The runner provides the live path with the local fake publisher,
        # like run_godot_script_only_websocket_probe.ps1.
        self.assertIn("fake_proxy_targets_publisher.py", runner)


if __name__ == "__main__":
    unittest.main()
