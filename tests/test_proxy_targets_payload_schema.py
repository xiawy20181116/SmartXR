import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools" / "validate_proxy_targets_payload_schema.py"
PUBLISHER = ROOT / "tools" / "fake_proxy_targets_publisher.py"
SAMPLE = ROOT / "godot-android" / "fixtures" / "proxy_targets_sample.json"
VST_SAMPLE = ROOT / "godot-android" / "fixtures" / "vst_proxy_targets_sample.json"
CONTRACT = ROOT / "docs" / "proxy_targets_payload_contract.md"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ProxyTargetsPayloadSchemaTests(unittest.TestCase):
    def test_fake_publisher_output_matches_canonical_proxy_targets_schema(self):
        validator = load_module(VALIDATOR, "validate_proxy_targets_payload_schema")
        publisher = load_module(PUBLISHER, "fake_proxy_targets_publisher")

        message = publisher.build_proxy_targets_message(0.25, sequence=42)

        self.assertEqual(validator.validate_message(message), [])

    def test_fixture_and_vst_normalized_sample_match_same_schema(self):
        validator = load_module(VALIDATOR, "validate_proxy_targets_payload_schema")

        for path in [SAMPLE, VST_SAMPLE]:
            message = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                self.assertEqual(validator.validate_message(message), [])

    def test_rejects_raw_vst_detection_fields_before_godot_consumer(self):
        validator = load_module(VALIDATOR, "validate_proxy_targets_payload_schema")

        raw_detection = {
            "type": "proxy_targets",
            "schema_version": 1,
            "sequence": 1,
            "bbox": {"cx": 436, "cy": 326, "w": 160, "h": 220},
            "targets": [
                {
                    "target_id": "person-7",
                    "source": "vst",
                    "state": "tracked",
                    "confidence": 0.91,
                    "timestamp_ms": 1000,
                    "detection": {"class": "person"},
                    "transform": {
                        "position": [0.15, 0.0, -1.2],
                        "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                        "scale": [1.0, 1.0, 1.0],
                    },
                }
            ],
            "cards": [{"card_id": "CardAnchor", "target_id": "person-7"}],
        }

        errors = validator.validate_message(raw_detection)

        self.assertIn("raw source field not allowed at $.bbox", errors)
        self.assertIn("raw source field not allowed at $.targets[0].detection", errors)

    def test_contract_documents_vst_to_proxy_targets_boundary(self):
        source = CONTRACT.read_text(encoding="utf-8")

        self.assertIn("VST / external publisher boundary", source)
        self.assertIn("Godot consumer/adapter must not read bbox or detection", source)
        self.assertIn("replace the publisher", source)


if __name__ == "__main__":
    unittest.main()
