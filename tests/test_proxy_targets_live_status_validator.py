import importlib.util
import json
from pathlib import Path
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools" / "validate_proxy_targets_live_status.py"
TMP = ROOT / "tests" / "tmp"


def load_validator_module():
    spec = importlib.util.spec_from_file_location("validate_proxy_targets_live_status", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ProxyTargetsLiveStatusValidatorTests(unittest.TestCase):
    def test_requirement_checks_are_layered(self):
        validator = load_validator_module()

        status = {"packets": 3, "parsed": 0, "live": 0, "attachments": 0, "anchor_mode": "manual"}

        self.assertTrue(validator.requirement_met(status, "packets"))
        self.assertFalse(validator.requirement_met(status, "parsed"))
        self.assertFalse(validator.requirement_met(status, "live"))

        status["parsed"] = 2
        self.assertTrue(validator.requirement_met(status, "parsed"))
        self.assertFalse(validator.requirement_met(status, "live"))

        status["live"] = 1
        self.assertTrue(validator.requirement_met(status, "live"))
        self.assertFalse(validator.requirement_met(status, "attached"))

        status["attachments"] = 1
        status["anchor_mode"] = "target"
        status["card_target_id"] = "vst-person-1"
        self.assertFalse(validator.requirement_met(status, "attached"))

        status["card_attach_target_id"] = "vst-person-1"
        status["card_apply_count"] = 1
        status["proxy_target_count"] = 1
        status["proxy_target_ids"] = ["vst-person-1"]
        self.assertTrue(validator.requirement_met(status, "attached"))

    def test_load_status_reads_json_file(self):
        validator = load_validator_module()

        TMP.mkdir(parents=True, exist_ok=True)
        status_path = TMP / f"proxy_targets_live_status_{uuid.uuid4().hex}.json"
        status_path.write_text(json.dumps({"packets": 1, "error": "json_invalid"}), encoding="utf-8")
        try:
            status = validator.load_status(status_path)
        finally:
            status_path.unlink(missing_ok=True)

        self.assertEqual(status["packets"], 1)
        self.assertEqual(status["error"], "json_invalid")

    def test_default_status_path_points_to_demo_run_user_data(self):
        validator = load_validator_module()

        path = validator.default_status_path(appdata=Path("C:/Users/test/AppData/Roaming"))

        self.assertEqual(path, Path("C:/Users/test/AppData/Roaming/Godot/app_userdata/demo_run/proxy_targets_live_status.json"))


if __name__ == "__main__":
    unittest.main()
