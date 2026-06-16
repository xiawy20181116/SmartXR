import json
from pathlib import Path
import unittest

from smartxr.card_lifecycle_schema import validate_message
from smartxr.card_lifecycle_fakes import (
    CardLifecycleConsumer,
    build_fake_card_lifecycle_message,
)


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "godot-android" / "fixtures" / "card_lifecycle_sample.json"
CONTRACT = ROOT / "docs" / "card_lifecycle_payload_contract.md"


class CardLifecyclePayloadSchemaTests(unittest.TestCase):
    def test_fake_producer_output_matches_canonical_schema(self):
        message = build_fake_card_lifecycle_message(sequence=2, timestamp_ms=10.0)
        self.assertEqual(validate_message(message), [])

    def test_fixture_matches_schema(self):
        message = json.loads(SAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(validate_message(message), [])

    def test_rejects_command_card_state_mismatch(self):
        message = build_fake_card_lifecycle_message()
        message["commands"][0]["command"] = "attach"
        message["commands"][0]["card_state"] = "expand"  # attach must be appear
        errors = validate_message(message)
        self.assertTrue(any("for command 'attach'" in e for e in errors))

    def test_rejects_unknown_command_and_card_state(self):
        message = build_fake_card_lifecycle_message()
        message["commands"][0]["command"] = "teleport"
        message["commands"][0]["card_state"] = "wiggle"
        errors = validate_message(message)
        self.assertTrue(any("command must be one of" in e for e in errors))
        self.assertTrue(any("card_state must be one of" in e for e in errors))

    def test_fake_producer_to_fake_consumer_round_trip(self):
        consumer = CardLifecycleConsumer()
        message = build_fake_card_lifecycle_message(sequence=0, timestamp_ms=0.0)
        wire = json.loads(json.dumps(message))
        self.assertTrue(consumer.consume(wire))
        self.assertEqual(consumer.commands_accepted, 5)
        self.assertEqual(consumer.commands_rejected, 0)
        # after detach/disappear the card is back to detached and re-attachable
        self.assertEqual(consumer.current_state("CardAnchor"), "detached")

    def test_consumer_rejects_illegal_transition(self):
        consumer = CardLifecycleConsumer()
        # contract -> expand is legal, but appear -> contract is not
        illegal = {
            "type": "card_lifecycle",
            "schema_version": 1,
            "sequence": 0,
            "timestamp_ms": 0.0,
            "commands": [
                {"card_id": "CardAnchor", "target_id": "person-7", "command": "attach", "card_state": "appear"},
                {"card_id": "CardAnchor", "target_id": "person-7", "command": "update", "card_state": "contract"},
            ],
        }
        self.assertFalse(consumer.consume(illegal))
        self.assertEqual(consumer.commands_accepted, 1)
        self.assertEqual(consumer.commands_rejected, 1)
        self.assertTrue(any("illegal transition appear -> contract" in e for e in consumer.errors))

    def test_consumer_rejects_update_before_attach(self):
        consumer = CardLifecycleConsumer()
        message = {
            "type": "card_lifecycle",
            "schema_version": 1,
            "sequence": 0,
            "timestamp_ms": 0.0,
            "commands": [
                {"card_id": "Lonely", "target_id": "person-1", "command": "update", "card_state": "expand"},
            ],
        }
        self.assertFalse(consumer.consume(message))
        self.assertEqual(consumer.commands_rejected, 1)

    def test_contract_documents_c3_state_machine(self):
        source = CONTRACT.read_text(encoding="utf-8")
        self.assertIn("card_lifecycle", source)
        self.assertIn("appear", source)
        self.assertIn("disappear", source)
        self.assertIn("offset_rule", source)


if __name__ == "__main__":
    unittest.main()
