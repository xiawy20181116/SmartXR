from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = ROOT / "godot-android" / "scripts" / "command_dispatcher.gd"
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_command_dispatcher_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_command_dispatcher_probe.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DOC = ROOT / "docs" / "gdscript_probes_ci.md"


class GodotCommandDispatcherTests(unittest.TestCase):
    def test_command_dispatcher_is_dependency_free_state_reducer(self):
        source = DISPATCHER.read_text(encoding="utf-8")

        self.assertIn("extends RefCounted", source)
        self.assertIn("class_name CommandDispatcher", source)
        self.assertIn("const EFFECT_APPLY_BBOX_ANCHOR := \"apply_bbox_anchor\"", source)
        self.assertIn("const EFFECT_APPLY_3DOF_ANCHOR := \"apply_3dof_anchor\"", source)
        self.assertIn("const EFFECT_DEBUG_TARGET_FREE := \"debug_target_free\"", source)
        self.assertIn("const EFFECT_DEBUG_TARGET_RESET := \"debug_target_reset\"", source)
        self.assertIn("const EFFECT_RESET_PROXY_WORLD_LATCHES := \"reset_proxy_world_latches\"", source)
        self.assertIn("static func default_state(config: Dictionary) -> Dictionary:", source)
        self.assertIn("static func apply_command(state: Dictionary, command: String, config: Dictionary) -> Dictionary:", source)
        self.assertIn('next_state["last_command"] = command', source)
        self.assertIn('next_state["effects"] = effects', source)
        self.assertIn('"yaw_left", "left", "move_left", "a":', source)
        self.assertIn('"bbox_depth_out":', source)
        self.assertIn('"reset_proxy_world_latch", "reset_world_anchor", "world_latch_reset":', source)
        self.assertIn('"reset", "r":', source)
        self.assertNotIn("preload(", source)
        self.assertNotIn("OS.get_environment", source)
        self.assertNotIn("get_tree()", source)
        self.assertNotIn("CommandDispatcher.new()", source)
        self.assertNotIn(": CommandDispatcher", source)

    def test_moving_card_delegates_command_state_to_dispatcher(self):
        card = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('const CommandDispatcherScript := preload("res://scripts/command_dispatcher.gd")', card)
        self.assertIn("var _command_dispatcher_config := CommandDispatcherScript.default_config()", card)
        self.assertIn("var next_state: Dictionary = CommandDispatcherScript.apply_command(", card)
        self.assertIn("func _command_state() -> Dictionary:", card)
        self.assertIn("func _apply_command_state(next_state: Dictionary) -> void:", card)
        self.assertIn("func _run_command_effects(effects: Array) -> void:", card)
        self.assertIn('CommandDispatcherScript.EFFECT_APPLY_BBOX_ANCHOR:', card)
        self.assertIn('CommandDispatcherScript.EFFECT_DEBUG_TARGET_RESET:', card)
        self.assertIn('CommandDispatcherScript.EFFECT_RESET_PROXY_WORLD_LATCHES:', card)
        self.assertIn("_reset_proxy_world_latches()", card)
        self.assertNotIn('match command:\n\t\t"yaw_left"', card)

    def test_runtime_probe_runner_and_ci_docs_exist(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        doc = DOC.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        self.assertIn('OS.get_environment("SMARTXR_COMMAND_DISPATCHER_SCRIPT")', probe)
        self.assertIn("SMARTXR_COMMAND_DISPATCHER_PROBE_STATUS_PATH", probe)
        self.assertIn("func _process(_delta: float) -> bool:", probe)
        self.assertIn("yaw_aliases_switch_to_manual", probe)
        self.assertIn("depth_clamps_to_min_and_max", probe)
        self.assertIn("bbox_commands_request_bbox_anchor", probe)
        self.assertIn("toggle_bbox_mode_requests_bbox_anchor_only_when_entering_bbox", probe)
        self.assertIn("reset_restores_defaults_and_requests_3dof", probe)
        self.assertIn("reset_proxy_world_latch_returns_latch_effect", probe)
        self.assertIn("debug_commands_return_side_effects", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_COMMAND_DISPATCHER_SCRIPT", runner)
        self.assertIn("tools/run_godot_command_dispatcher_probe.ps1", workflow)
        self.assertIn("tools/run_godot_command_dispatcher_probe.ps1", doc)


if __name__ == "__main__":
    unittest.main()
