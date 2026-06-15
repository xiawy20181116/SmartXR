from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
SUBSYSTEM = ROOT / "godot-android" / "scripts" / "vst_debug_ui.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_vst_debug_ui_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_vst_debug_ui_probe.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
TASKS = ROOT / "TASKS.md"
DECISIONS = ROOT / "DECISIONS.md"
HANDOFF = ROOT / "HANDOFF.md"
DOC = ROOT / "docs" / "vst_debug_ui.md"


class GodotVSTDebugUITests(unittest.TestCase):
    def test_vst_debug_ui_subsystem_owns_scene_nodes_and_overlay_updates(self):
        source = SUBSYSTEM.read_text(encoding="utf-8")

        self.assertIn("extends RefCounted", source)
        self.assertIn("class_name VSTDebugUI", source)
        self.assertNotIn("VSTDebugUI.new()", source)
        self.assertNotIn(": VSTDebugUI", source)
        self.assertNotIn("preload(", source)
        self.assertNotIn("get_tree()", source)

        for marker in [
            "func build_world_bbox_frame(parent: Node3D) -> void:",
            "func build_raw_debug_panel(camera: Node3D) -> void:",
            "func update_world_bbox_frame(anchor_position: Vector3, anchor_depth_m: float, angular_size_deg: Vector2, orient_to_camera: Callable) -> void:",
            "func update_raw_image(right_img: Image, image_size: Vector2) -> void:",
            "func update_raw_bbox_overlay(boxes: PackedFloat32Array, image_size: Vector2) -> void:",
            "func set_world_bbox_visible(visible: bool) -> void:",
            "func set_raw_bbox_visible(visible: bool) -> void:",
        ]:
            self.assertIn(marker, source)

        for marker in [
            "VSTBBoxFrame",
            "VSTRawDebugPanel",
            "VSTRawRightImage",
            "VSTRawBBox",
            "VSTRawDebugLabel",
            "ImageTexture.create_from_image",
        ]:
            self.assertIn(marker, source)

    def test_moving_card_delegates_vst_debug_ui_and_keeps_public_api(self):
        card = CARD.read_text(encoding="utf-8")

        self.assertIn('const VSTDebugUIScript := preload("res://scripts/vst_debug_ui.gd")', card)
        self.assertIn("var _vst_debug_ui = VSTDebugUIScript.new(", card)
        self.assertIn("_vst_debug_ui.build_raw_debug_panel(_camera)", card)
        self.assertIn("_vst_debug_ui.build_world_bbox_frame(self)", card)
        self.assertIn("_vst_debug_ui.update_raw_image(right_img, image_size)", card)
        self.assertIn("_vst_debug_ui.update_raw_bbox_overlay(boxes, image_size)", card)
        self.assertIn("_vst_debug_ui.update_world_bbox_frame(", card)
        self.assertIn("func update_vst_target(target_id: String, transform: Transform3D, confidence: float, timestamp_ms: float) -> bool:", card)
        self.assertIn("func register_node3d_target(target_id: String, node_or_path) -> bool:", card)
        self.assertIn("func attach_to_target(card_id: String, target_id: String, offset_rule = {}) -> bool:", card)

        for removed in [
            "var _vst_bbox_frame_anchor: Node3D = null",
            "var _vst_bbox_frame_parts: Array[MeshInstance3D] = []",
            "var _vst_raw_debug_anchor: Node3D = null",
            "var _vst_raw_right_sprite: Sprite3D = null",
            "var _vst_raw_bbox_parts: Array[MeshInstance3D] = []",
            "func _build_vst_bbox_frame() -> void:",
            "func _build_vst_raw_debug_panel() -> void:",
            "func _configure_vst_bbox_frame_part(part: MeshInstance3D, size: Vector2, position: Vector3) -> void:",
            "func _set_vst_raw_bbox_visible(visible: bool) -> void:",
        ]:
            self.assertNotIn(removed, card)

    def test_runtime_probe_runner_ci_and_docs_are_registered(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        self.assertIn('OS.get_environment("SMARTXR_VST_DEBUG_UI_SCRIPT")', probe)
        self.assertIn("SMARTXR_VST_DEBUG_UI_PROBE_STATUS_PATH", probe)
        self.assertIn("world_bbox_frame_updates", probe)
        self.assertIn("raw_bbox_overlay_updates", probe)
        self.assertIn("raw_image_texture_updates", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_VST_DEBUG_UI_SCRIPT", runner)
        self.assertIn("tools/run_godot_vst_debug_ui_probe.ps1", workflow)

        for path in (TASKS, DECISIONS, HANDOFF, DOC):
            text = path.read_text(encoding="utf-8")
            self.assertIn("VSTDebugUI", text)

    def test_android_moving_card_is_orchestration_sized_after_ui_extraction(self):
        lines = CARD.read_text(encoding="utf-8").splitlines()
        non_empty_lines = [line for line in lines if line.strip()]
        self.assertLess(len(non_empty_lines), 1000)
        self.assertLessEqual(len(re.findall(r"^func ", "\n".join(lines), flags=re.M)), 84)


if __name__ == "__main__":
    unittest.main()
