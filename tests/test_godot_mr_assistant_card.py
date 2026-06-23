from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASE_STATE = ROOT / "godot-android" / "scripts" / "card_state_base.gd"
BASE_VIEW = ROOT / "godot-android" / "scripts" / "card_view_base.gd"
STATE = ROOT / "godot-android" / "scripts" / "assistant" / "assistant_card_state.gd"
VIEW = ROOT / "godot-android" / "scripts" / "assistant" / "assistant_card_view.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_assistant_card_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_mr_assistant_card_probe.ps1"


class GodotMRAssistantCardTests(unittest.TestCase):
    def test_assistant_card_state_parses_payloads_and_exposes_snapshot(self):
        base = BASE_STATE.read_text(encoding="utf-8")
        source = STATE.read_text(encoding="utf-8")

        self.assertIn("class_name CardStateBase", base)
        self.assertIn("func configure_card_state(data_source: String, initial_snapshot := {}) -> void:", base)
        self.assertIn("func update_snapshot(values: Dictionary) -> void:", base)
        self.assertIn("func snapshot() -> Dictionary:", base)
        self.assertIn('extends "../card_state_base.gd"', source)
        self.assertIn("class_name AssistantCardState", source)
        self.assertIn('const MESSAGE_TYPE := "assistant_card"', source)
        self.assertIn("const SCHEMA_VERSION := 1", source)
        self.assertIn("func apply_assistant_card_json(payload: String) -> bool:", source)
        self.assertIn("func apply_assistant_card_message(message: Dictionary) -> bool:", source)
        self.assertNotIn("func snapshot() -> Dictionary:", source)
        self.assertNotIn("func last_error() -> String:", source)
        self.assertIn("func _validate_message(message: Dictionary) -> String:", source)
        self.assertIn('message.get("type", "") != MESSAGE_TYPE', source)
        self.assertIn('str(message.get("card_id", "")).is_empty()', source)
        self.assertIn('str(message.get("target_id", "")).is_empty()', source)
        self.assertNotIn("get_tree()", source)
        self.assertNotIn("OS.get_environment", source)

    def test_assistant_card_view_renders_snapshot_into_label3d(self):
        base = BASE_VIEW.read_text(encoding="utf-8")
        source = VIEW.read_text(encoding="utf-8")

        self.assertIn("class_name CardViewBase", base)
        self.assertIn("func build_label3d(parent: Node3D, label_name: String, options := {}) -> Label3D:", base)
        self.assertIn("func format_snapshot_text(title: String, snapshot: Dictionary, fields: Array) -> String:", base)
        self.assertIn('extends "../card_view_base.gd"', source)
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
        self.assertIn("state_uses_shared_card_base", probe)
        self.assertIn("view_uses_shared_card_base", probe)
        self.assertIn("invalid_payload_sets_error", probe)
        self.assertIn("view_renders_response_text", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_ASSISTANT_CARD_STATE_SCRIPT", runner)
        self.assertIn("SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT", runner)


if __name__ == "__main__":
    unittest.main()
