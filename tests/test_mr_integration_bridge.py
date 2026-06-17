"""Module 3 live bridge tests (YAN-110 option A): C1 WS -> align -> C2 WS.

- **Unit**: the shared transport client primitives (masked encode / server-frame
  read incl. ping/close) and the proxy_targets request gate.
- **L2 live end-to-end (headless)**: a real C1 publisher thread -> the bridge
  thread -> a card-side reader, asserting the forwarded proxy_targets stream is
  schema-valid, sequence-contiguous, and carries targets + a card. No device.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlparse

from smartxr.cli import mr_integration_bridge as bridge
from smartxr.cli import tracking_raw_publisher as pub
from smartxr.schema import validate_message as validate_proxy_targets
from smartxr.transport import (
    client_handshake,
    decode_websocket_frame,
    encode_masked_text_frame,
    encode_websocket_control_frame,
    encode_websocket_text_frame,
    read_server_text_frame,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "godot-android" / "fixtures" / "tracking_raw_replay_detections.jsonl"
HARNESS_PS1 = ROOT / "tools" / "run_mr_integration_bridge_harness.ps1"
WRAPPER = ROOT / "tools" / "run_mr_integration_bridge.py"


class _FakeConn:
    """In-memory socket stand-in: recv() drains a byte buffer, sendall() captures."""

    def __init__(self, data: bytes = b"") -> None:
        self._buf = bytearray(data)
        self.sent = bytearray()

    def feed(self, data: bytes) -> None:
        self._buf.extend(data)

    def recv(self, size: int) -> bytes:
        if not self._buf:
            return b""
        take = min(size, len(self._buf))
        chunk = bytes(self._buf[:take])
        del self._buf[:take]
        return chunk

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)


class TransportClientPrimitivesTests(unittest.TestCase):
    def test_masked_text_frame_decodes_back(self):
        frame = encode_masked_text_frame("hello-世界")
        opcode, payload = decode_websocket_frame(frame)
        self.assertEqual(opcode, 0x1)
        self.assertEqual(payload, "hello-世界")
        # Client frames must set the mask bit.
        self.assertTrue(frame[1] & 0x80)

    def test_read_server_text_frame_reads_unmasked_text(self):
        conn = _FakeConn(encode_websocket_text_frame("{\"a\":1}"))
        self.assertEqual(read_server_text_frame(conn), "{\"a\":1}")

    def test_read_server_text_frame_close_returns_none(self):
        conn = _FakeConn(encode_websocket_control_frame(0x8))
        self.assertIsNone(read_server_text_frame(conn))

    def test_read_server_text_frame_ping_answers_pong(self):
        conn = _FakeConn(encode_websocket_control_frame(0x9, b"hi"))
        self.assertEqual(read_server_text_frame(conn), "")
        # A masked pong (opcode 0xA) must have been sent back.
        self.assertTrue(conn.sent)
        self.assertEqual(conn.sent[0] & 0x0F, 0xA)
        self.assertTrue(conn.sent[1] & 0x80)


class RequestGateTests(unittest.TestCase):
    def test_accepts_proxy_targets_path(self):
        self.assertTrue(bridge.is_proxy_targets_request("GET /proxy_targets HTTP/1.1"))
        self.assertTrue(bridge.is_proxy_targets_request("GET /proxy_targets?x=1 HTTP/1.1"))

    def test_rejects_other_paths(self):
        self.assertFalse(bridge.is_proxy_targets_request("GET /tracking_raw HTTP/1.1"))
        self.assertFalse(bridge.is_proxy_targets_request("garbage"))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _read_proxy_targets(url: str, min_packets: int, timeout_seconds: float) -> list[dict]:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    messages: list[dict] = []
    deadline = time.monotonic() + timeout_seconds
    with socket.create_connection((host, port), timeout=timeout_seconds) as conn:
        conn.settimeout(max(0.1, timeout_seconds))
        client_handshake(conn, host, port, path)
        conn.sendall(
            encode_masked_text_frame(
                json.dumps({"type": "subscribe", "stream": "proxy_targets"}, separators=(",", ":"))
            )
        )
        while len(messages) < min_packets and time.monotonic() < deadline:
            conn.settimeout(max(0.1, deadline - time.monotonic()))
            payload = read_server_text_frame(conn)
            if payload is None:
                break
            if payload == "":
                continue
            messages.append(json.loads(payload))
    return messages


class BridgeEndToEndTests(unittest.TestCase):
    def test_c1_publisher_through_bridge_to_card(self):
        c1_port = _free_port()
        proxy_port = _free_port()

        make_source = pub.make_detection_jsonl_source(FIXTURE, loop=True)
        c1_server = threading.Thread(
            target=pub.serve,
            kwargs=dict(host="127.0.0.1", port=c1_port, make_source=make_source, hz=400.0, log_every=0),
            daemon=True,
        )
        c1_server.start()

        c1_url = f"ws://127.0.0.1:{c1_port}/tracking_raw"
        bridge_server = threading.Thread(
            target=bridge.serve,
            kwargs=dict(host="127.0.0.1", port=proxy_port, c1_url=c1_url, log_every=0),
            daemon=True,
        )
        bridge_server.start()

        url = f"ws://127.0.0.1:{proxy_port}/proxy_targets"
        messages: list[dict] = []
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline and len(messages) < 40:
            try:
                messages = _read_proxy_targets(url, min_packets=40, timeout_seconds=8.0)
                break
            except (ConnectionRefusedError, ConnectionResetError):
                time.sleep(0.1)

        self.assertGreaterEqual(len(messages), 40, "bridge did not forward enough proxy_targets")
        # Every forwarded message is canonical C2 the Godot card accepts.
        for index, message in enumerate(messages):
            self.assertEqual(validate_proxy_targets(message), [], f"packet[{index}]")
            self.assertEqual(message["type"], "proxy_targets")
            self.assertTrue(message["targets"])
            self.assertTrue(message["cards"])
        # Converter re-stamps a contiguous C2 sequence starting at 0 (empty C1
        # frames are skipped, so C2 space stays contiguous).
        sequences = [m["sequence"] for m in messages]
        self.assertEqual(sequences[0], 0)
        self.assertTrue(all(b == a + 1 for a, b in zip(sequences, sequences[1:])), sequences)


class RunnerContractTests(unittest.TestCase):
    def test_harness_wires_publisher_bridge_monitor(self):
        src = HARNESS_PS1.read_text(encoding="utf-8")
        self.assertIn("smartxr.cli.tracking_raw_publisher", src)
        self.assertIn("smartxr.cli.mr_integration_bridge", src)
        self.assertIn("monitor_proxy_targets_live_stream.py", src)
        self.assertIn("/proxy_targets", src)
        self.assertIn("--c1-url", src)

    def test_wrapper_reuses_cli_main(self):
        src = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("from smartxr.cli.mr_integration_bridge import main", src)


if __name__ == "__main__":
    unittest.main()
