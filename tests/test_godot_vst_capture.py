from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
SUBSYSTEM = ROOT / "godot-android" / "scripts" / "vst_capture.gd"
PROBE = ROOT / "godot-android" / "tests" / "script_only_vst_capture_probe.gd"
RUNNER = ROOT / "tools" / "run_godot_vst_capture_probe.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
TASKS = ROOT / "TASKS.md"
DECISIONS = ROOT / "DECISIONS.md"
HANDOFF = ROOT / "HANDOFF.md"
DOC = ROOT / "docs" / "vst_capture.md"


class GodotVSTCaptureTests(unittest.TestCase):
    def test_vst_capture_subsystem_owns_bbox_math_and_capture_pipeline(self):
        source = SUBSYSTEM.read_text(encoding="utf-8")

        self.assertIn("extends RefCounted", source)
        self.assertIn("class_name VSTCapture", source)
        self.assertNotIn("VSTCapture.new()", source)
        self.assertNotIn(": VSTCapture", source)
        self.assertNotIn("preload(", source)
        self.assertNotIn("get_tree()", source)

        for marker in [
            "func setup_capture(xr_active: bool) -> void:",
            "func poll() -> Dictionary:",
            "func shutdown() -> void:",
            "func set_camera_calibration(horizontal_fov_deg: float, vertical_fov_deg: float, principal_point_px: Vector2 = Vector2(-1.0, -1.0)) -> void:",
            "func anchor_from_bbox(center_px: Vector2, size_px: Vector2, image_size: Vector2, depth_m: float) -> Dictionary:",
            "func target_position_from_bbox_anchor(anchor: Dictionary) -> Vector3:",
            "func convert_vst_camera_point_to_head_convention(point: Vector3) -> Vector3:",
            "func transform_right_vst_point_to_head(point: Vector3) -> Vector3:",
            "func tracker_box_to_target_transform(boxes: PackedFloat32Array, depth_m: float) -> Transform3D:",
            "func store_right_eye_to_head_matrix(eye_info: Dictionary) -> void:",
            "func status_snapshot() -> Dictionary:",
            "func last_error() -> String:",
            "func set_raw_image_callback(on_raw_image: Callable) -> void:",
            "func set_boxes_callback(on_boxes: Callable) -> void:",
            "func set_anchor_callback(on_anchor: Callable) -> void:",
        ]:
            self.assertIn(marker, source)

        for marker in [
            "ClassDB.class_exists(&\"GXRDualVstCapture\")",
            "ClassDB.instantiate(&\"GXRDualVstCapture\")",
            "configure_right_tracker_model",
            "get_right_tracker_boxes",
            "get_right_tracker_total_latency_ms",
            "get_eye_to_head_matrices",
            "get_calibration_coeff_info",
            "_principal_point_px",
            '"principal_point_px": _principal_point_px',
            "GXR_CAL_CV_DEWARP_L",
            "GXR_CAL_CV_DEWARP_R",
            "GXR_CAL_CV_SLAM",
        ]:
            self.assertIn(marker, source)

    def test_moving_card_delegates_vst_capture_and_keeps_public_api(self):
        card = CARD.read_text(encoding="utf-8")

        self.assertIn('const VSTCaptureScript := preload("res://scripts/vst_capture.gd")', card)
        self.assertIn("var _vst_capture = VSTCaptureScript.new(", card)
        self.assertIn("_vst_capture.set_raw_image_callback(_on_vst_raw_right_image)", card)
        self.assertIn("_vst_capture.set_boxes_callback(_on_vst_tracker_boxes)", card)
        self.assertIn("_vst_capture.set_anchor_callback(_on_vst_tracker_anchor)", card)
        self.assertIn("_vst_capture.setup_capture(_xr_active)", card)
        self.assertIn("_vst_capture.poll()", card)
        self.assertIn("_vst_capture.status_snapshot()", card)
        self.assertIn("_vst_capture.shutdown()", card)
        self.assertIn("func update_vst_target(target_id: String, transform: Transform3D, confidence: float, timestamp_ms: float) -> bool:", card)
        self.assertIn("func register_node3d_target(target_id: String, node_or_path) -> bool:", card)
        self.assertIn("func attach_to_target(card_id: String, target_id: String, offset_rule = {}) -> bool:", card)

        for removed in [
            "func _configure_vst_right_tracker_model() -> void:",
            "func _stage_vst_tracker_asset(source_path: String, target_path: String) -> String:",
            "func _refresh_vst_calibration_diagnostics() -> void:",
            "func _store_right_eye_to_head_matrix(eye_info: Dictionary) -> void:",
            "func _format_eye_to_head_status(eye_info: Dictionary) -> String:",
            "func _format_calibration_probe(info) -> String:",
            "func _vst_tracker_box_to_target_transform(boxes: PackedFloat32Array) -> Transform3D:",
        ]:
            self.assertNotIn(removed, card)

    def test_runtime_probe_runner_ci_and_docs_are_registered(self):
        probe = PROBE.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("extends SceneTree", probe)
        self.assertIn('OS.get_environment("SMARTXR_VST_CAPTURE_SCRIPT")', probe)
        self.assertIn("SMARTXR_VST_CAPTURE_PROBE_STATUS_PATH", probe)
        self.assertIn("bbox_center_math", probe)
        self.assertIn("eye_to_head_matrix_path", probe)
        self.assertIn("tracker_box_to_target_transform", probe)
        self.assertIn("status_snapshot_defaults", probe)
        self.assertIn('"--script", $ProbeScript', runner)
        self.assertNotIn('"--path"', runner)
        self.assertIn("SMARTXR_VST_CAPTURE_SCRIPT", runner)
        self.assertIn("tools/run_godot_vst_capture_probe.ps1", workflow)

        for path in (TASKS, DECISIONS, HANDOFF, DOC):
            text = path.read_text(encoding="utf-8")
            self.assertIn("VSTCapture", text)

    def test_android_moving_card_is_orchestration_sized(self):
        lines = CARD.read_text(encoding="utf-8").splitlines()
        self.assertLess(len(lines), 1350)
        self.assertLessEqual(len(re.findall(r"^func ", "\n".join(lines), flags=re.M)), 90)


if __name__ == "__main__":
    unittest.main()
