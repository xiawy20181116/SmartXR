from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
ANDROID_ACTIVITY = (
    ROOT
    / "godot-android"
    / "android"
    / "build"
    / "src"
    / "main"
    / "java"
    / "com"
    / "godot"
    / "game"
    / "GodotApp.java"
)
GODOT_ANDROID = ROOT / "godot-android"


class GodotAndroidMeshCardTests(unittest.TestCase):
    def test_moving_card_uses_regular_mesh_card_anchor(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("OpenXRCompositionLayerQuad", source)
        self.assertIn('CARD_ANCHOR_NAME := "CardAnchor"', source)
        self.assertIn("MeshInstance3D.new()", source)
        self.assertIn("QuadMesh.new()", source)
        self.assertIn("StandardMaterial3D.new()", source)
        self.assertIn("albedo_texture = _card_viewport.get_texture()", source)

    def test_moving_card_reports_world_corners_for_real_device_validation(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("_corner_world_points()", source)
        self.assertIn("TL", source)
        self.assertIn("TR", source)
        self.assertIn("BL", source)
        self.assertIn("BR", source)

    def test_moving_card_defaults_to_fixed_world_orientation_with_toggle(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("var _face_camera_enabled := true", source)
        self.assertIn("_orient_card_for_3dof_reading()", source)
        self.assertIn("Face: 3DoF", source)
        self.assertIn("_card_anchor.rotation_degrees", source)

    def test_moving_card_uses_yaw_pitch_depth_anchor_model(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("CARD_START_YAW_DEG", source)
        self.assertIn("CARD_START_PITCH_DEG", source)
        self.assertIn("CARD_START_DEPTH_M", source)
        self.assertIn("var _anchor_yaw_deg", source)
        self.assertIn("var _anchor_pitch_deg", source)
        self.assertIn("var _anchor_depth_m", source)
        self.assertIn("_apply_3dof_anchor_transform()", source)
        self.assertIn('"yaw_left", "left", "move_left", "a":', source)
        self.assertIn('"yaw_right", "right", "move_right", "d":', source)
        self.assertIn('"pitch_up", "up", "move_up", "w":', source)
        self.assertIn('"pitch_down", "down", "move_down", "s":', source)
        self.assertIn('"depth_in", "closer":', source)
        self.assertIn('"depth_out", "farther":', source)
        self.assertIn("3DoF Anchor", source)
        self.assertIn("Yaw/Pitch/Depth", source)
        self.assertNotIn("world anchor", source.lower())

    def test_moving_card_starts_centered_for_visibility(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("const CARD_START_YAW_DEG := 0.0", source)
        self.assertIn("const CARD_START_PITCH_DEG := 0.0", source)
        self.assertIn("const CARD_DEFAULT_SPEED_DEG_PER_SECOND := 0.0", source)
        self.assertIn("const BBOX_START_CENTER_PX := Vector2(436.0, 326.0)", source)
        self.assertIn("const BBOX_IMAGE_SIZE := Vector2(872.0, 652.0)", source)

    def test_moving_card_supports_mock_bbox_anchor_mode(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("BBOX_IMAGE_SIZE", source)
        self.assertIn("var _anchor_mode := \"manual\"", source)
        self.assertIn("var _bbox_center_px", source)
        self.assertIn("var _bbox_size_px", source)
        self.assertIn("var _bbox_depth_m", source)
        self.assertIn("_apply_bbox_anchor()", source)
        self.assertIn("_anchor_from_bbox(", source)
        self.assertIn('"toggle_bbox_mode"', source)
        self.assertIn('"bbox_left"', source)
        self.assertIn('"bbox_right"', source)
        self.assertIn('"bbox_up"', source)
        self.assertIn('"bbox_down"', source)
        self.assertIn('"bbox_depth_in"', source)
        self.assertIn('"bbox_depth_out"', source)
        self.assertIn("Mode: %s", source)
        self.assertIn("BBox cx/cy/w/h", source)
        self.assertIn("Angular W/H", source)

    def test_moving_card_accepts_bbox_payloads_from_websocket(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('parsed.get("type", "") == "bbox"', source)
        self.assertIn("_apply_bbox_payload(parsed)", source)
        self.assertIn("_bbox_center_px = Vector2", source)
        self.assertIn("_bbox_size_px = Vector2", source)
        self.assertIn("_bbox_image_size = Vector2", source)

    def test_vst_tracker_boxes_drive_bbox_anchor(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("_apply_vst_tracker_anchor(boxes)", source)
        self.assertIn("func _apply_vst_tracker_anchor(boxes: PackedFloat32Array) -> void:", source)
        self.assertIn("_bbox_center_px = Vector2", source)
        self.assertIn("_bbox_size_px = Vector2", source)
        self.assertIn("_bbox_image_size = _vst_right_image_size", source)
        self.assertIn('_anchor_mode = "bbox"', source)
        self.assertIn('_last_command = "vst_bbox"', source)
        self.assertIn("_apply_bbox_anchor()", source)
        self.assertIn("VST anchor:", source)

    def test_vst_tracker_boxes_draw_visible_3d_bbox_frame(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("const VST_BBOX_FRAME_COLOR", source)
        self.assertIn("const VST_BBOX_FRAME_LINE_M", source)
        self.assertIn("const VST_BBOX_FRAME_Z_OFFSET_M", source)
        self.assertIn("var _vst_bbox_frame_anchor: Node3D = null", source)
        self.assertIn("var _vst_bbox_frame_parts: Array[MeshInstance3D] = []", source)
        self.assertIn("_build_vst_bbox_frame()", source)
        self.assertIn('VSTBBoxFrame"', source)
        self.assertIn("_update_vst_bbox_frame()", source)
        self.assertIn("_set_vst_bbox_frame_visible(false)", source)
        self.assertIn("_orient_node_for_3dof_reading(_vst_bbox_frame_anchor)", source)

    def test_moving_card_reports_xr_pose_for_tracking_diagnosis(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("var _xr_origin: XROrigin3D = null", source)
        self.assertIn("_format_vec3(_camera.global_position)", source)
        self.assertIn("_format_vec3(_camera.global_rotation_degrees)", source)
        self.assertIn("_format_vec3(_xr_origin.global_position)", source)
        self.assertIn("Camera Pos xyz: %s", source)
        self.assertIn("Camera Rot xyz: %s", source)
        self.assertIn("XROrigin Pos xyz: %s", source)

    def test_android_template_has_concrete_godot_activity(self):
        source = ANDROID_ACTIVITY.read_text(encoding="utf-8")

        self.assertIn("package com.godot.game;", source)
        self.assertIn("extends GodotActivity", source)

    def test_gxr_extension_is_enabled_for_android_export(self):
        extension_path = GODOT_ANDROID / "addons" / "gxr_sdk" / "gxr_sdk.gdextension"
        extension_list = GODOT_ANDROID / ".godot" / "extension_list.cfg"
        gradle_extension_libs = (
            GODOT_ANDROID / "android" / "build" / "libs" / "gdextensionlibs.json"
        )
        native_lib = (
            GODOT_ANDROID
            / "android"
            / "build"
            / "libs"
            / "debug"
            / "arm64-v8a"
            / "libgxr_sdk.android.template_debug.arm64.so"
        )

        self.assertTrue(extension_path.exists())
        self.assertIn("res://addons/gxr_sdk/gxr_sdk.gdextension", extension_list.read_text(encoding="utf-8"))
        self.assertIn("libgxr_sdk.android.template_debug.arm64.so", gradle_extension_libs.read_text(encoding="utf-8"))
        self.assertTrue(native_lib.exists())

    def test_android_export_is_visible_launcher_app(self):
        export_presets = (GODOT_ANDROID / "export_presets.cfg").read_text(encoding="utf-8")

        self.assertIn('package/unique_name="com.smartxr.godotcontrol"', export_presets)
        self.assertIn("package/show_as_launcher_app=true", export_presets)

    def test_android_app_label_is_demo_run_for_device_disambiguation(self):
        project = (GODOT_ANDROID / "project.godot").read_text(encoding="utf-8")
        export_presets = (GODOT_ANDROID / "export_presets.cfg").read_text(encoding="utf-8")
        android_label = (
            GODOT_ANDROID / "android" / "build" / "res" / "values" / "godot_project_name_string.xml"
        ).read_text(encoding="utf-8")

        self.assertIn('config/name="demo_run"', project)
        self.assertIn('package/name="demo_run"', export_presets)
        self.assertIn(">demo_run<", android_label)

    def test_xr_visibility_diagnostic_uses_opaque_composition(self):
        source = SCRIPT.read_text(encoding="utf-8")
        project = (GODOT_ANDROID / "project.godot").read_text(encoding="utf-8")

        self.assertIn("get_viewport().transparent_bg = false", source)
        self.assertIn("XRInterface.XR_ENV_BLEND_MODE_OPAQUE", source)
        self.assertIn("blend=opaque", source)
        self.assertIn("environment/defaults/default_clear_color=Color(0.02, 0.025, 0.03, 1)", project)

    def test_android_adaptive_icon_references_existing_mipmap_resources(self):
        res_dir = GODOT_ANDROID / "android" / "build" / "res"
        adaptive_icon = res_dir / "mipmap-anydpi-v26" / "icon.xml"
        source = adaptive_icon.read_text(encoding="utf-8")

        refs = re.findall(r"@mipmap/([A-Za-z0-9_]+)", source)
        self.assertGreater(len(refs), 0)
        for ref in refs:
            self.assertNotEqual(ref, adaptive_icon.stem, "adaptive icon must not reference itself")
            matches = list(res_dir.glob(f"mipmap*/{ref}.*"))
            with self.subTest(resource=ref):
                self.assertTrue(matches, f"{adaptive_icon} references missing @mipmap/{ref}")


if __name__ == "__main__":
    unittest.main()
