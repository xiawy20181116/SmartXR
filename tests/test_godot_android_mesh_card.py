from pathlib import Path
import re
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "godot-android" / "scripts" / "AndroidMovingCard.gd"
# Status label rendering and the user:// status-file writers moved to the
# StatusHud subsystem in M3 step 1 (YAN-74); display/format assertions are
# pinned there, snapshot-assembly assertions stay on the card script.
STATUS_HUD = ROOT / "godot-android" / "scripts" / "status_hud.gd"
# TargetRegistry + Node3DTargetAdapter moved to scripts/target_registry.gd in
# M3 step 2 (YAN-75); registry/adapter assertions are pinned there, the
# attach/fallback state machine stays on the card script.
TARGET_REGISTRY = ROOT / "godot-android" / "scripts" / "target_registry.gd"
# The two WebSocketPeer connect/poll/retry loops moved to scripts/ws_transport.gd
# in M3 step 3 (YAN-76); peer/retry/subscribe assertions are pinned there,
# URL resolution, packet handling, and the status snapshot stay on the card.
WS_TRANSPORT = ROOT / "godot-android" / "scripts" / "ws_transport.gd"
# The attachment store, fallback state machine, and offset-rule math moved to
# scripts/card_attachment.gd in M3 step 4 (YAN-77); store/fallback/offset
# assertions are pinned there, the public API, anchor-mode switching, and the
# status snapshot stay on the card.
CARD_ATTACHMENT = ROOT / "godot-android" / "scripts" / "card_attachment.gd"
CARD_STATE_BASE = ROOT / "godot-android" / "scripts" / "card_state_base.gd"
CARD_STATE = ROOT / "godot-android" / "scripts" / "card_state.gd"
CARD_RECEIVER = ROOT / "godot-android" / "scripts" / "card_receiver.gd"
# Command parsing / state reduction moved to scripts/command_dispatcher.gd in
# YAN-104; command alias assertions are pinned there, while the card keeps
# node side effects and state copy-back.
COMMAND_DISPATCHER = ROOT / "godot-android" / "scripts" / "command_dispatcher.gd"
# Proxy target diagnostics/status snapshot assembly moved to
# scripts/proxy_targets_status_fragment.gd in YAN-104; packet/message state
# assertions are pinned there, while the card keeps transport and live
# consumer wiring.
PROXY_TARGETS_STATUS_FRAGMENT = (
    ROOT / "godot-android" / "scripts" / "proxy_targets_status_fragment.gd"
)
# TrackableTarget / VSTTargetAdapter moved to scripts/target_source.gd in M4
# step 2 (YAN-84); state-machine assertions are pinned there, bbox math and
# target-source wiring stay on the card.
TARGET_SOURCE = ROOT / "godot-android" / "scripts" / "target_source.gd"
# VST capture/polling/calibration/bbox math moved to scripts/vst_capture.gd
# in YAN-99; card-side assertions only cover scene callbacks and public API.
VST_CAPTURE = ROOT / "godot-android" / "scripts" / "vst_capture.gd"
# VST debug scene visuals moved to scripts/vst_debug_ui.gd in YAN-100; visual
# node construction and overlay sizing assertions are pinned there.
VST_DEBUG_UI = ROOT / "godot-android" / "scripts" / "vst_debug_ui.gd"
# The XR startup path (_try_init_xr) and the camera/origin construction moved
# to scripts/xr_bootstrap.gd in M3 step 5 (YAN-79); init/blend/camera
# assertions are pinned there, the resolved _xr_* state and the status
# snapshot stay on the card.
XR_BOOTSTRAP = ROOT / "godot-android" / "scripts" / "xr_bootstrap.gd"
# Passthrough overlay viewport/layer construction moved to
# scripts/passthrough_overlay_presenter.gd in YAN-103; card-side assertions
# cover only enablement state and delegation.
PASSTHROUGH_OVERLAY_PRESENTER = (
    ROOT / "godot-android" / "scripts" / "passthrough_overlay_presenter.gd"
)
# Card viewport/mesh/UI construction moved to scripts/card_view.gd in YAN-103;
# card-side assertions cover only owner wiring and retained handles.
CARD_VIEW_BASE = ROOT / "godot-android" / "scripts" / "card_view_base.gd"
CARD_VIEW = ROOT / "godot-android" / "scripts" / "card_view.gd"
VALIDATION_SCENE_BUILDER = ROOT / "godot-android" / "scripts" / "validation_scene_builder.gd"
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
ANDROID_WORKFLOW_DOC = ROOT / "docs" / "android_apk_workflow.md"
PROXY_TARGETS_CONSUMER = GODOT_ANDROID / "scripts" / "proxy_targets_consumer.gd"
PROXY_TARGETS_CARD_ADAPTER = GODOT_ANDROID / "scripts" / "proxy_targets_card_adapter.gd"
PROXY_TARGETS_SAMPLE = GODOT_ANDROID / "fixtures" / "proxy_targets_sample.json"
FAKE_PROXY_TARGETS_PUBLISHER = ROOT / "tools" / "fake_proxy_targets_publisher.py"


class GodotAndroidMeshCardTests(unittest.TestCase):
    def test_moving_card_uses_regular_mesh_card_anchor(self):
        source = SCRIPT.read_text(encoding="utf-8")
        card_view_base = CARD_VIEW_BASE.read_text(encoding="utf-8")
        card_view = CARD_VIEW.read_text(encoding="utf-8")

        self.assertIn('CARD_ANCHOR_NAME := "CardAnchor"', source)
        self.assertIn("var _card_view = CardViewScript.new(", source)
        self.assertIn("_card_view.build(self, CARD_ANCHOR_NAME)", source)
        self.assertIn("_card_viewport = _card_view.viewport()", source)
        self.assertIn("_card_anchor = _card_view.anchor()", source)
        self.assertIn("_card_mesh = _card_view.card_mesh()", source)
        self.assertIn("class_name CardViewBase", card_view_base)
        self.assertIn('extends "card_view_base.gd"', card_view)
        self.assertIn("MeshInstance3D.new()", card_view)
        self.assertIn("QuadMesh.new()", card_view)
        self.assertIn("StandardMaterial3D.new()", card_view)
        self.assertIn("albedo_texture = _viewport.get_texture()", card_view)

    def test_phase_c_uses_card_state_view_receiver_trio(self):
        source = SCRIPT.read_text(encoding="utf-8")
        card_state_base = CARD_STATE_BASE.read_text(encoding="utf-8")
        card_state = CARD_STATE.read_text(encoding="utf-8")
        card_receiver = CARD_RECEIVER.read_text(encoding="utf-8")

        self.assertIn('const CardStateScript := preload("res://scripts/card_state.gd")', source)
        self.assertIn('const CardReceiverScript := preload("res://scripts/card_receiver.gd")', source)
        self.assertIn("var _card_state = CardStateScript.new(", source)
        self.assertIn("var _card_receiver = CardReceiverScript.new()", source)
        self.assertIn("_card_receiver.setup(", source)
        self.assertIn("_card_receiver.connect_if_enabled()", source)
        self.assertIn("_card_receiver.poll(delta)", source)
        self.assertNotIn("func _connect_proxy_targets_ws() -> void:", source)
        self.assertNotIn("func _poll_proxy_targets_ws(delta: float) -> void:", source)
        self.assertNotIn("func _apply_proxy_targets_live_payload(payload: String) -> void:", source)
        self.assertIn("class_name CardStateBase", card_state_base)
        self.assertIn('extends "card_state_base.gd"', card_state)
        self.assertIn("func command_state() -> Dictionary:", card_state)
        self.assertIn("func apply_command_state(next_state: Dictionary) -> void:", card_state)
        self.assertIn("func apply_bbox_payload(parsed: Dictionary) -> bool:", card_state)
        self.assertIn("func status_values() -> Dictionary:", card_state)
        self.assertIn("func connect_if_enabled() -> void:", card_receiver)
        self.assertIn("func apply_live_payload(payload: String) -> bool:", card_receiver)
        self.assertIn("func status_values(extra := {}) -> Dictionary:", card_receiver)

    def test_antman_passthrough_overlay_layer_path_is_gated_by_env(self):
        source = SCRIPT.read_text(encoding="utf-8")
        hud = STATUS_HUD.read_text(encoding="utf-8")
        presenter = PASSTHROUGH_OVERLAY_PRESENTER.read_text(encoding="utf-8")

        self.assertIn('const PASSTHROUGH_OVERLAY_ENV := "SMARTXR_USE_PASSTHROUGH_OVERLAY"', source)
        self.assertIn('const PASSTHROUGH_OVERLAY_STATUS_RES := "user://passthrough_overlay_status.json"', hud)
        self.assertIn("var _passthrough_overlay_enabled := false", source)
        self.assertIn("func _use_passthrough_overlay() -> bool:", source)
        self.assertIn("overlay_enabled_from_env(PASSTHROUGH_OVERLAY_ENV)", source)
        self.assertIn("OS.get_environment(env_name)", presenter)
        self.assertIn("func _build_passthrough_overlay_layer() -> void:", source)
        self.assertIn("build_layer(self, _xr_active, _passthrough_overlay_enabled)", source)
        self.assertIn("OpenXRCompositionLayerQuad.new()", presenter)
        self.assertIn("_layer.layer_viewport = _viewport", presenter)
        self.assertIn("_layer.alpha_blend = true", presenter)
        self.assertIn("PASSTHROUGH OVERLAY", presenter)
        # The presenter reports overlay status values; StatusHud writes the file.
        self.assertIn("func _build_passthrough_overlay_status_snapshot() -> Dictionary:", source)
        self.assertIn("status_values(", source)
        self.assertIn('"layer_alpha_blend": layer_alpha_blend()', presenter)
        self.assertIn("func _write_passthrough_overlay_status_file(snapshot: Dictionary, delta: float) -> void:", hud)
        self.assertIn('"overlay_enabled": overlay.get("enabled", false)', hud)

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
        hud = STATUS_HUD.read_text(encoding="utf-8")

        self.assertIn("var _face_camera_enabled := true", source)
        self.assertIn("_orient_card_for_3dof_reading()", source)
        self.assertIn("var flat_camera_position := Vector3(camera_position.x, world_position.y, camera_position.z)", source)
        self.assertIn("flat_camera_position.direction_to(world_position)", source)
        self.assertIn("Face: 3DoF", hud)
        self.assertIn("_card_anchor.rotation_degrees", source)

    def test_moving_card_uses_yaw_pitch_depth_anchor_model(self):
        source = SCRIPT.read_text(encoding="utf-8")
        dispatcher = COMMAND_DISPATCHER.read_text(encoding="utf-8")
        hud = STATUS_HUD.read_text(encoding="utf-8")

        self.assertIn("CARD_START_YAW_DEG", source)
        self.assertIn("CARD_START_PITCH_DEG", source)
        self.assertIn("CARD_START_DEPTH_M", source)
        self.assertIn("var _anchor_yaw_deg", source)
        self.assertIn("var _anchor_pitch_deg", source)
        self.assertIn("var _anchor_depth_m", source)
        self.assertIn("_apply_3dof_anchor_transform()", source)
        self.assertIn('"yaw_left", "left", "move_left", "a":', dispatcher)
        self.assertIn('"yaw_right", "right", "move_right", "d":', dispatcher)
        self.assertIn('"pitch_up", "up", "move_up", "w":', dispatcher)
        self.assertIn('"pitch_down", "down", "move_down", "s":', dispatcher)
        self.assertIn('"depth_in", "closer":', dispatcher)
        self.assertIn('"depth_out", "farther":', dispatcher)
        self.assertIn("3DoF Anchor", hud)
        self.assertIn("Yaw/Pitch/Depth", hud)
        self.assertNotIn("world anchor", source.lower())
        self.assertNotIn("world anchor", hud.lower())

    def test_moving_card_starts_centered_for_visibility(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("const CARD_START_YAW_DEG := 0.0", source)
        self.assertIn("const CARD_START_PITCH_DEG := 0.0", source)
        self.assertIn("const CARD_DEFAULT_SPEED_DEG_PER_SECOND := 0.0", source)
        self.assertIn("const BBOX_START_CENTER_PX := Vector2(436.0, 326.0)", source)
        self.assertIn("const BBOX_IMAGE_SIZE := Vector2(872.0, 652.0)", source)

    def test_moving_card_supports_mock_bbox_anchor_mode(self):
        source = SCRIPT.read_text(encoding="utf-8")
        dispatcher = COMMAND_DISPATCHER.read_text(encoding="utf-8")
        hud = STATUS_HUD.read_text(encoding="utf-8")

        self.assertIn("BBOX_IMAGE_SIZE", source)
        self.assertIn("var _anchor_mode := \"manual\"", source)
        self.assertIn("var _bbox_center_px", source)
        self.assertIn("var _bbox_size_px", source)
        self.assertIn("var _bbox_depth_m", source)
        self.assertIn("_apply_bbox_anchor()", source)
        self.assertIn("_anchor_from_bbox(", source)
        self.assertIn('"toggle_bbox_mode"', dispatcher)
        self.assertIn('"bbox_left"', dispatcher)
        self.assertIn('"bbox_right"', dispatcher)
        self.assertIn('"bbox_up"', dispatcher)
        self.assertIn('"bbox_down"', dispatcher)
        self.assertIn('"bbox_depth_in"', dispatcher)
        self.assertIn('"bbox_depth_out"', dispatcher)
        self.assertIn("Mode: %s", hud)
        self.assertIn("BBox cx/cy/w/h", hud)
        self.assertIn("Angular W/H", hud)

    def test_moving_card_accepts_bbox_payloads_from_websocket(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('parsed.get("type", "") == "bbox"', source)
        self.assertIn("_apply_bbox_payload(parsed)", source)
        self.assertIn("_bbox_center_px = Vector2", source)
        self.assertIn("_bbox_size_px = Vector2", source)
        self.assertIn("_bbox_image_size = Vector2", source)

    def test_vst_tracker_boxes_drive_proxy_target_not_bbox_anchor(self):
        source = SCRIPT.read_text(encoding="utf-8")
        vst_capture = VST_CAPTURE.read_text(encoding="utf-8")

        self.assertIn("_apply_vst_tracker_anchor(boxes)", vst_capture)
        self.assertIn("func _apply_vst_tracker_anchor(boxes: PackedFloat32Array) -> void:", vst_capture)
        self.assertIn("_bbox_center_px = Vector2", source)
        self.assertIn("_bbox_size_px = Vector2", source)
        self.assertIn('_bbox_image_size = anchor.get("image_size", _bbox_image_size)', source)
        self.assertIn('"target_transform": target_transform', vst_capture)
        self.assertIn("update_vst_target(VST_TRACKED_TARGET_ID, target_transform, confidence, float(Time.get_ticks_msec()))", source)
        self.assertIn('_last_command = "vst_target"', source)
        self.assertIn("VST target:", source)

    def test_vst_tracker_updates_standard_trackable_target_proxy(self):
        source = SCRIPT.read_text(encoding="utf-8")
        target_source = TARGET_SOURCE.read_text(encoding="utf-8")
        vst_capture = VST_CAPTURE.read_text(encoding="utf-8")

        self.assertIn("class TrackableTarget", target_source)
        self.assertIn('const TRACKABLE_STATE_TRACKED := "tracked"', target_source)
        self.assertIn('const TRACKABLE_SOURCE_VST := "vst"', target_source)
        self.assertIn("class VSTTargetAdapter", target_source)
        self.assertIn("func update_target(target_id: String, transform: Transform3D, confidence: float, timestamp_ms: float) -> bool:", target_source)
        self.assertIn("func update_vst_target(target_id: String, transform: Transform3D, confidence: float, timestamp_ms: float) -> bool:", source)
        self.assertIn("var _vst_target_source = null", source)
        self.assertIn("TargetSourceScript.VSTTargetSource.new(", source)
        self.assertIn("var _vst_target_proxy: Node3D = null", source)
        self.assertIn('register_node3d_target(VST_TRACKED_TARGET_ID, _vst_target_proxy)', source)
        self.assertIn('attach_to_target(CARD_ANCHOR_NAME, VST_TRACKED_TARGET_ID, VST_TARGET_OFFSET_RULE)', source)
        self.assertIn("func tracker_box_to_target_transform(boxes: PackedFloat32Array, depth_m: float) -> Transform3D:", vst_capture)
        self.assertIn("target_transform.origin = target_position_from_bbox_anchor(anchor)", vst_capture)

    def test_vst_target_adapter_tracks_confidence_timestamp_and_fallback_states(self):
        source = SCRIPT.read_text(encoding="utf-8")
        target_source = TARGET_SOURCE.read_text(encoding="utf-8")
        hud = STATUS_HUD.read_text(encoding="utf-8")

        # The lost-state display default is rendered by StatusHud.
        self.assertIn("target_state=lost", hud)
        for marker in [
            "VST_TARGET_CONFIDENCE_THRESHOLD",
            "VST_TARGET_PREDICT_MS",
            "VST_TARGET_STALE_MS",
            "VST_TARGET_LOST_MS",
            "VST_TARGET_SMOOTHING_ALPHA",
        ]:
            self.assertIn(marker, source)
        for marker in [
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
            "set_on_target_lost(on_target_lost: Callable)",
        ]:
            self.assertIn(marker, target_source)
        self.assertIn("func _on_vst_target_lost(_target_id: String) -> void:", source)

    def test_vst_tracker_does_not_use_bbox_direct_anchor_inside_proxy_entrypoint(self):
        source = VST_CAPTURE.read_text(encoding="utf-8")
        match = re.search(
            r"func _apply_vst_tracker_anchor\(boxes: PackedFloat32Array\) -> void:(?P<body>.*?)(?=\n\nfunc |\Z)",
            source,
            re.S,
        )
        self.assertIsNotNone(match)
        body = match.group("body")

        self.assertNotIn('_anchor_mode = "bbox"', body)
        self.assertNotIn('_last_command = "vst_bbox"', body)
        self.assertNotIn("_apply_bbox_anchor()", body)
        self.assertIn("_on_anchor.call({", body)
        self.assertIn('"target_transform": target_transform', body)

    def test_vst_bbox_anchor_uses_right_eye_to_head_transform_when_available(self):
        source = SCRIPT.read_text(encoding="utf-8")
        vst_capture = VST_CAPTURE.read_text(encoding="utf-8")
        hud = STATUS_HUD.read_text(encoding="utf-8")

        self.assertIn("var _right_eye_to_head_matrix := PackedFloat64Array()", vst_capture)
        self.assertIn("var _uses_eye_to_head_anchor := false", vst_capture)
        self.assertIn("VST camera axes: +X right, +Y down, +Z forward", vst_capture)
        self.assertIn("var point_vst := Vector3(nx, ny, 1.0).normalized() * depth_m", vst_capture)
        self.assertIn("convert_vst_camera_point_to_head_convention(point_vst)", vst_capture)
        self.assertIn("store_right_eye_to_head_matrix(eye_info)", vst_capture)
        self.assertIn("func transform_right_vst_point_to_head(point: Vector3) -> Vector3:", vst_capture)
        self.assertIn("point_head = transform_right_vst_point_to_head(point_vst)", vst_capture)
        # The anchor-mode line is rendered by StatusHud from the vst snapshot.
        self.assertIn('"uses_eye_to_head_anchor": _uses_eye_to_head_anchor', vst_capture)
        self.assertIn("Anchor: %s", hud)
        self.assertIn('"eye2head" if _truthy(vst.get("uses_eye_to_head_anchor", false)) else "raw-fov"', hud)

    def test_vst_tracker_boxes_draw_visible_3d_bbox_frame(self):
        source = SCRIPT.read_text(encoding="utf-8")
        debug_ui = VST_DEBUG_UI.read_text(encoding="utf-8")

        self.assertIn("const VST_BBOX_FRAME_COLOR", debug_ui)
        self.assertIn("const VST_BBOX_FRAME_LINE_M", debug_ui)
        self.assertIn("const VST_BBOX_FRAME_Z_OFFSET_M", debug_ui)
        self.assertIn("var _world_bbox_frame_anchor: Node3D = null", debug_ui)
        self.assertIn("var _world_bbox_frame_parts: Array[MeshInstance3D] = []", debug_ui)
        self.assertIn("func build_world_bbox_frame(parent: Node3D) -> void:", debug_ui)
        self.assertIn('VSTBBoxFrame"', debug_ui)
        self.assertIn("var _vst_debug_ui = VSTDebugUIScript.new()", source)
        self.assertIn("_update_vst_bbox_frame()", source)
        self.assertIn("_set_vst_bbox_frame_visible(false)", source)
        self.assertIn("Callable(self, \"_orient_node_for_3dof_reading\")", source)

    def test_vst_tracker_debug_panel_draws_raw_right_image_bbox(self):
        source = SCRIPT.read_text(encoding="utf-8")
        debug_ui = VST_DEBUG_UI.read_text(encoding="utf-8")

        self.assertIn("const VST_RAW_DEBUG_PIXEL_SIZE_M", debug_ui)
        self.assertIn("var _raw_debug_anchor: Node3D = null", debug_ui)
        self.assertIn("var _raw_right_sprite: Sprite3D = null", debug_ui)
        self.assertIn("var _raw_bbox_parts: Array[MeshInstance3D] = []", debug_ui)
        self.assertIn("func build_raw_debug_panel(camera: Node3D) -> void:", debug_ui)
        self.assertIn('VSTRawDebugPanel"', debug_ui)
        self.assertIn("_raw_right_sprite.texture = ImageTexture.create_from_image(right_img)", debug_ui)
        self.assertIn("_vst_debug_ui.update_raw_bbox_overlay(boxes, image_size)", source)
        self.assertIn("(x + w * 0.5 - 0.5) * overlay_size.x", debug_ui)
        self.assertIn("(0.5 - y - h * 0.5) * overlay_size.y", debug_ui)

    def test_card_can_attach_to_registered_node3d_targets(self):
        source = SCRIPT.read_text(encoding="utf-8")
        registry = TARGET_REGISTRY.read_text(encoding="utf-8")
        attachment = CARD_ATTACHMENT.read_text(encoding="utf-8")

        self.assertIn("class Node3DTargetAdapter", registry)
        self.assertIn("func register(target_id: String, adapter: Node3DTargetAdapter) -> bool:", registry)
        self.assertIn("var _target_registry = TargetRegistryScript.new()", source)
        self.assertIn("func register_node3d_target(target_id: String, node_or_path", source)
        self.assertIn("func attach_to_target(card_id: String, target_id: String, offset_rule", source)
        # The store and the attach/fallback bodies moved to card_attachment.gd
        # in M3 step 4 (YAN-77); target lookup is wired back into the registry.
        self.assertIn("var _attachments := {}", attachment)
        self.assertIn('"hold_last_pose"', source)
        self.assertIn("_update_target_attachments()", source)
        self.assertIn("_card_attachment.set_resolver(_target_registry.resolve)", source)
        self.assertIn("adapter.get_global_transform()", attachment)
        self.assertIn("_offset_transform_for_adapter(adapter, offset_rule)", attachment)
        self.assertIn('adapter.get_meta_value("proxy_target_size_m", Vector3.ZERO)', attachment)
        self.assertIn("_card_state.mark_attached(target_id)", source)
        self.assertIn("_orient_card_for_3dof_reading()", source)
        self.assertRegex(source, r"if _anchor_mode == \"target\":\s+_update_target_attachments\(\)")

    def test_debug_marker_target_can_drive_real_device_validation(self):
        source = SCRIPT.read_text(encoding="utf-8")
        dispatcher = COMMAND_DISPATCHER.read_text(encoding="utf-8")
        builder = VALIDATION_SCENE_BUILDER.read_text(encoding="utf-8")

        self.assertIn("const DEBUG_NODE3D_TARGET_ENABLED := false", source)
        self.assertIn('const DEBUG_TARGET_ID := "debug_marker"', source)
        self.assertIn('var _debug_target_marker: MeshInstance3D = null', source)
        self.assertIn("func _build_debug_target_marker() -> void:", source)
        self.assertIn('marker.name = str(config.get("marker_name", "MovingTargetMarker"))', builder)
        self.assertIn("BoxMesh.new()", builder)
        self.assertIn('register_target.call(target_id, marker)', builder)
        self.assertIn('attach_card.call(card_id, target_id, offset_rule)', builder)
        self.assertIn('"offset_rule": {"mode": "right_top"', source)
        self.assertIn("func _update_debug_target_marker(delta: float) -> void:", source)
        self.assertIn("marker.position = Vector3(", builder)
        self.assertIn("sin(next_elapsed", builder)
        self.assertIn('"debug_target_free"', dispatcher)
        self.assertIn('"debug_target_reset"', dispatcher)
        self.assertIn("CommandDispatcherScript.EFFECT_DEBUG_TARGET_FREE", source)
        self.assertIn("CommandDispatcherScript.EFFECT_DEBUG_TARGET_RESET", source)

    def test_world_target_offset_ignores_target_rotation_for_card_position(self):
        source = SCRIPT.read_text(encoding="utf-8")
        # The offset-rule math moved to card_attachment.gd in M3 step 4
        # (YAN-77); the offset-space contract is pinned there.
        attachment = CARD_ATTACHMENT.read_text(encoding="utf-8")

        self.assertIn('"offset_space"', source)
        self.assertIn('"world"', source)
        self.assertIn('"target"', source)
        self.assertIn("static func world_offset_transform(target_transform: Transform3D, offset_rule) -> Transform3D:", attachment)
        self.assertIn("static func local_offset_transform(target_transform: Transform3D, offset_rule) -> Transform3D:", attachment)
        self.assertIn("result.origin = target_transform.origin + offset_vector(rule)", attachment)
        self.assertIn("result.origin = target_transform * offset_vector(rule)", attachment)
        self.assertIn('if str(rule.get("offset_space", "world")) == "target":', attachment)

    def test_debug_marker_uses_world_offset_while_rotating_for_pcmr_validation(self):
        source = SCRIPT.read_text(encoding="utf-8")
        builder = VALIDATION_SCENE_BUILDER.read_text(encoding="utf-8")

        self.assertIn('"offset_space": "world"', source)
        self.assertIn("marker.rotation_degrees", builder)
        self.assertIn("marker.position = Vector3(", builder)

    def test_proxy_targets_validation_mode_drives_real_card_wrapper(self):
        source = SCRIPT.read_text(encoding="utf-8")
        builder = VALIDATION_SCENE_BUILDER.read_text(encoding="utf-8")

        self.assertIn("const PROXY_TARGETS_VALIDATION_ENABLED := true", source)
        self.assertIn('const PROXY_TARGETS_SAMPLE_RES := "res://fixtures/proxy_targets_sample.json"', source)
        self.assertIn('preload("res://scripts/proxy_targets_consumer.gd")', source)
        self.assertIn('preload("res://scripts/proxy_targets_card_adapter.gd")', source)
        self.assertIn("var _proxy_targets_consumer: Node = null", source)
        self.assertIn("var _proxy_targets_card_adapter: Node = null", source)
        self.assertNotIn("var _proxy_targets_consumer: ProxyTargetsConsumer = null", source)
        self.assertNotIn("var _proxy_targets_card_adapter: ProxyTargetsCardAdapter = null", source)
        self.assertIn("func _build_proxy_targets_validation() -> void:", source)
        self.assertIn("func apply_proxy_targets_sample(target_source, sample_res: String) -> String:", builder)
        self.assertIn("adapter.bind(consumer, wrapper)", builder)
        self.assertIn("target_source_factory.call(adapter)", builder)
        self.assertIn("target_source.apply_proxy_targets_json(sample)", builder)
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
        self.assertIn("func set_default_offset_rule(offset_rule: Dictionary) -> void:", adapter)
        self.assertIn("var default_offset_rule := {", adapter)
        self.assertIn("func sync_card_wrapper() -> bool:", adapter)
        self.assertIn("return registered_ok and attached_ok", adapter)
        self.assertIn("return bool(card_wrapper.call(attach_method_name", adapter)

    def test_proxy_targets_sample_targets_real_card_anchor_without_raw_fields(self):
        sample = json.loads(PROXY_TARGETS_SAMPLE.read_text(encoding="utf-8"))

        self.assertEqual(sample["type"], "proxy_targets")
        self.assertEqual(sample["schema_version"], 1)
        self.assertEqual(sample["cards"][0]["card_id"], "CardAnchor")
        self.assertEqual(sample["cards"][0]["target_id"], sample["targets"][0]["target_id"])
        self.assertEqual(sample["cards"][0]["offset_rule"]["mode"], "depth_scaled_right_half_width")
        self.assertEqual(sample["cards"][0]["offset_rule"]["offset_space"], "world")
        self.assertEqual(sample["cards"][0]["offset_rule"]["depth_scale"], 1.3)
        self.assertEqual(sample["cards"][0]["offset_rule"]["depth_offset_m"], 0.0)
        self.assertEqual(sample["cards"][0]["offset_rule"]["right_width_fraction"], 0.5)
        self.assertEqual(sample["targets"][0]["target_size_m"]["width"], 0.72)
        self.assertEqual(sample["targets"][0]["coordinate_space"], "world")
        self.assertEqual(sample["targets"][0]["transform_space"], "world")
        serialized = json.dumps(sample)
        self.assertNotIn("bbox", serialized)
        self.assertNotIn("detection", serialized)

    def test_proxy_targets_live_websocket_consumer_is_wired(self):
        source = SCRIPT.read_text(encoding="utf-8")
        hud = STATUS_HUD.read_text(encoding="utf-8")
        # The peer/retry/subscribe loop itself moved to ws_transport.gd in M3
        # step 3 (YAN-76); see tests/test_godot_ws_transport.py for the full
        # transport contract.
        transport = WS_TRANSPORT.read_text(encoding="utf-8")
        fragment = PROXY_TARGETS_STATUS_FRAGMENT.read_text(encoding="utf-8")
        receiver = CARD_RECEIVER.read_text(encoding="utf-8")

        self.assertIn("const PROXY_TARGETS_WS_ENABLED := true", source)
        self.assertIn('const PROXY_TARGETS_WS_URL := "ws://127.0.0.1:8766/proxy_targets"', source)
        self.assertIn('const PROXY_TARGETS_STATUS_RES := "user://proxy_targets_live_status.json"', hud)
        self.assertIn("var _proxy_targets_ws = WSTransportScript.new()", source)
        self.assertIn("var _card_receiver = CardReceiverScript.new()", source)
        self.assertIn("var _messages_seen := 0", receiver)
        self.assertIn("var _subscribed := false", transport)
        self.assertIn("var _packets_seen := 0", transport)
        self.assertIn("var _parsed_messages := 0", fragment)
        self.assertIn("var _last_sequence := -1", fragment)
        self.assertIn("var _last_position := Vector3.ZERO", fragment)
        self.assertIn("var _last_packet_bytes := 0", transport)
        self.assertIn('var _last_packet_preview := "-"', fragment)
        self.assertIn('var _last_message_type := "-"', fragment)
        self.assertIn('var _last_error := "-"', fragment)
        self.assertIn("var _last_source_coordinate := {}", fragment)
        self.assertIn("var _proxy_targets_status_write_elapsed := 0.0", hud)
        self.assertIn("func connect_if_enabled() -> void:", receiver)
        self.assertIn("func poll(delta: float) -> void:", receiver)
        self.assertIn("func _send_subscribe_once() -> void:", transport)
        self.assertIn("func apply_live_payload(payload: String) -> bool:", receiver)
        self.assertIn("func record_parsed_message(message: Dictionary, head_info: Dictionary = {}) -> void:", fragment)
        self.assertIn("func _write_proxy_targets_status_file(snapshot: Dictionary, delta: float) -> void:", hud)
        self.assertIn("func _format_proxy_targets_status_line(proxy: Dictionary) -> String:", hud)
        self.assertIn("_card_receiver.connect_if_enabled()", source)
        self.assertIn("_card_receiver.poll(delta)", source)
        self.assertIn("_send_subscribe_once()", transport)
        self.assertIn("_proxy_targets_ws_url()", source)
        # URL/enable resolution is centralized in SmartXROptions (env var ->
        # user://smartxr_options.json -> const default); see
        # tests/test_godot_smartxr_options.py for the resolution contract.
        self.assertIn("_options.proxy_targets_ws_url(PROXY_TARGETS_WS_URL)", source)
        self.assertIn("_options.proxy_targets_ws_enabled(PROXY_TARGETS_WS_ENABLED)", source)
        self.assertIn("_options.control_ws_url(WS_URL)", source)
        self.assertIn("_ws.connect_to(_ws_url())", receiver)
        self.assertIn("connect_to(_control_ws_url())", source)
        self.assertIn("connect_to_url(url)", transport)
        self.assertIn("_packets_seen += 1", transport)
        self.assertIn("_last_packet_bytes = packet.size()", transport)
        self.assertIn("_status_fragment.set_packet_preview(_sanitize_status_text(payload))", receiver)
        self.assertIn("_target_source.apply_proxy_targets_json(payload)", receiver)
        self.assertIn("func _on_message_parsed(message: Dictionary) -> void:", receiver)
        self.assertIn("_status_fragment.record_parsed_message(message, head_info)", receiver)
        # Per-frame seam: the card assembles the snapshot, StatusHud writes the files.
        self.assertIn("_update_status_hud(delta)", source)
        self.assertIn("_status_hud.write_status_files(snapshot, delta)", source)
        self.assertIn("FileAccess.open(proxy_targets_status_path, FileAccess.WRITE)", hud)
        self.assertIn('"anchor_mode": _anchor_mode', source)
        self.assertIn('"attachments": _card_attachment.size()', source)
        self.assertIn('"card_target_id": _proxy_targets_card_target_id()', source)
        self.assertIn("func _proxy_targets_card_target_id() -> String:", source)
        self.assertIn('"proxy_target_count": _proxy_targets_proxy_count()', source)
        self.assertIn('"proxy_target_ids": _proxy_targets_proxy_ids()', source)
        self.assertIn('"last_proxy_position": _format_vec3(proxy.get("last_position", Vector3.ZERO))', hud)
        self.assertIn('"card_attach_target_id": str(proxy.get("card_target_id", ""))', hud)
        self.assertIn('"card_resolved_position": _proxy_targets_card_resolved_position()', source)
        self.assertIn('"card_node_position": _proxy_targets_card_node_position()', source)
        self.assertIn('"card_apply_count": _proxy_targets_card_apply_count', source)
        self.assertIn("var _proxy_targets_card_apply_count := 0", source)
        self.assertIn("func _proxy_targets_proxy_count() -> int:", source)
        self.assertIn("func _proxy_targets_proxy_ids() -> Array:", source)
        # Untyped returns (Vector3 or null); StatusHud formats null as "n/a".
        self.assertIn("func _proxy_targets_card_resolved_position():", source)
        self.assertIn("func _proxy_targets_card_node_position():", source)
        self.assertIn("_proxy_targets_card_apply_count += 1", source)
        self.assertIn('"packet_preview": _last_packet_preview', fragment)
        self.assertIn('"source_coordinate": _last_source_coordinate', fragment)
        self.assertIn('"source_coordinate_summary": _source_coordinate_summary(proxy.get("source_coordinate", {}))', hud)
        self.assertIn("func _source_coordinate_summary(source_coordinate) -> String:", hud)
        self.assertLess(receiver.index("_target_source.apply_proxy_targets_json(payload)"), receiver.index('_set_last_command("proxy_live")'))
        self.assertIn("ProxyWS: %s sub=%s packets=%d parsed=%d live=%d apply=%d seq=%d bytes=%d type=%s pos=%s card=%s src=%s err=%s", hud)
        self.assertIn('_set_last_command("proxy_live")', receiver)

    def test_fake_proxy_targets_publisher_exists_and_uses_stdlib_websocket(self):
        # The tools file is a compatibility wrapper; implementation lives in
        # the smartxr package (publisher/transport/cli layers).
        self.assertTrue(FAKE_PROXY_TARGETS_PUBLISHER.exists())
        wrapper = FAKE_PROXY_TARGETS_PUBLISHER.read_text(encoding="utf-8")
        publisher = (ROOT / "smartxr" / "publisher.py").read_text(encoding="utf-8")
        transport = (ROOT / "smartxr" / "transport.py").read_text(encoding="utf-8")
        schema = (ROOT / "smartxr" / "schema.py").read_text(encoding="utf-8")
        cli = (ROOT / "smartxr" / "cli" / "fake_publisher.py").read_text(encoding="utf-8")

        self.assertIn("build_fake_proxy_targets_message as build_proxy_targets_message", wrapper)
        self.assertIn("def build_fake_proxy_targets_message(", publisher)
        self.assertIn("def encode_websocket_text_frame(", transport)
        self.assertIn("def serve(", cli)
        self.assertIn("sequence: int = 0", publisher)
        self.assertIn("mode: str = \"moving\"", publisher)
        self.assertIn('"sequence": sequence', publisher)
        self.assertIn("sent seq=", cli)
        self.assertIn('choices=["moving", "static"]', cli)
        self.assertIn('"type": "proxy_targets"', publisher)
        self.assertIn("SCHEMA_VERSION = 1", schema)
        self.assertIn('"coordinate_space": "world"', publisher)
        self.assertIn('"transform_space": "world"', publisher)
        self.assertIn('"card_id": card_id', publisher)
        self.assertIn('"target_id": target_id', publisher)
        for source in (wrapper, publisher, transport, cli):
            self.assertNotIn("import websockets", source)
        for source in (wrapper, transport, cli):
            self.assertNotIn("bbox", source)
            self.assertNotIn("detection", source)

    def test_proxy_targets_consumer_converts_head_space_to_world(self):
        consumer = PROXY_TARGETS_CONSUMER.read_text(encoding="utf-8")

        self.assertIn("var head_reference: Node3D = null", consumer)
        self.assertIn('const HEAD_Z_MODE_NEGATIVE_FORWARD := "negative_z_forward"', consumer)
        self.assertIn('const HEAD_Z_MODE_POSITIVE_FORWARD := "positive_z_forward"', consumer)
        self.assertIn("var proxy_head_z_mode := HEAD_Z_MODE_NEGATIVE_FORWARD", consumer)
        self.assertIn("func set_head_reference(reference: Node3D) -> void:", consumer)
        self.assertIn("func set_proxy_head_z_mode(mode: String) -> void:", consumer)
        self.assertIn("func get_last_applied_target_info() -> Dictionary:", consumer)
        self.assertIn('target.get("transform_space"', consumer)
        self.assertIn('target.get("coordinate_space"', consumer)
        self.assertIn('source_coordinate.get("publisher_convention"', consumer)
        self.assertIn("func _is_head_coordinate_space(coordinate_space: String) -> bool:", consumer)
        self.assertIn("func _head_transform_for_runtime(head_transform: Transform3D) -> Transform3D:", consumer)
        self.assertIn("runtime_transform.origin.z = -runtime_transform.origin.z", consumer)
        self.assertIn("func _head_transform_to_world(head_transform: Transform3D) -> Transform3D:", consumer)
        self.assertIn("return head_reference.global_transform * head_transform", consumer)
        self.assertIn('proxy.set_meta("proxy_head_z_mode", proxy_head_z_mode)', consumer)
        self.assertIn('proxy.set_meta("proxy_runtime_local_position", runtime_local_position)', consumer)
        self.assertIn("world_from_head_applied", consumer)
        self.assertIn('"head_z_mode": proxy_head_z_mode', consumer)
        self.assertIn('"runtime_local_position": _vec3_to_array(runtime_local_position)', consumer)
        self.assertIn('"world_position": _vec3_to_array(parsed_transform.origin)', consumer)

    def test_proxy_targets_consumer_supports_dynamic_and_world_latched_modes(self):
        source = SCRIPT.read_text(encoding="utf-8")
        consumer = PROXY_TARGETS_CONSUMER.read_text(encoding="utf-8")

        self.assertIn('const PROXY_TARGETS_ANCHOR_MODE := "dynamic"', source)
        self.assertIn('const PROXY_TARGETS_HEAD_Z_MODE := "negative_z_forward"', source)
        self.assertIn("func _proxy_targets_anchor_mode() -> String:", source)
        self.assertIn("func _proxy_targets_head_z_mode() -> String:", source)
        self.assertIn("_options.proxy_targets_anchor_mode(PROXY_TARGETS_ANCHOR_MODE)", source)
        self.assertIn("_options.proxy_targets_head_z_mode(PROXY_TARGETS_HEAD_Z_MODE)", source)
        self.assertIn("set_proxy_anchor_mode(_proxy_targets_anchor_mode())", source)
        self.assertIn("set_proxy_head_z_mode(_proxy_targets_head_z_mode())", source)
        self.assertIn("func _reset_proxy_world_latches() -> void:", source)
        self.assertIn("CommandDispatcherScript.EFFECT_RESET_PROXY_WORLD_LATCHES", source)
        self.assertIn('const ANCHOR_MODE_DYNAMIC := "dynamic"', consumer)
        self.assertIn('const ANCHOR_MODE_WORLD_LATCHED := "world_latched"', consumer)
        self.assertIn("var proxy_anchor_mode := ANCHOR_MODE_DYNAMIC", consumer)
        self.assertIn("var _world_latches := {}", consumer)
        self.assertIn("var _world_latch_references := {}", consumer)
        self.assertIn("var _world_latch_sizes := {}", consumer)
        self.assertIn("func set_proxy_anchor_mode(mode: String) -> void:", consumer)
        self.assertIn("func reset_world_latches() -> void:", consumer)
        self.assertIn("func _apply_dynamic_hold(target_id: String, target: Dictionary, world_transform: Transform3D, current_world_transform: Transform3D, reference_transform: Transform3D, target_size_m: Vector3) -> Dictionary:", consumer)
        self.assertIn("func _apply_world_latch(target_id: String, target: Dictionary, world_transform: Transform3D, current_world_transform: Transform3D, reference_transform: Transform3D, target_size_m: Vector3) -> Dictionary:", consumer)
        self.assertIn('target.get("freshness"', consumer)
        self.assertIn('target.get("tracking_confidence"', consumer)
        self.assertIn('target.get("held"', consumer)
        self.assertIn("_world_latch_references[target_id] = reference_transform", consumer)
        self.assertIn("_world_latch_sizes[target_id] = target_size_m", consumer)
        self.assertIn('"world_latch_state": "dynamic_held"', consumer)
        self.assertIn('"world_latch_state": "dynamic_waiting_fresh"', consumer)
        self.assertIn("if proxy_anchor_mode == ANCHOR_MODE_DYNAMIC:", consumer)
        self.assertIn('target_size_m = latch_result.get("target_size_m", target_size_m)', consumer)
        self.assertIn('proxy.set_meta("proxy_anchor_mode", proxy_anchor_mode)', consumer)
        self.assertIn('proxy.set_meta("proxy_world_latched", world_latched)', consumer)
        self.assertIn('proxy.set_meta("proxy_world_latch_state", world_latch_state)', consumer)
        self.assertIn('proxy.set_meta("proxy_world_latch_reference_transform", offset_reference_transform)', consumer)
        self.assertIn('"anchor_mode": proxy_anchor_mode', consumer)
        self.assertIn('"world_latched": world_latched', consumer)
        self.assertIn('"world_latch_state": world_latch_state', consumer)

    def test_proxy_targets_status_reports_head_to_world_diagnostics(self):
        source = SCRIPT.read_text(encoding="utf-8")
        hud = STATUS_HUD.read_text(encoding="utf-8")
        fragment = PROXY_TARGETS_STATUS_FRAGMENT.read_text(encoding="utf-8")
        builder = VALIDATION_SCENE_BUILDER.read_text(encoding="utf-8")

        self.assertIn("camera", source)
        self.assertIn("consumer.set_head_reference(camera)", builder)
        self.assertIn("var _last_world_from_head_applied := false", fragment)
        self.assertIn("var _last_local_position := Vector3.ZERO", fragment)
        self.assertIn("var _last_runtime_local_position := Vector3.ZERO", fragment)
        self.assertIn("var _last_world_position := Vector3.ZERO", fragment)
        self.assertIn('var _last_head_z_mode := "negative_z_forward"', fragment)
        self.assertIn("get_last_applied_target_info", source)
        self.assertIn('"world_from_head_applied": _last_world_from_head_applied', fragment)
        self.assertIn('"local_position": _last_local_position', fragment)
        self.assertIn('"runtime_local_position": _last_runtime_local_position', fragment)
        self.assertIn('"world_position": _last_world_position', fragment)
        self.assertIn('"head_z_mode": _last_head_z_mode', fragment)
        self.assertIn('"proxy_local_position": _format_vec3(proxy.get("local_position", Vector3.ZERO))', hud)
        self.assertIn('"proxy_runtime_local_position": _format_vec3(proxy.get("runtime_local_position", Vector3.ZERO))', hud)
        self.assertIn('"proxy_world_position": _format_vec3(proxy.get("world_position", Vector3.ZERO))', hud)
        self.assertIn('"proxy_head_z_mode": str(proxy.get("head_z_mode", "negative_z_forward"))', hud)
        self.assertIn('"proxy_anchor_mode": str(proxy.get("anchor_mode", "dynamic"))', hud)
        self.assertIn('"proxy_world_latched": _truthy(proxy.get("world_latched", false))', hud)
        self.assertIn('"proxy_world_latch_state": str(proxy.get("world_latch_state", "-"))', hud)

    def test_moving_card_reports_xr_pose_for_tracking_diagnosis(self):
        source = SCRIPT.read_text(encoding="utf-8")
        hud = STATUS_HUD.read_text(encoding="utf-8")

        self.assertIn("var _xr_origin: XROrigin3D = null", source)
        # The card snapshots the raw poses; StatusHud formats them (null -> "n/a").
        self.assertIn('"camera_position": _camera.global_position if _camera != null else null', source)
        self.assertIn('"camera_rotation_degrees": _camera.global_rotation_degrees if _camera != null else null', source)
        self.assertIn('"xr_origin_position": _xr_origin.global_position if _xr_origin != null else null', source)
        self.assertIn('_format_vec3_or_na(snapshot.get("camera_position"))', hud)
        self.assertIn("Camera Pos xyz: %s", hud)
        self.assertIn("Camera Rot xyz: %s", hud)
        self.assertIn("XROrigin Pos xyz: %s", hud)

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

    def test_android_export_runner_preflights_templates_aar_signing_and_smoke(self):
        runner = ANDROID_EXPORT_RUNNER.read_text(encoding="utf-8")

        self.assertIn("SMARTXR_GODOT_EXE", runner)
        self.assertIn("PreflightOnly", runner)
        self.assertIn("android_source.zip", runner)
        self.assertIn("godot-lib.template_debug.aar", runner)
        self.assertIn("godot-lib.template_release.aar", runner)
        self.assertIn("themes.xml", runner)
        self.assertIn("JAVA_HOME", runner)
        self.assertIn("ANDROID_HOME", runner)
        self.assertIn("ANDROID_SDK_ROOT", runner)
        self.assertIn("GRADLE_USER_HOME", runner)
        self.assertIn("apksigner", runner)
        self.assertIn("verify --verbose", runner)
        self.assertIn("adb install -r", runner)
        self.assertIn("INSTALL_FAILED_UPDATE_INCOMPATIBLE", runner)
        self.assertIn("adb uninstall", runner)
        self.assertIn("adb reverse tcp:8766 tcp:8766", runner)
        self.assertIn("adb reverse tcp:8767 tcp:8767", runner)
        self.assertIn("pm list packages com.smartxr.godotcontrol", runner)

    def test_android_apk_workflow_doc_records_repeatable_device_steps(self):
        doc = ANDROID_WORKFLOW_DOC.read_text(encoding="utf-8")

        self.assertIn("tools\\export_android.ps1 -PreflightOnly", doc)
        self.assertIn("tools\\export_android.ps1", doc)
        self.assertIn("Godot 4.6.2", doc)
        self.assertIn("JDK 17", doc)
        self.assertIn("ANDROID_HOME", doc)
        self.assertIn("android_source.zip", doc)
        self.assertIn("godot-lib.template_debug.aar", doc)
        self.assertIn("apksigner verify --verbose", doc)
        self.assertIn("adb install -r godot-android\\builds\\SmartXR-Godot-Control.apk", doc)
        self.assertIn("adb reverse tcp:8766 tcp:8766", doc)
        self.assertIn("adb reverse tcp:8767 tcp:8767", doc)
        self.assertIn("adb shell pm list packages com.smartxr.godotcontrol", doc)

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
        # The transparent-composition setup moved to xr_bootstrap.gd in M3
        # step 5 (YAN-79); the card delegates and keeps the resolved state.
        bootstrap = XR_BOOTSTRAP.read_text(encoding="utf-8")
        project = (GODOT_ANDROID / "project.godot").read_text(encoding="utf-8")

        self.assertIn("_xr_bootstrap.try_init_xr(get_viewport())", source)
        self.assertIn("viewport.transparent_bg = true", bootstrap)
        self.assertIn("XRInterface.XR_ENV_BLEND_MODE_ALPHA_BLEND", bootstrap)
        self.assertIn("blend=alpha", bootstrap)
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
        themes = (res_dir / "values" / "themes.xml").read_text(encoding="utf-8")
        self.assertNotIn("@mipmap/icon_background", themes)
        self.assertIn("@color/icon_background", themes)


if __name__ == "__main__":
    unittest.main()
