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

    def test_script_probes_for_dual_vst_capture_class(self):
        self.assertIn('ClassDB.class_exists(&"GXRDualVstCapture")', self.source)
        self.assertIn('ClassDB.instantiate(&"GXRDualVstCapture")', self.source)

    def test_script_stages_ncnn_model_to_user_dir(self):
        self.assertIn('"res://ncnn/yolov8n_320.opt.ncnn.param"', self.source)
        self.assertIn('"res://ncnn/yolov8n_320.opt.ncnn.bin"', self.source)
        self.assertIn('"user://ncnn/yolov8n_320.opt.ncnn.param"', self.source)
        self.assertIn('"user://ncnn/yolov8n_320.opt.ncnn.bin"', self.source)
        self.assertIn("_stage_vst_tracker_asset(", self.source)

    def test_script_configures_right_tracker_model(self):
        self.assertIn("_configure_vst_right_tracker_model()", self.source)
        self.assertIn('configure_right_tracker_model', self.source)
        self.assertIn("VST_RIGHT_TRACKER_FRAME_STRIDE", self.source)

    def test_script_polls_right_tracker_boxes_each_frame(self):
        self.assertIn("_poll_vst_bbox()", self.source)
        self.assertIn("get_right_tracker_boxes", self.source)
        self.assertIn("has_new_frame_right", self.source)
        self.assertIn("capture_frame_right", self.source)
        self.assertIn("get_right_tracker_total_latency_ms", self.source)

    def test_script_reports_vst_diagnostics_in_status_label(self):
        self.assertIn("_format_vst_status_line()", self.source)
        self.assertIn("VST:", self.source)
        self.assertIn("vst_line", self.source)

    def test_script_shuts_capture_down_on_exit(self):
        self.assertIn("func _exit_tree()", self.source)
        self.assertIn("_vst_capture.shutdown()", self.source)

    def test_m1_does_not_yet_touch_anchor_or_fov_constants(self):
        # ADR-007 v2 and ADR-010 are explicit: FOV and BBOX_IMAGE_SIZE change in M2,
        # not M1. This guard catches drift if a future agent tries to bundle the
        # constant swap into M1.
        self.assertIn("const BBOX_HORIZONTAL_FOV_DEG := 70.0", self.source)
        self.assertIn("const BBOX_VERTICAL_FOV_DEG := 43.0", self.source)
        self.assertIn("const BBOX_IMAGE_SIZE := Vector2(1280.0, 720.0)", self.source)


if __name__ == "__main__":
    unittest.main()
