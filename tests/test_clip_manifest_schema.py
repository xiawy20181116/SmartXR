import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools" / "validate_clip_manifest_schema.py"
MANIFEST = ROOT / "docs" / "capture_clip_manifest.json"
CONTRACT = ROOT / "docs" / "capture_clip_manifest.md"

EXPECTED_SESSIONS = [
    "capture_20260415T055846Z",
    "capture_20260415T062913Z",
    "capture_20260415T063047Z",
    "capture_20260415T063848Z",
    "capture_20260415T065340Z",
    "capture_20260417T073836Z",
]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ClipManifestSchemaTests(unittest.TestCase):
    def test_committed_manifest_validates_and_labels_six_t1_sessions(self):
        self.assertTrue(VALIDATOR.exists(), "clip manifest validator is missing")
        self.assertTrue(MANIFEST.exists(), "clip manifest fixture is missing")
        validator = load_module(VALIDATOR, "validate_clip_manifest_schema")

        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(validator.validate_manifest(manifest), [])

        clips = manifest["clips"]
        self.assertEqual([clip["session_id"] for clip in clips], EXPECTED_SESSIONS)
        self.assertTrue(all(clip["tier"] == "T1" for clip in clips))

        for clip in clips:
            with self.subTest(session=clip["session_id"]):
                labels = clip["labels"]
                self.assertEqual(
                    set(labels),
                    {"scene", "people", "distance", "motion", "lighting", "entry_exit"},
                )
                self.assertIn("sampled_count_histogram", labels["people"])
                self.assertGreaterEqual(labels["people"]["max_sampled_count"], 1)

    def test_rejects_missing_clip_labels_and_bad_tier(self):
        validator = load_module(VALIDATOR, "validate_clip_manifest_schema")
        manifest = {
            "type": "capture_clip_manifest",
            "schema_version": 1,
            "source_package": {"package_id": "pkg", "source_manifest": "CAPTURE_PACKAGE_MANIFEST.json"},
            "clips": [{"session_id": "capture_bad", "tier": "T4", "labels": {}}],
        }

        errors = validator.validate_manifest(manifest)

        self.assertIn("$.clips[0].tier must be one of ['T0', 'T1', 'T2', 'T3']", errors)
        self.assertIn("$.clips[0].labels.scene is required", errors)
        self.assertIn("$.clips[0].labels.entry_exit is required", errors)

    def test_contract_documents_tiers_and_t3_gate(self):
        self.assertTrue(CONTRACT.exists(), "clip manifest contract doc is missing")
        source = CONTRACT.read_text(encoding="utf-8")

        for tier in ["T0", "T1", "T2", "T3"]:
            self.assertIn(tier, source)
        self.assertIn("T3 gate", source)
        self.assertIn("2D bbox + id", source)
        self.assertIn("3D ground truth", source)
        self.assertIn("tracking_raw_replay_c1.jsonl", source)


if __name__ == "__main__":
    unittest.main()
