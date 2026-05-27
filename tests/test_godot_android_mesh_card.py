from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
