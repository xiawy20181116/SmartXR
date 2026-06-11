from pathlib import Path
import re
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
VALIDATOR = ROOT / "tests" / "validate_project.ps1"
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
EXPORT_PRESETS = GODOT_ANDROID / "export_presets.cfg"
WINDOWS_PCMR_RUNNER = ROOT / "tools" / "run_windows_pcmr.ps1"
GXR_EXTENSION_SWITCH = ROOT / "tools" / "set_gxr_extension.ps1"
ANDROID_EXPORT_RUNNER = ROOT / "tools" / "export_android.ps1"
PROXY_TARGETS_CONSUMER = GODOT_ANDROID / "scripts" / "proxy_targets_consumer.gd"
PROXY_TARGETS_CARD_ADAPTER = GODOT_ANDROID / "scripts" / "proxy_targets_card_adapter.gd"
PROXY_TARGETS_SAMPLE = GODOT_ANDROID / "fixtures" / "proxy_targets_sample.json"
FAKE_PROXY_TARGETS_PUBLISHER = ROOT / "tools" / "fake_proxy_targets_publisher.py"


class GodotAndroidMeshCardTests(unittest.TestCase):
    def test_moving_card_uses_regular_mesh_card_anchor(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('CARD_ANCHOR_NAME := "CardAnchor"', source)
        self.assertIn("MeshInstance3D.new()", source)
        self.assertIn("QuadMesh.new()", source)
        self.assertIn("StandardMaterial3D.new()", source)
        self.assertIn("albedo_texture = _card_viewport.get_texture()", source)

    def test_antman_passthrough_overlay_layer_path_is_gated_by_env(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('const PASSTHROUGH_OVERLAY_ENV := "SMARTXR_USE_PASSTHROUGH_OVERLAY"', source)
        self.assertIn('const PASSTHROUGH_OVERLAY_STATUS_RES := "user://passthrough_overlay_status.json"', source)
        self.assertIn("var _passthrough_overlay_enabled := false", source)
        self.assertIn("func _use_passthrough_overlay() -> bool:", source)
        self.assertIn("OS.get_environment(PASSTHROUGH_OVERLAY_ENV)", source)
        self.assertIn("func _build_passthrough_overlay_layer() -> void:", source)
        self.assertIn("OpenXRCompositionLayerQuad.new()", source)
        self.assertIn("_passthrough_overlay_layer.layer_viewport = _passthrough_overlay_viewport", source)
        self.assertIn("_passthrough_overlay_layer.alpha_blend = true", source)
        self.assertIn("PASSTHROUGH OVERLAY", source)
        self.assertIn("func _write_passthrough_overlay_status_file(delta: float) -> void:", source)
        self.assertIn('"overlay_enabled": _passthrough_overlay_enabled', source)
        self.assertIn('"layer_alpha_blend": _passthrough_overlay_layer_alpha_blend()', source)

    def test_validate_project_wrapper_exists(self):
        source = VALIDATOR.read_text(encoding="utf-8")

        self.assertIn("python -m unittest", source)
        self.assertIn("test_godot_android_mesh_card.py", source)
        self.assertIn("test_vst_ncnn_port.py", source)
        self.assertIn("test_ws_control.py", source)

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

    def test_vst_tracker_boxes_drive_proxy_target_not_bbox_anchor(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("_apply_vst_tracker_anchor(boxes)", source)
        self.assertIn("func _apply_vst_tracker_anchor(boxes: PackedFloat32Array) -> void:", source)
        self.assertIn("_bbox_center_px = Vector2", source)
        self.assertIn("_bbox_size_px = Vector2", source)
        self.assertIn("_bbox_image_size = _vst_right_image_size", source)
        self.assertIn("var target_transform := _vst_tracker_box_to_target_transform(boxes)", source)
        self.assertIn("update_vst_target(VST_TRACKED_TARGET_ID, target_transform, confidence, float(Time.get_ticks_msec()))", source)
        self.assertIn('_last_command = "vst_target"', source)
        self.assertIn("VST target:", source)

    def test_vst_tracker_updates_standard_trackable_target_proxy(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("class TrackableTarget", source)
        self.assertIn('const TRACKABLE_STATE_TRACKED := "tracked"', source)
        self.assertIn('const TRACKABLE_SOURCE_VST := "vst"', source)
        self.assertIn("class VSTTargetAdapter", source)
        self.assertIn("func update_target(target_id: String, transform: Transform3D, confidence: float, timestamp_ms: float) -> bool:", source)
        self.assertIn("func update_vst_target(target_id: String, transform: Transform3D, confidence: float, timestamp_ms: float) -> bool:", source)
        self.assertIn("var _vst_target_adapter: VSTTargetAdapter = null", source)
        self.assertIn("var _vst_target_proxy: Node3D = null", source)
        self.assertIn('register_node3d_target(VST_TRACKED_TARGET_ID, _vst_target_proxy)', source)
        self.assertIn('attach_to_target(CARD_ANCHOR_NAME, VST_TRACKED_TARGET_ID, VST_TARGET_OFFSET_RULE)', source)
        self.assertIn("_vst_tracker_box_to_target_transform(boxes)", source)
        self.assertIn("func _vst_tracker_box_to_target_transform(boxes: PackedFloat32Array) -> Transform3D:", source)
        self.assertIn("target_transform.origin = _target_position_from_bbox_anchor(anchor)", source)

    def test_vst_target_adapter_tracks_confidence_timestamp_and_fallback_states(self):
        source = SCRIPT.read_text(encoding="utf-8")

        for marker in [
            "VST_TARGET_CONFIDENCE_THRESHOLD",
            "VST_TARGET_PREDICT_MS",
            "VST_TARGET_STALE_MS",
            "VST_TARGET_LOST_MS",
            "VST_TARGET_SMOOTHING_ALPHA",
            "velocity: Vector3",
            "confidence: float",
            "timestamp_ms: float",
            "state: String",
            "source: String",
            "_hold_last_pose",
            "_predict_pose",
            "_set_state(TRACKABLE_STATE_PREDICTED)",
            "_set_state(TRACKABLE_STATE_STALE)",
            "_set_state(TRACKABLE_STATE_LOST)",
            "_apply_vst_target_fallback()",
            "target_state=lost",
        ]:
            self.assertIn(marker, source)

    def test_vst_tracker_does_not_use_bbox_direct_anchor_inside_proxy_entrypoint(self):
        source = SCRIPT.read_text(encoding="utf-8")
        match = re.search(
            r"func _apply_vst_tracker_anchor\(boxes: PackedFloat32Array\) -> void:(?P<body>.*?)(?=\n\nfunc )",
            source,
            re.S,
        )
        self.assertIsNotNone(match)
        body = match.group("body")

        self.assertNotIn('_anchor_mode = "bbox"', body)
        self.assertNotIn('_last_command = "vst_bbox"', body)
        self.assertNotIn("_apply_bbox_anchor()", body)
        self.assertIn("update_vst_target(", body)

    def test_vst_bbox_anchor_uses_right_eye_to_head_transform_when_available(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("var _vst_right_eye_to_head_matrix := PackedFloat64Array()", source)
        self.assertIn("var _vst_uses_eye_to_head_anchor := false", source)
        self.assertIn("VST camera axes: +X right, +Y down, +Z forward", source)
        self.assertIn("var point_vst := Vector3(nx, ny, 1.0).normalized() * depth_m", source)
        self.assertIn("_convert_vst_camera_point_to_head_convention(point_vst)", source)
        self.assertIn("_store_right_eye_to_head_matrix(eye_info)", source)
        self.assertIn("func _transform_right_vst_point_to_head(point: Vector3) -> Vector3:", source)
        self.assertIn("point_head = _transform_right_vst_point_to_head(point_vst)", source)
        self.assertIn("Anchor: %s", source)
        self.assertIn('"eye2head" if _vst_uses_eye_to_head_anchor else "raw-fov"', source)

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

    def test_vst_tracker_debug_panel_draws_raw_right_image_bbox(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("const VST_RAW_DEBUG_PIXEL_SIZE_M", source)
        self.assertIn("var _vst_raw_debug_anchor: Node3D = null", source)
        self.assertIn("var _vst_raw_right_sprite: Sprite3D = null", source)
        self.assertIn("var _vst_raw_bbox_parts: Array[MeshInstance3D] = []", source)
        self.assertIn("_build_vst_raw_debug_panel()", source)
        self.assertIn('VSTRawDebugPanel"', source)
        self.assertIn("_vst_raw_right_sprite.texture = ImageTexture.create_from_image(right_img)", source)
        self.assertIn("_update_vst_raw_bbox_overlay(boxes)", source)
        self.assertIn("(x + w * 0.5 - 0.5) * overlay_size.x", source)
        self.assertIn("(0.5 - y - h * 0.5) * overlay_size.y", source)

    def test_card_can_attach_to_registered_node3d_targets(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("class TargetRegistry", source)
        self.assertIn("class Node3DTargetAdapter", source)
        self.assertIn("var _target_registry := TargetRegistry.new()", source)
        self.assertIn("func register_node3d_target(target_id: String, node_or_path", source)
        self.assertIn("func attach_to_target(card_id: String, target_id: String, offset_rule", source)
        self.assertIn('var _card_attachments := {}', source)
        self.assertIn('"hold_last_pose"', source)
        self.assertIn("_update_target_attachments()", source)
        self.assertIn("_target_registry.resolve(target_id)", source)
        self.assertIn("adapter.get_global_transform()", source)
        self.assertIn("_target_offset_transform(adapter.get_global_transform(), offset_rule)", source)
        self.assertIn('_anchor_mode = "target"', source)
        self.assertIn("_orient_card_for_3dof_reading()", source)
        self.assertRegex(source, r"if _anchor_mode == \"target\":\s+_update_target_attachments\(\)")

    def test_debug_marker_target_can_drive_real_device_validation(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("const DEBUG_NODE3D_TARGET_ENABLED := false", source)
        self.assertIn('const DEBUG_TARGET_ID := "debug_marker"', source)
        self.assertIn('var _debug_target_marker: MeshInstance3D = null', source)
        self.assertIn("func _build_debug_target_marker() -> void:", source)
        self.assertIn('marker.name = "MovingTargetMarker"', source)
        self.assertIn("BoxMesh.new()", source)
        self.assertIn("register_node3d_target(DEBUG_TARGET_ID, _debug_target_marker)", source)
        self.assertIn('attach_to_target(CARD_ANCHOR_NAME, DEBUG_TARGET_ID, {"mode": "right_top"', source)
        self.assertIn("func _update_debug_target_marker(delta: float) -> void:", source)
        self.assertIn("_debug_target_marker.position = Vector3(", source)
        self.assertIn("sin(_debug_target_elapsed_seconds", source)
        self.assertIn('"debug_target_free"', source)
        self.assertIn('"debug_target_reset"', source)

    def test_world_target_offset_ignores_target_rotation_for_card_position(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('"offset_space"', source)
        self.assertIn('"world"', source)
        self.assertIn('"target"', source)
        self.assertIn("func _target_world_offset_transform(target_transform: Transform3D, offset_rule) -> Transform3D:", source)
        self.assertIn("func _target_local_offset_transform(target_transform: Transform3D, offset_rule) -> Transform3D:", source)
        self.assertIn("result.origin = target_transform.origin + _target_offset_vector(rule)", source)
        self.assertIn("result.origin = target_transform * _target_offset_vector(rule)", source)
        self.assertIn('if str(rule.get("offset_space", "world")) == "target":', source)

    def test_debug_marker_uses_world_offset_while_rotating_for_pcmr_validation(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('"offset_space": "world"', source)
        self.assertIn("_debug_target_marker.rotation_degrees", source)
        self.assertIn("_debug_target_marker.position = Vector3(", source)

    def test_proxy_targets_validation_mode_drives_real_card_wrapper(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("const PROXY_TARGETS_VALIDATION_ENABLED := true", source)
        self.assertIn('const PROXY_TARGETS_SAMPLE_RES := "res://fixtures/proxy_targets_sample.json"', source)
        self.assertIn('preload("res://scripts/proxy_targets_consumer.gd")', source)
        self.assertIn('preload("res://scripts/proxy_targets_card_adapter.gd")', source)
        self.assertIn("var _proxy_targets_consumer: Node = null", source)
        self.assertIn("var _proxy_targets_card_adapter: Node = null", source)
        self.assertNotIn("var _proxy_targets_consumer: ProxyTargetsConsumer = null", source)
        self.assertNotIn("var _proxy_targets_card_adapter: ProxyTargetsCardAdapter = null", source)
        self.assertIn("func _build_proxy_targets_validation() -> void:", source)
        self.assertIn("func _apply_proxy_targets_sample() -> void:", source)
        self.assertIn("_proxy_targets_card_adapter.bind(_proxy_targets_consumer, self)", source)
        self.assertIn("_proxy_targets_card_adapter.apply_proxy_targets_json", source)
        self.assertIn("_build_proxy_targets_validation()", source)

    def test_proxy_targets_card_adapter_uses_offset_rule_contract(self):
        self.assertTrue(PROXY_TARGETS_CONSUMER.exists())
        self.assertTrue(PROXY_TARGETS_CARD_ADAPTER.exists())

        adapter = PROXY_TARGETS_CARD_ADAPTER.read_text(encoding="utf-8")
        self.assertIn("class_name ProxyTargetsCardAdapter", adapter)
        self.assertIn("var proxy_targets_consumer: Node = null", adapter)
        self.assertIn("func bind(consumer: Node, wrapper: Node) -> void:", adapter)
        self.assertNotIn("ProxyTargetsConsumer = null", adapter)
        self.assertIn('"register_node3d_target"', adapter)
        self.assertIn('"attach_to_target"', adapter)
        self.assertIn('card.get("offset_rule"', adapter)
        self.assertIn("_default_offset_rule", adapter)
        self.assertIn("func sync_card_wrapper() -> bool:", adapter)
        self.assertIn("return registered_ok and attached_ok", adapter)
        self.assertIn("return bool(card_wrapper.call(attach_method_name", adapter)

    def test_proxy_targets_sample_targets_real_card_anchor_without_raw_fields(self):
        sample = json.loads(PROXY_TARGETS_SAMPLE.read_text(encoding="utf-8"))

        self.assertEqual(sample["type"], "proxy_targets")
        self.assertEqual(sample["schema_version"], 1)
        self.assertEqual(sample["cards"][0]["card_id"], "CardAnchor")
        self.assertEqual(sample["cards"][0]["target_id"], sample["targets"][0]["target_id"])
        self.assertEqual(sample["cards"][0]["offset_rule"]["mode"], "right_top")
        self.assertEqual(sample["cards"][0]["offset_rule"]["offset_space"], "world")
        self.assertEqual(sample["targets"][0]["coordinate_space"], "world")
        self.assertEqual(sample["targets"][0]["transform_space"], "world")
        serialized = json.dumps(sample)
        self.assertNotIn("bbox", serialized)
        self.assertNotIn("detection", serialized)

    def test_proxy_targets_live_websocket_consumer_is_wired(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("const PROXY_TARGETS_WS_ENABLED := true", source)
        self.assertIn('const PROXY_TARGETS_WS_URL := "ws://127.0.0.1:8766/proxy_targets"', source)
        self.assertIn('const PROXY_TARGETS_STATUS_RES := "user://proxy_targets_live_status.json"', source)
        self.assertIn("var _proxy_targets_ws := WebSocketPeer.new()", source)
        self.assertIn("var _proxy_targets_live_messages := 0", source)
        self.assertIn("var _proxy_targets_ws_subscribed := false", source)
        self.assertIn("var _proxy_targets_ws_packets_seen := 0", source)
        self.assertIn("var _proxy_targets_parsed_messages := 0", source)
        self.assertIn("var _proxy_targets_last_sequence := -1", source)
        self.assertIn("var _proxy_targets_last_position := Vector3.ZERO", source)
        self.assertIn("var _proxy_targets_last_packet_bytes := 0", source)
        self.assertIn('var _proxy_targets_last_packet_preview := "-"', source)
        self.assertIn('var _proxy_targets_last_message_type := "-"', source)
        self.assertIn('var _proxy_targets_last_error := "-"', source)
        self.assertIn("var _proxy_targets_last_source_coordinate := {}", source)
        self.assertIn("var _proxy_targets_status_write_elapsed := 0.0", source)
        self.assertIn("func _connect_proxy_targets_ws() -> void:", source)
        self.assertIn("func _poll_proxy_targets_ws(delta: float) -> void:", source)
        self.assertIn("func _send_proxy_targets_subscribe() -> void:", source)
        self.assertIn("func _apply_proxy_targets_live_payload(payload: String) -> void:", source)
        self.assertIn("func _record_proxy_targets_diagnostics(message: Dictionary) -> void:", source)
        self.assertIn("func _write_proxy_targets_status_file(delta: float) -> void:", source)
        self.assertIn("func _format_proxy_targets_status_line() -> String:", source)
        self.assertIn("_connect_proxy_targets_ws()", source)
        self.assertIn("_poll_proxy_targets_ws(delta)", source)
        self.assertIn("_send_proxy_targets_subscribe()", source)
        self.assertIn("_proxy_targets_ws_url()", source)
        self.assertIn('OS.get_environment("PROXY_TARGETS_WS_URL")', source)
        self.assertIn("connect_to_url(_proxy_targets_ws_url())", source)
        self.assertIn("_proxy_targets_ws_packets_seen += 1", source)
        self.assertIn("_proxy_targets_last_packet_bytes = packet.size()", source)
        self.assertIn("_proxy_targets_last_packet_preview = _sanitize_proxy_targets_status_text(payload)", source)
        self.assertIn("_record_proxy_targets_diagnostics(parsed)", source)
        self.assertIn("_write_proxy_targets_status_file(delta)", source)
        self.assertIn("FileAccess.open(PROXY_TARGETS_STATUS_RES, FileAccess.WRITE)", source)
        self.assertIn('"anchor_mode": _anchor_mode', source)
        self.assertIn('"attachments": _card_attachments.size()', source)
        self.assertIn('"card_target_id": _proxy_targets_card_target_id()', source)
        self.assertIn("func _proxy_targets_card_target_id() -> String:", source)
        self.assertIn('"proxy_target_count": _proxy_targets_proxy_count()', source)
        self.assertIn('"proxy_target_ids": _proxy_targets_proxy_ids()', source)
        self.assertIn('"last_proxy_position": _format_vec3(_proxy_targets_last_position)', source)
        self.assertIn('"card_attach_target_id": _proxy_targets_card_target_id()', source)
        self.assertIn('"card_resolved_position": _proxy_targets_card_resolved_position()', source)
        self.assertIn('"card_node_position": _proxy_targets_card_node_position()', source)
        self.assertIn('"card_apply_count": _proxy_targets_card_apply_count', source)
        self.assertIn("var _proxy_targets_card_apply_count := 0", source)
        self.assertIn("func _proxy_targets_proxy_count() -> int:", source)
        self.assertIn("func _proxy_targets_proxy_ids() -> Array:", source)
        self.assertIn("func _proxy_targets_card_resolved_position() -> String:", source)
        self.assertIn("func _proxy_targets_card_node_position() -> String:", source)
        self.assertIn("_proxy_targets_card_apply_count += 1", source)
        self.assertIn('"packet_preview": _proxy_targets_last_packet_preview', source)
        self.assertIn('"source_coordinate": _proxy_targets_last_source_coordinate', source)
        self.assertIn('"source_coordinate_summary": _proxy_targets_source_coordinate_summary()', source)
        self.assertIn("func _proxy_targets_source_coordinate_summary() -> String:", source)
        self.assertLess(source.index("_record_proxy_targets_diagnostics(parsed)"), source.index("_proxy_targets_card_adapter.apply_proxy_targets_message(parsed)"))
        self.assertIn("ProxyWS: %s sub=%s packets=%d parsed=%d live=%d apply=%d seq=%d bytes=%d type=%s pos=%s card=%s src=%s err=%s", source)
        self.assertIn('_last_command = "proxy_live"', source)

    def test_fake_proxy_targets_publisher_exists_and_uses_stdlib_websocket(self):
        self.assertTrue(FAKE_PROXY_TARGETS_PUBLISHER.exists())
        source = FAKE_PROXY_TARGETS_PUBLISHER.read_text(encoding="utf-8")

        self.assertIn("def build_proxy_targets_message(", source)
        self.assertIn("def encode_websocket_text_frame(", source)
        self.assertIn("def serve(", source)
        self.assertIn("sequence: int = 0", source)
        self.assertIn("mode: str = \"moving\"", source)
        self.assertIn('"sequence": sequence', source)
        self.assertIn("sent seq=", source)
        self.assertIn('choices=["moving", "static"]', source)
        self.assertIn('"type": "proxy_targets"', source)
        self.assertIn('"schema_version": 1', source)
        self.assertIn('"coordinate_space": "world"', source)
        self.assertIn('"transform_space": "world"', source)
        self.assertIn('"card_id": card_id', source)
        self.assertIn('"target_id": target_id', source)
        self.assertNotIn("import websockets", source)
        self.assertNotIn("bbox", source)
        self.assertNotIn("detection", source)

    def test_proxy_targets_consumer_converts_head_space_to_world(self):
        consumer = PROXY_TARGETS_CONSUMER.read_text(encoding="utf-8")

        self.assertIn("var head_reference: Node3D = null", consumer)
        self.assertIn("func set_head_reference(reference: Node3D) -> void:", consumer)
        self.assertIn("func get_last_applied_target_info() -> Dictionary:", consumer)
        self.assertIn('target.get("transform_space"', consumer)
        self.assertIn('target.get("coordinate_space"', consumer)
        self.assertIn('source_coordinate.get("publisher_convention"', consumer)
        self.assertIn("func _is_head_coordinate_space(coordinate_space: String) -> bool:", consumer)
        self.assertIn("func _head_transform_to_world(head_transform: Transform3D) -> Transform3D:", consumer)
        self.assertIn("return head_reference.global_transform * head_transform", consumer)
        self.assertIn("world_from_head_applied", consumer)
        self.assertIn('"world_position": _vec3_to_array(parsed_transform.origin)', consumer)

    def test_proxy_targets_status_reports_head_to_world_diagnostics(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("_proxy_targets_consumer.set_head_reference(_camera)", source)
        self.assertIn("var _proxy_targets_last_world_from_head_applied := false", source)
        self.assertIn("var _proxy_targets_last_local_position := Vector3.ZERO", source)
        self.assertIn("var _proxy_targets_last_world_position := Vector3.ZERO", source)
        self.assertIn("get_last_applied_target_info", source)
        self.assertIn('"world_from_head_applied": _proxy_targets_last_world_from_head_applied', source)
        self.assertIn('"proxy_local_position": _format_vec3(_proxy_targets_last_local_position)', source)
        self.assertIn('"proxy_world_position": _format_vec3(_proxy_targets_last_world_position)', source)

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
        export_presets = EXPORT_PRESETS.read_text(encoding="utf-8")

        self.assertIn('package/unique_name="com.smartxr.godotcontrol"', export_presets)
        self.assertIn("package/show_as_launcher_app=true", export_presets)

    def test_export_presets_support_windows_pcmr_without_regressing_android(self):
        export_presets = EXPORT_PRESETS.read_text(encoding="utf-8")

        self.assertIn('name="Android"', export_presets)
        self.assertIn('platform="Android"', export_presets)
        self.assertIn('export_path="builds/SmartXR-Godot-Control.apk"', export_presets)
        self.assertIn('package/unique_name="com.smartxr.godotcontrol"', export_presets)
        self.assertIn('name="Windows Desktop"', export_presets)
        self.assertIn('platform="Windows Desktop"', export_presets)
        self.assertIn('export_path="builds/windows/SmartXR-PCMR.exe"', export_presets)

    def test_windows_pcmr_runner_uses_known_godot_path_and_project(self):
        runner = WINDOWS_PCMR_RUNNER.read_text(encoding="utf-8")

        self.assertTrue(runner.lstrip().startswith("param("))
        self.assertIn(r"E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe", runner)
        self.assertIn("SmartXR-PCMR", runner)
        self.assertIn("godot-android", runner)
        self.assertIn("--path", runner)
        self.assertIn("SteamVR", runner)
        self.assertIn("WMR", runner)
        self.assertIn("Meta Link", runner)
        self.assertIn("OpenXR", runner)
        self.assertIn("$PSScriptRoot", runner)

    def test_gxr_extension_switch_can_disable_for_windows_and_enable_for_android(self):
        switcher = GXR_EXTENSION_SWITCH.read_text(encoding="utf-8")

        self.assertIn('ValidateSet("enable", "disable")', switcher)
        self.assertIn("res://addons/gxr_sdk/gxr_sdk.gdextension", switcher)
        self.assertIn(".godot", switcher)
        self.assertIn("extension_list.cfg", switcher)
        self.assertIn(".gdextension.disabled", switcher)
        self.assertIn('$Mode -eq "disable"', switcher)
        self.assertIn('$Mode -eq "enable"', switcher)
        self.assertIn("Move-Item", switcher)
        self.assertIn("Where-Object", switcher)
        self.assertIn("Write-Utf8NoBomLines", switcher)
        self.assertIn("UTF8Encoding($false)", switcher)
        self.assertIn("WriteAllText", switcher)

    def test_windows_runner_temporarily_disables_gxr_extension(self):
        runner = WINDOWS_PCMR_RUNNER.read_text(encoding="utf-8")

        self.assertIn("set_gxr_extension.ps1", runner)
        self.assertIn("-Mode disable", runner)
        self.assertIn("-Mode enable", runner)
        self.assertIn("try {", runner)
        self.assertIn("finally {", runner)

    def test_android_export_runner_enables_gxr_extension_before_export(self):
        runner = ANDROID_EXPORT_RUNNER.read_text(encoding="utf-8")

        self.assertIn("set_gxr_extension.ps1", runner)
        self.assertIn("-Mode enable", runner)
        self.assertIn("--export-debug", runner)
        self.assertIn("Android", runner)
        self.assertIn("SmartXR-Godot-Control.apk", runner)

    def test_android_app_label_is_demo_run_for_device_disambiguation(self):
        project = (GODOT_ANDROID / "project.godot").read_text(encoding="utf-8")
        export_presets = (GODOT_ANDROID / "export_presets.cfg").read_text(encoding="utf-8")
        android_label = (
            GODOT_ANDROID / "android" / "build" / "res" / "values" / "godot_project_name_string.xml"
        ).read_text(encoding="utf-8")

        self.assertIn('config/name="demo_run"', project)
        self.assertIn('package/name="demo_run"', export_presets)
        self.assertIn(">demo_run<", android_label)

    def test_xr_visibility_diagnostic_uses_alpha_blend_composition_for_pcmr_seethrough(self):
        source = SCRIPT.read_text(encoding="utf-8")
        project = (GODOT_ANDROID / "project.godot").read_text(encoding="utf-8")

        self.assertIn("get_viewport().transparent_bg = true", source)
        self.assertIn("XRInterface.XR_ENV_BLEND_MODE_ALPHA_BLEND", source)
        self.assertIn("blend=alpha", source)
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
