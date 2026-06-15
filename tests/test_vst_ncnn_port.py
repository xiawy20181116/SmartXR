"""M1 (YAN-56) static checks: VST+ncnn binaries and GDScript scaffold are in place.

These are file-existence and source-substring assertions. Real on-device
behaviour requires a Quest install — see addons/gxr_sdk/VERSION.txt for the
rollback procedure if the new .so set misbehaves.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "godot-android"
ADDON_SO = ANDROID / "addons" / "gxr_sdk" / "bin" / "android"
ADDON_VERSION = ANDROID / "addons" / "gxr_sdk" / "VERSION.txt"
NCNN_DIR = ANDROID / "ncnn"
NCNN_PARAM = NCNN_DIR / "yolov8n_320.opt.ncnn.param"
NCNN_BIN = NCNN_DIR / "yolov8n_320.opt.ncnn.bin"
JNI_DEBUG = ANDROID / "android" / "build" / "libs" / "debug" / "arm64-v8a"
JNI_RELEASE = ANDROID / "android" / "build" / "libs" / "release" / "arm64-v8a"
SCRIPT = ANDROID / "scripts" / "AndroidMovingCard.gd"
VST_CAPTURE = ANDROID / "scripts" / "vst_capture.gd"
CARD_VIEW = ANDROID / "scripts" / "card_view.gd"
# Status-line rendering moved to the StatusHud subsystem in M3 step 1 (YAN-74);
# the card assembles the xr/vst snapshots that feed those lines.
STATUS_HUD = ANDROID / "scripts" / "status_hud.gd"


ADDON_LIBS = [
    "libahrs.so",
    "libgxr_log.so",
    "libgxr_metadata.so",
    "libgxr_sdk.android.template_debug.arm64.so",
    "libgxr_sdk.android.template_release.arm64.so",
    "libgxrapi.so",
    "libjxg.so",
    "libtrace_provider.so",
    "libtracking_hand.so",
]

JNI_DEBUG_LIBS = [
    "libahrs.so",
    "libgxr_log.so",
    "libgxr_metadata.so",
    "libgxr_sdk.android.template_debug.arm64.so",
    "libgxrapi.so",
    "libjxg.so",
    "libomp.so",
    "libopenxr_loader.so",
    "libtrace_provider.so",
    "libtracking_hand.so",
]

JNI_RELEASE_LIBS = [
    "libahrs.so",
    "libgxr_log.so",
    "libgxr_metadata.so",
    "libgxrapi.so",
    "libjxg.so",
    "libomp.so",
    "libtrace_provider.so",
    "libtracking_hand.so",
]


class VstNcnnPortLayoutTests(unittest.TestCase):
    def test_ncnn_model_pair_is_staged(self):
        self.assertTrue(NCNN_PARAM.exists(), f"missing {NCNN_PARAM}")
        self.assertTrue(NCNN_BIN.exists(), f"missing {NCNN_BIN}")
        # bin is ~12 MB; guard against accidental zero-byte LFS placeholder
        self.assertGreater(NCNN_BIN.stat().st_size, 10_000_000)
        self.assertGreater(NCNN_PARAM.stat().st_size, 1_000)

    def test_addon_so_set_complete(self):
        for name in ADDON_LIBS:
            path = ADDON_SO / name
            with self.subTest(lib=name):
                self.assertTrue(path.exists(), f"missing addon lib {path}")
                self.assertGreater(path.stat().st_size, 0)

    def test_addon_libgxr_sdk_is_fat_version(self):
        # Vanilla SmartXR libgxr_sdk was ~913 KB; Godot_card's fat version is ~9.4 MB.
        # The fat version is what registers GXRDualVstCapture.
        debug = ADDON_SO / "libgxr_sdk.android.template_debug.arm64.so"
        self.assertGreater(debug.stat().st_size, 5_000_000, "libgxr_sdk too small; likely still vanilla")

    def test_jni_libs_debug_complete(self):
        for name in JNI_DEBUG_LIBS:
            path = JNI_DEBUG / name
            with self.subTest(lib=name):
                self.assertTrue(path.exists(), f"missing debug jniLib {path}")
                self.assertGreater(path.stat().st_size, 0)

    def test_jni_libs_release_complete(self):
        for name in JNI_RELEASE_LIBS:
            path = JNI_RELEASE / name
            with self.subTest(lib=name):
                self.assertTrue(path.exists(), f"missing release jniLib {path}")
                self.assertGreater(path.stat().st_size, 0)

    def test_version_pin_recorded(self):
        self.assertTrue(ADDON_VERSION.exists())
        body = ADDON_VERSION.read_text(encoding="utf-8")
        self.assertIn("Godot_card", body)
        self.assertIn("libgxr_sdk.android.template_debug.arm64.so", body)
        self.assertIn("YAN-56", body)


class AndroidMovingCardVstScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.source = SCRIPT.read_text(encoding="utf-8")
        self.vst_capture = VST_CAPTURE.read_text(encoding="utf-8")
        self.card_view = CARD_VIEW.read_text(encoding="utf-8")

    def test_script_probes_for_dual_vst_capture_class(self):
        self.assertIn('ClassDB.class_exists(&"GXRDualVstCapture")', self.vst_capture)
        self.assertIn('ClassDB.instantiate(&"GXRDualVstCapture")', self.vst_capture)

    def test_script_stages_ncnn_model_to_user_dir(self):
        self.assertIn('"res://ncnn/yolov8n_320.opt.ncnn.param"', self.source)
        self.assertIn('"res://ncnn/yolov8n_320.opt.ncnn.bin"', self.source)
        self.assertIn('"user://ncnn/yolov8n_320.opt.ncnn.param"', self.source)
        self.assertIn('"user://ncnn/yolov8n_320.opt.ncnn.bin"', self.source)
        self.assertIn("_stage_vst_tracker_asset(", self.vst_capture)

    def test_android_export_includes_ncnn_model_assets(self):
        export_presets = (ANDROID / "export_presets.cfg").read_text(encoding="utf-8")

        self.assertIn('include_filter="ncnn/*.param,ncnn/*.bin"', export_presets)

    def test_script_configures_right_tracker_model(self):
        self.assertIn("_configure_vst_right_tracker_model()", self.vst_capture)
        self.assertIn('configure_right_tracker_model', self.vst_capture)
        self.assertIn("VST_RIGHT_TRACKER_FRAME_STRIDE", self.source)

    def test_script_polls_right_tracker_boxes_each_frame(self):
        self.assertIn("_poll_vst_bbox()", self.source)
        self.assertIn("_vst_capture.poll()", self.source)
        self.assertIn("get_right_tracker_boxes", self.vst_capture)
        self.assertIn("has_new_frame_right", self.vst_capture)
        self.assertIn("capture_frame_right", self.vst_capture)
        self.assertIn("get_right_tracker_total_latency_ms", self.vst_capture)

    def test_script_reports_vst_diagnostics_in_status_label(self):
        hud = STATUS_HUD.read_text(encoding="utf-8")

        self.assertIn("func _build_vst_status_snapshot() -> Dictionary:", self.source)
        self.assertIn("func _format_vst_status_line(vst: Dictionary) -> String:", hud)
        self.assertIn("VST:", hud)
        self.assertIn("vst_line", hud)

    def test_script_reports_xr_diagnostics_before_vst_status(self):
        hud = STATUS_HUD.read_text(encoding="utf-8")

        self.assertIn("func _build_xr_status_snapshot() -> Dictionary:", self.source)
        self.assertIn("func _format_xr_status_line(snapshot: Dictionary) -> String:", hud)
        self.assertIn("XR:", hud)
        self.assertIn("_xr_interface_found", self.source)
        self.assertIn("_xr_initialize_ok", self.source)
        self.assertIn("_xr_init_error", self.source)

    def test_script_does_not_enable_vst_when_openxr_is_inactive(self):
        setup_index = self.vst_capture.index("func setup_capture(xr_active: bool) -> void:")
        gated_index = self.vst_capture.index("if not xr_active:", setup_index)
        class_probe_index = self.vst_capture.index('ClassDB.class_exists(&"GXRDualVstCapture")', setup_index)
        self.assertLess(gated_index, class_probe_index)

    def test_script_has_simple_xr_render_probe(self):
        self.assertIn("_build_xr_render_probe()", self.source)
        self.assertIn("_card_view.build_xr_render_probe()", self.source)
        self.assertIn("XR_PROBE_SIZE_M", self.source)
        self.assertIn('"XRRenderProbe"', self.card_view)
        self.assertIn("Color(1.0, 0.05, 0.05, 1.0)", self.card_view)

    def test_script_shuts_capture_down_on_exit(self):
        self.assertIn("func _exit_tree()", self.source)
        self.assertIn("_vst_capture.shutdown()", self.source)

    def test_on_device_vst_bbox_image_geometry_is_pinned(self):
        self.assertIn("const BBOX_HORIZONTAL_FOV_DEG := 70.0", self.source)
        self.assertIn("const BBOX_VERTICAL_FOV_DEG := 43.0", self.source)
        self.assertIn("const BBOX_IMAGE_SIZE := Vector2(872.0, 652.0)", self.source)

    def test_vst_tracker_boxes_are_normalized_xywh(self):
        self.assertIn("var x := clampf(float(boxes[0]), 0.0, 1.0)", self.vst_capture)
        self.assertIn("var y := clampf(float(boxes[1]), 0.0, 1.0)", self.vst_capture)
        self.assertIn("var w := clampf(float(boxes[2]), 0.02, 1.0)", self.vst_capture)
        self.assertIn("var center_px := Vector2((x + w * 0.5) * _right_image_size.x", self.vst_capture)

    def test_script_and_extension_expose_runtime_calibration_diagnostics(self):
        self.assertIn("const GXR_CAL_CV_DEWARP_R := 0x00400061", self.vst_capture)
        self.assertIn("const GXR_CAL_CV_SLAM := 0x00400070", self.vst_capture)
        self.assertIn("_refresh_vst_calibration_diagnostics()", self.vst_capture)
        self.assertIn("_eye_to_head_status", self.vst_capture)
        self.assertIn("_calibration_status", self.vst_capture)
        self.assertIn("get_eye_to_head_matrices", self.vst_capture)
        self.assertIn("get_calibration_coeff_info", self.vst_capture)

        debug_binary = (ADDON_SO / "libgxr_sdk.android.template_debug.arm64.so").read_bytes()
        release_binary = (ADDON_SO / "libgxr_sdk.android.template_release.arm64.so").read_bytes()
        for binary in [debug_binary, release_binary]:
            with self.subTest(size=len(binary)):
                self.assertIn(b"get_eye_to_head_matrices", binary)
                self.assertIn(b"get_calibration_coeff_info", binary)


if __name__ == "__main__":
    unittest.main()
