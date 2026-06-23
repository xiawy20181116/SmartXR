from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRAGMENT = ROOT / "godot-android" / "scripts" / "proxy_targets_status_fragment.gd"
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
CARD_RECEIVER = ROOT / "godot-android" / "scripts" / "card_receiver.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_proxy_targets_status_fragment_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_proxy_targets_status_fragment_probe.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DOC = ROOT / "docs" / "gdscript_probes_ci.md"


class GodotProxyTargetsStatusFragmentTests(unittest.TestCase):
    def test_fragment_is_dependency_free_diagnostics_store(self):
        source = FRAGMENT.read_text(encoding="utf-8")

        self.assertIn("extends RefCounted", source)
        self.assertIn("class_name ProxyTargetsStatusFragment", source)
        self.assertIn("var _parsed_messages := 0", source)
        self.assertIn("var _last_sequence := -1", source)
        self.assertIn("var _last_position := Vector3.ZERO", source)
        self.assertIn('var _last_packet_preview := "-"', source)
        self.assertIn('var _last_message_type := "-"', source)
        self.assertIn('var _last_error := "-"', source)
        self.assertIn("var _last_source_coordinate := {}", source)
        self.assertIn("func set_packet_preview(preview: String) -> void:", source)
        self.assertIn("func set_error(error: String) -> void:", source)
        self.assertIn("func set_message_type(message_type: String) -> void:", source)
        self.assertIn("func record_parsed_message(message: Dictionary, head_info: Dictionary = {}) -> void:", source)
        self.assertIn("func status_values(runtime_values: Dictionary) -> Dictionary:", source)
        self.assertIn("static func proxy_target_count(targets) -> int:", source)
        self.assertIn("static func proxy_target_ids(targets) -> Array:", source)
        self.assertIn("static func vector3_from_status_array(value, fallback: Vector3) -> Vector3:", source)
        self.assertNotIn("preload(", source)
        self.assertNotIn("OS.get_environment", source)
        self.assertNotIn("get_tree()", source)
        self.assertNotIn("ProxyTargetsStatusFragment.new()", source)
        self.assertNotIn(": ProxyTargetsStatusFragment", source)

    def test_moving_card_delegates_proxy_diagnostics_to_fragment(self):
        card = SCRIPT.read_text(encoding="utf-8")
        receiver = CARD_RECEIVER.read_text(encoding="utf-8")

        self.assertIn('const ProxyTargetsStatusFragmentScript := preload("res://scripts/proxy_targets_status_fragment.gd")', card)
        self.assertIn("var _proxy_targets_status_fragment = ProxyTargetsStatusFragmentScript.new()", card)
        self.assertIn('"status_fragment": _proxy_targets_status_fragment', card)
        self.assertIn("_status_fragment.set_packet_preview(", receiver)
        self.assertIn("_status_fragment.set_error(", receiver)
        self.assertIn("_status_fragment.set_message_type(", receiver)
        self.assertIn("_status_fragment.record_parsed_message(message, head_info)", receiver)
        self.assertIn("func _proxy_targets_head_to_world_info() -> Dictionary:", card)
        self.assertIn("ProxyTargetsStatusFragmentScript.proxy_target_count(_proxy_targets_proxy_dictionary())", card)
        self.assertIn("ProxyTargetsStatusFragmentScript.proxy_target_ids(_proxy_targets_proxy_dictionary())", card)
        self.assertIn("_card_receiver.status_values({", card)
        self.assertIn("_status_fragment.status_values({", receiver)
        self.assertNotIn("func _record_proxy_targets_diagnostics", card)
        self.assertNotIn("func _record_proxy_targets_head_to_world_diagnostics", card)
        self.assertNotIn("func _vector3_from_status_array", card)

    def test_runtime_probe_runner_and_ci_docs_exist(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        doc = DOC.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        self.assertIn('OS.get_environment("SMARTXR_PROXY_TARGETS_STATUS_FRAGMENT_SCRIPT")', probe)
        self.assertIn("SMARTXR_PROXY_TARGETS_STATUS_FRAGMENT_PROBE_STATUS_PATH", probe)
        self.assertIn("records_message_diagnostics", probe)
        self.assertIn("records_head_to_world_info", probe)
        self.assertIn("valid_target_without_head_info_resets_head_flag", probe)
        self.assertIn("proxy_ids_are_sorted", probe)
        self.assertIn("status_values_preserve_contract", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_PROXY_TARGETS_STATUS_FRAGMENT_SCRIPT", runner)
        self.assertIn("tools/run_godot_proxy_targets_status_fragment_probe.ps1", workflow)
        self.assertIn("tools/run_godot_proxy_targets_status_fragment_probe.ps1", doc)


if __name__ == "__main__":
    unittest.main()
