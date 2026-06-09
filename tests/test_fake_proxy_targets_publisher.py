import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "tools" / "fake_proxy_targets_publisher.py"


def load_publisher_module():
    spec = importlib.util.spec_from_file_location("fake_proxy_targets_publisher", PUBLISHER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeProxyTargetsPublisherTests(unittest.TestCase):
    def test_builds_moving_proxy_targets_message_without_raw_fields(self):
        publisher = load_publisher_module()

        first = publisher.build_proxy_targets_message(0.0, sequence=7)
        second = publisher.build_proxy_targets_message(1.0, sequence=8)

        self.assertEqual(first["type"], "proxy_targets")
        self.assertEqual(first["schema_version"], 1)
        self.assertEqual(first["sequence"], 7)
        self.assertEqual(second["sequence"], 8)
        self.assertEqual(first["cards"][0]["card_id"], "CardAnchor")
        self.assertEqual(first["cards"][0]["target_id"], first["targets"][0]["target_id"])
        self.assertNotEqual(first["targets"][0]["transform"]["position"], second["targets"][0]["transform"]["position"])
        serialized = json.dumps(first)
        self.assertNotIn("bbox", serialized)
        self.assertNotIn("detection", serialized)

    def test_encodes_unmasked_server_text_frame(self):
        publisher = load_publisher_module()

        self.assertEqual(publisher.encode_websocket_text_frame("ok"), b"\x81\x02ok")

    def test_decodes_masked_client_text_frame(self):
        publisher = load_publisher_module()

        mask = bytes([1, 2, 3, 4])
        payload = b'{"type":"subscribe"}'
        masked_payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        opcode, decoded = publisher.decode_websocket_frame(bytes([0x81, 0x80 | len(payload)]) + mask + masked_payload)

        self.assertEqual(opcode, 0x1)
        self.assertEqual(decoded, '{"type":"subscribe"}')

    def test_can_build_static_proxy_target_for_ab_validation(self):
        publisher = load_publisher_module()

        first = publisher.build_proxy_targets_message(0.0, sequence=1, mode="static")
        second = publisher.build_proxy_targets_message(1.0, sequence=2, mode="static")

        self.assertEqual(first["targets"][0]["transform"]["position"], second["targets"][0]["transform"]["position"])
        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 2)

    def test_server_status_logs_flush_immediately(self):
        source = PUBLISHER.read_text(encoding="utf-8")

        self.assertIn("proxy_targets fake publisher listening", source)
        self.assertIn("flush=True", source)


if __name__ == "__main__":
    unittest.main()
