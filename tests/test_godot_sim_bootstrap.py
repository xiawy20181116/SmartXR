from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SIM_BOOTSTRAP = ROOT / "godot-android" / "scripts" / "sim_bootstrap.gd"
CARD = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
STATUS_HUD = ROOT / "godot-android" / "scripts" / "status_hud.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_sim_bootstrap_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_sim_bootstrap_probe.ps1"
SIM_RUNNER = ROOT / "tools" / "run_desktop_sim.ps1"
DOCS = ROOT / "docs" / "smartxr_options.md"


class GodotSimBootstrapTests(unittest.TestCase):
    def test_sim_bootstrap_forces_non_xr_and_moves_fallback_camera(self):
        source = SIM_BOOTSTRAP.read_text(encoding="utf-8")

        self.assertIn("extends RefCounted", source)
        self.assertIn("class_name SimBootstrap", source)
        self.assertNotIn("SimBootstrap.new()", source)
        self.assertNotIn(": SimBootstrap", source)
        self.assertIn("func apply_to_xr_bootstrap(xr_bootstrap) -> void:", source)
        self.assertIn("xr_bootstrap.set_interface_provider(func(): return null)", source)
        self.assertIn("func bind_camera(camera: Camera3D) -> void:", source)
        self.assertIn("func handle_input(event: InputEvent) -> void:", source)
        self.assertIn("func update(delta: float) -> void:", source)
        self.assertIn("Input.is_key_pressed(KEY_W)", source)
        self.assertIn("Input.is_key_pressed(KEY_S)", source)
        self.assertIn("Input.is_key_pressed(KEY_A)", source)
        self.assertIn("Input.is_key_pressed(KEY_D)", source)
        self.assertIn("InputEventMouseMotion", source)
        self.assertIn("func status_snapshot() -> Dictionary:", source)
        self.assertIn('"enabled": true', source)
        self.assertIn('"mode": "desktop_sim"', source)

    def test_sim_bootstrap_builds_stereo_eye_preview(self):
        source = SIM_BOOTSTRAP.read_text(encoding="utf-8")

        self.assertIn("const DEFAULT_IPD_M := 0.064", source)
        self.assertIn("const DEFAULT_STEREO_FOV_DEG := 70.0", source)
        self.assertIn("var ipd_m := DEFAULT_IPD_M", source)
        self.assertIn("var stereo_fov_deg := DEFAULT_STEREO_FOV_DEG", source)
        self.assertIn("var _left_eye_camera: Camera3D = null", source)
        self.assertIn("var _right_eye_camera: Camera3D = null", source)
        self.assertIn("func build_stereo_preview(owner: Node, source_viewport: Viewport) -> void:", source)
        self.assertIn("CanvasLayer.new()", source)
        self.assertIn("HBoxContainer.new()", source)
        self.assertIn("SubViewport.new()", source)
        self.assertIn("TextureRect.new()", source)
        self.assertIn("Label.new()", source)
        self.assertIn("Control.MOUSE_FILTER_IGNORE", source)
        self.assertIn('"LEFT"', source)
        self.assertIn('"RIGHT"', source)
        self.assertIn('"LeftEyeViewport"', source)
        self.assertIn('"RightEyeViewport"', source)
        self.assertIn('"LeftEyeCamera"', source)
        self.assertIn('"RightEyeCamera"', source)
        self.assertIn("func _sync_stereo_eye_transforms() -> void:", source)
        self.assertIn("Vector3(-ipd_m * 0.5, 0.0, 0.0)", source)
        self.assertIn("Vector3(ipd_m * 0.5, 0.0, 0.0)", source)
        self.assertIn("PROJECTION_PERSPECTIVE", source)
        self.assertIn("current = true", source)

    def test_moving_card_wires_sim_mode_through_snapshot_without_replacing_card_logic(self):
        card = CARD.read_text(encoding="utf-8")

        self.assertIn('const SimBootstrapScript := preload("res://scripts/sim_bootstrap.gd")', card)
        self.assertIn('const SIM_MODE_ENV := "SMARTXR_SIM_MODE"', card)
        self.assertIn("var _sim_bootstrap = SimBootstrapScript.new()", card)
        self.assertIn("var _sim_enabled := false", card)
        self.assertIn("func _sim_mode_enabled() -> bool:", card)
        self.assertIn("_sim_enabled = _sim_mode_enabled()", card)
        self.assertIn("_sim_bootstrap.apply_to_xr_bootstrap(_xr_bootstrap)", card)
        self.assertIn("_sim_bootstrap.bind_camera(_camera)", card)
        self.assertIn("_sim_bootstrap.build_stereo_preview(self, get_viewport())", card)
        self.assertIn("func _unhandled_input(event: InputEvent) -> void:", card)
        self.assertIn("_sim_bootstrap.handle_input(event)", card)
        self.assertIn("_sim_bootstrap.update(delta)", card)
        self.assertIn('"sim": _build_sim_status_snapshot()', card)
        self.assertIn("func _build_sim_status_snapshot() -> Dictionary:", card)
        self.assertIn('return {"enabled": false}', card)
        self.assertIn("func _setup_xr_bootstrap() -> void:", card)
        self.assertIn("func _setup_camera() -> void:", card)
        self.assertIn("func _build_status_snapshot() -> Dictionary:", card)
        # The simulator reuses the card scene/script instead of copying UI or
        # card-anchor logic.
        self.assertEqual(card.count("func _make_card_ui() -> Control:"), 1)

    def test_sim_mode_anchors_card_in_head_space_to_avoid_mouse_look_distortion(self):
        card = CARD.read_text(encoding="utf-8")

        self.assertIn("func _anchor_position_from_yaw_pitch_depth() -> Vector3:", card)
        self.assertIn("func _local_anchor_position_from_yaw_pitch_depth() -> Vector3:", card)
        self.assertIn("var local_anchor_position := _local_anchor_position_from_yaw_pitch_depth()", card)
        self.assertIn("if _sim_enabled and _camera != null:", card)
        self.assertIn("return _camera.global_transform * local_anchor_position", card)
        self.assertLess(
            card.index("var local_anchor_position := _local_anchor_position_from_yaw_pitch_depth()"),
            card.index("return _camera.global_transform * local_anchor_position"),
        )

    def test_sim_mode_applies_card_transform_from_head_basis_to_preserve_shape(self):
        card = CARD.read_text(encoding="utf-8")

        self.assertIn("func _apply_sim_3dof_anchor_transform(node: Node3D) -> bool:", card)
        self.assertIn("var head_basis := _camera.global_transform.basis.orthonormalized()", card)
        self.assertIn("var local_anchor_position := _local_anchor_position_from_yaw_pitch_depth()", card)
        self.assertIn("node.global_transform = Transform3D(", card)
        self.assertIn("head_basis,", card)
        self.assertIn("_camera.global_transform * local_anchor_position", card)
        self.assertIn("if _apply_sim_3dof_anchor_transform(_card_anchor):", card)
        self.assertIn("if _apply_sim_3dof_anchor_transform(_vst_bbox_frame_anchor):", card)

    def test_status_hud_displays_sim_mode_from_snapshot_without_status_file_shape_change(self):
        source = STATUS_HUD.read_text(encoding="utf-8")

        self.assertIn("var sim_line := _format_sim_status_line(snapshot.get(\"sim\", {}))", source)
        self.assertIn("func _format_sim_status_line(sim: Dictionary) -> String:", source)
        self.assertIn('"SIM: mode=%s pos=%s rot=%s speed=%.1f"', source)
        self.assertIn("sim_line,", source)
        # Status file JSON remains the existing proxy_targets and passthrough
        # contracts; sim mode is HUD-only.
        self.assertNotIn('"sim"', source[source.index("func _write_proxy_targets_status_file"):source.index("func _write_passthrough_overlay_status_file")])
        self.assertNotIn('"sim"', source[source.index("func _write_passthrough_overlay_status_file"):source.index("func _format_xr_status_line")])

    def test_runtime_probe_runner_desktop_runner_and_docs_exist(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        sim_runner = SIM_RUNNER.read_text(encoding="utf-8")
        docs = DOCS.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        self.assertIn('OS.get_environment("SMARTXR_SIM_BOOTSTRAP_SCRIPT")', probe)
        self.assertIn("force_non_xr_provider", probe)
        self.assertIn("mouse_motion_updates_rotation", probe)
        self.assertIn("status_snapshot_reports_desktop_sim", probe)
        self.assertIn("stereo_preview_builds_left_and_right_eye_viewports", probe)
        self.assertIn("stereo_preview_ignores_mouse_input", probe)
        self.assertIn("stereo_status_reports_ipd_and_eye_positions", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_SIM_BOOTSTRAP_SCRIPT", runner)
        self.assertIn("set_gxr_extension.ps1", sim_runner)
        self.assertIn("-Mode disable", sim_runner)
        self.assertIn('SMARTXR_SIM_MODE', sim_runner)
        self.assertIn('"--xr-mode", "off"', sim_runner)
        self.assertIn('"--path", $ProjectDir', sim_runner)
        self.assertIn("Desktop simulator", docs)
        self.assertIn("Stereo eye preview", docs)
        self.assertIn("left/right eye", docs)
        self.assertIn("IPD", docs)
        self.assertIn("--xr-mode off", docs)
        self.assertIn("tools\\run_desktop_sim.ps1", docs)
        self.assertIn("SMARTXR_SIM_MODE=1", docs)


if __name__ == "__main__":
    unittest.main()
