from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "godot-android" / "scripts" / "assistant" / "assistant_card_state.gd"
VIEW = ROOT / "godot-android" / "scripts" / "assistant" / "assistant_card_view.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_assistant_card_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_mr_assistant_card_probe.ps1"


class GodotMRAssistantCardTests(unittest.TestCase):
    def test_assistant_card_state_parses_payloads_and_exposes_snapshot(self):
        source = STATE.read_text(encoding="utf-8")

        self.assertIn("extends RefCounted", source)
        self.assertIn("class_name AssistantCardState", source)
        self.assertIn('const MESSAGE_TYPE := "assistant_card"', source)
        self.assertIn("const SCHEMA_VERSION := 1", source)
        self.assertIn("func apply_assistant_card_json(payload: String) -> bool:", source)
        self.assertIn("func apply_assistant_card_message(message: Dictionary) -> bool:", source)
        self.assertIn("func snapshot() -> Dictionary:", source)
        self.assertIn("func last_error() -> String:", source)
        self.assertIn("func _validate_message(message: Dictionary) -> String:", source)
        self.assertIn('message.get("type", "") != MESSAGE_TYPE', source)
        self.assertIn('str(message.get("card_id", "")).is_empty()', source)
        self.assertIn('str(message.get("target_id", "")).is_empty()', source)
        self.assertNotIn("get_tree()", source)
        self.assertNotIn("OS.get_environment", source)

    def test_assistant_card_view_renders_snapshot_into_label3d(self):
        source = VIEW.read_text(encoding="utf-8")

        self.assertIn("extends Node", source)
        self.assertIn("class_name AssistantCardView", source)
        self.assertIn("func build_card_label(parent: Node3D) -> Label3D:", source)
        self.assertIn('"AssistantCardLabel"', source)
        self.assertIn("func update_from_snapshot(snapshot: Dictionary) -> void:", source)
        self.assertIn('"Assistant"', source)
        self.assertIn('snapshot.get("assistant_state", "idle")', source)
        self.assertIn('snapshot.get("response_text", "")', source)
        self.assertIn('tool_summary.get("status_line", "")', source)
        self.assertNotIn("OS.get_environment", source)

    def test_script_only_probe_and_runner_exist(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        self.assertIn('OS.get_environment("SMARTXR_ASSISTANT_CARD_STATE_SCRIPT")', probe)
        self.assertIn('OS.get_environment("SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT")', probe)
        self.assertIn("SMARTXR_ASSISTANT_CARD_PROBE_STATUS_PATH", probe)
        self.assertIn("func _process(_delta: float) -> bool:", probe)
        self.assertIn("valid_payload_updates_snapshot", probe)
        self.assertIn("invalid_payload_sets_error", probe)
        self.assertIn("view_renders_response_text", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_ASSISTANT_CARD_STATE_SCRIPT", runner)
        self.assertIn("SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT", runner)


if __name__ == "__main__":
    unittest.main()
