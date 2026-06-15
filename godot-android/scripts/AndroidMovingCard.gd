extends Node3D

const CARD_ANCHOR_NAME := "CardAnchor"
const CARD_VIEWPORT_SIZE := Vector2i(720, 1080)
const CARD_SIZE_M := Vector2(0.72, 1.08)
const XR_PROBE_SIZE_M := Vector2(0.18, 0.18)
const CARD_START_YAW_DEG := 0.0
const CARD_END_YAW_DEG := -32.0
const CARD_START_PITCH_DEG := 0.0
const CARD_START_DEPTH_M := 1.35
const CARD_DEFAULT_SPEED_DEG_PER_SECOND := 0.0
const CARD_SPEED_STEP_DEG_PER_SECOND := 2.0
const CARD_YAW_STEP_DEG := 3.0
const CARD_PITCH_STEP_DEG := 3.0
const CARD_DEPTH_STEP_M := 0.10
const BBOX_IMAGE_SIZE := Vector2(872.0, 652.0)
const BBOX_START_CENTER_PX := Vector2(436.0, 326.0)
const BBOX_START_SIZE_PX := Vector2(180.0, 240.0)
const BBOX_CENTER_STEP_PX := 32.0
const BBOX_DEPTH_STEP_M := 0.10
const BBOX_HORIZONTAL_FOV_DEG := 70.0
const BBOX_VERTICAL_FOV_DEG := 43.0
const MIN_SPEED_DEG_PER_SECOND := 0.0
const MAX_SPEED_DEG_PER_SECOND := 45.0
const MIN_DEPTH_M := 0.65
const MAX_DEPTH_M := 4.0
# Default flipped from the historical dev-machine LAN IP (10.1.98.195) to
# loopback per the owner's decision on YAN-76; deployments override via
# SMARTXR_CONTROL_WS_URL or user://smartxr_options.json (ADR-2).
const WS_URL := "ws://127.0.0.1:8766/control"
const DEBUG_NODE3D_TARGET_ENABLED := false
const DEBUG_TARGET_ID := "debug_marker"
const DEBUG_TARGET_SIZE_M := Vector3(0.12, 0.12, 0.12)
const DEBUG_TARGET_BASE_POSITION := Vector3(0.0, 0.0, -1.15)
const DEBUG_TARGET_RADIUS_M := 0.28
const PROXY_TARGETS_VALIDATION_ENABLED := true
const PROXY_TARGETS_SAMPLE_RES := "res://fixtures/proxy_targets_sample.json"
const PROXY_TARGETS_WS_ENABLED := true
const PROXY_TARGETS_WS_URL := "ws://127.0.0.1:8766/proxy_targets"
const PASSTHROUGH_OVERLAY_ENV := "SMARTXR_USE_PASSTHROUGH_OVERLAY"
const PASSTHROUGH_OVERLAY_VIEWPORT_SIZE := Vector2i(512, 256)
const PASSTHROUGH_OVERLAY_QUAD_SIZE_M := Vector2(0.42, 0.20)
const PASSTHROUGH_OVERLAY_DEPTH_M := 1.5
const CardAttachmentScript := preload("res://scripts/card_attachment.gd")
const ProxyTargetsConsumerScript := preload("res://scripts/proxy_targets_consumer.gd")
const ProxyTargetsCardAdapterScript := preload("res://scripts/proxy_targets_card_adapter.gd")
const SmartXROptionsScript := preload("res://scripts/smartxr_options.gd")
const StatusHudScript := preload("res://scripts/status_hud.gd")
const TargetRegistryScript := preload("res://scripts/target_registry.gd")
const TargetSourceScript := preload("res://scripts/target_source.gd")
const VSTCaptureScript := preload("res://scripts/vst_capture.gd")
const WSTransportScript := preload("res://scripts/ws_transport.gd")
const XRBootstrapScript := preload("res://scripts/xr_bootstrap.gd")

# Centralized runtime configuration (env var -> user://smartxr_options.json
# -> script const default). The consts below stay as the defaults; deployment
# overrides go through SmartXROptions instead of source edits.
var _options = SmartXROptionsScript.load_options()

# M1 (YAN-56): on-device VST capture + ncnn tracker scaffold.
# Functional behaviour is gated on GXRDualVstCapture class registration so the
# scene still loads on a vanilla GXR SDK; activation requires the fat libgxr_sdk
# from Godot_card (see addons/gxr_sdk/VERSION.txt).
const VST_NCNN_PARAM_RES := "res://ncnn/yolov8n_320.opt.ncnn.param"
const VST_NCNN_BIN_RES := "res://ncnn/yolov8n_320.opt.ncnn.bin"
const VST_NCNN_PARAM_USER := "user://ncnn/yolov8n_320.opt.ncnn.param"
const VST_NCNN_BIN_USER := "user://ncnn/yolov8n_320.opt.ncnn.bin"
const VST_RIGHT_TRACKER_ENABLED := true
const VST_RIGHT_TRACKER_FRAME_STRIDE := 5
const VST_BBOX_FRAME_COLOR := Color(1.0, 0.88, 0.05, 1.0)
const VST_BBOX_FRAME_LINE_M := 0.018
const VST_BBOX_FRAME_Z_OFFSET_M := 0.04
const VST_RAW_DEBUG_PIXEL_SIZE_M := 0.00045
const VST_RAW_DEBUG_POSITION := Vector3(0.48, -0.28, -1.2)
const VST_RAW_DEBUG_FRAME_Z_OFFSET_M := 0.025
const VST_TRACKED_TARGET_ID := "vst_right_target"
const VST_TARGET_CONFIDENCE_THRESHOLD := 0.45
const VST_TARGET_PREDICT_MS := 180.0
const VST_TARGET_STALE_MS := 650.0
const VST_TARGET_LOST_MS := 1400.0
const VST_TARGET_SMOOTHING_ALPHA := 0.38
const VST_TARGET_OFFSET_RULE := {
	"mode": "right_top",
	"offset_space": "world",
	"right_m": 0.35,
	"up_m": 0.25,
	"fallback": CardAttachmentScript.TARGET_FALLBACK_HOLD_LAST_POSE,
}
const GXR_CAL_CV_DEWARP_L := 0x00400060
const GXR_CAL_CV_DEWARP_R := 0x00400061
const GXR_CAL_CV_SLAM := 0x00400070


# XR bootstrap subsystem (scripts/xr_bootstrap.gd): the OpenXR startup path
# (interface lookup/initialize, viewport use_xr/transparent_bg, the
# alpha-blend request, vsync disable) and the camera/origin construction,
# extracted in M3 step 5. The card keeps the resolved XR state in the vars
# below and the status snapshot (ADR-4); the fallback camera's look_at target
# routes back through _anchor_position_from_yaw_pitch_depth in
# _setup_xr_bootstrap(). Untyped `=` on purpose (no class_name reference) so
# script-only probes can load both scripts.
var _xr_bootstrap = XRBootstrapScript.new()
var _xr_active := false
var _xr_interface_found := false
var _xr_initialize_ok := false
var _xr_init_error := "not attempted"
var _xr_origin: XROrigin3D = null
var _camera: Camera3D = null
# WS transport subsystem (scripts/ws_transport.gd): each instance owns one
# WebSocketPeer plus the shared connect/poll/2.0 s retry-on-close loop,
# extracted in M3 step 3. The card resolves URLs and enable gates through
# _options and handles every packet itself (ADR-4); the transports only move
# bytes. Untyped `=` on purpose (no class_name reference) so script-only
# probes can load both scripts; wiring happens in _setup_ws_transports().
var _control_ws = WSTransportScript.new()
var _card_viewport: SubViewport = null
var _card_anchor: Node3D = null
var _card_mesh: MeshInstance3D = null
var _xr_probe_mesh: MeshInstance3D = null
var _vst_bbox_frame_anchor: Node3D = null
var _vst_bbox_frame_parts: Array[MeshInstance3D] = []
var _vst_raw_debug_anchor: Node3D = null
var _vst_raw_right_sprite: Sprite3D = null
var _vst_raw_bbox_parts: Array[MeshInstance3D] = []
# Status HUD subsystem (scripts/status_hud.gd): renders the diagnostics label
# and writes the user:// status files from the snapshot this script assembles
# per frame in _build_status_snapshot(). Untyped Node on purpose (no
# class_name reference) so script-only probes can load both scripts.
var _status_hud: Node = null
var _speed_deg_per_second := CARD_DEFAULT_SPEED_DEG_PER_SECOND
var _anchor_yaw_deg := CARD_START_YAW_DEG
var _anchor_pitch_deg := CARD_START_PITCH_DEG
var _anchor_depth_m := CARD_START_DEPTH_M
var _anchor_mode := "manual"
var _bbox_center_px := BBOX_START_CENTER_PX
var _bbox_size_px := BBOX_START_SIZE_PX
var _bbox_image_size := BBOX_IMAGE_SIZE
var _bbox_depth_m := CARD_START_DEPTH_M
var _bbox_angular_size_deg := Vector2.ZERO
var _paused := false
var _face_camera_enabled := true
var _last_command := "none"
# Target registry subsystem (scripts/target_registry.gd): id -> adapter
# bookkeeping plus the Node3D/NodePath adapter, extracted in M3 step 2.
# Untyped `=` on purpose (no class_name reference) so script-only probes can
# load both scripts; see _options above for the same pattern.
var _target_registry = TargetRegistryScript.new()
# Card attachment subsystem (scripts/card_attachment.gd): the card_id ->
# attachment store, the per-frame attachment pass, the fallback state machine,
# and the offset-rule math, extracted in M3 step 4. The card keeps its public
# API (attach_to_target / detach_card), anchor-mode switching, orientation,
# and the status snapshot (ADR-4); target lookup is wired back into
# _target_registry in _setup_card_attachment(). Untyped `=` on purpose (no
# class_name reference) so script-only probes can load both scripts.
var _card_attachment = CardAttachmentScript.new()
var _debug_target_marker: MeshInstance3D = null
var _debug_target_elapsed_seconds := 0.0
var _vst_target_source = null
var _vst_target_proxy: Node3D = null
var _proxy_targets_consumer: Node = null
var _proxy_targets_card_adapter: Node = null
var _proxy_targets_target_source = null
# Second WSTransport instance (see _control_ws above): the proxy_targets
# stream adds the subscribe-once-on-open payload on top of the same loop.
var _proxy_targets_ws = WSTransportScript.new()
var _proxy_targets_parsed_messages := 0
var _proxy_targets_live_messages := 0
var _proxy_targets_last_sequence := -1
var _proxy_targets_last_position := Vector3.ZERO
var _proxy_targets_last_packet_preview := "-"
var _proxy_targets_last_message_type := "-"
var _proxy_targets_last_error := "-"
var _proxy_targets_last_source_coordinate := {}
var _proxy_targets_last_world_from_head_applied := false
var _proxy_targets_last_local_position := Vector3.ZERO
var _proxy_targets_last_world_position := Vector3.ZERO
var _proxy_targets_card_apply_count := 0
var _passthrough_overlay_enabled := false
var _passthrough_overlay_blend_ok := false
var _passthrough_overlay_requested_blend_mode := "alpha_blend"
var _passthrough_overlay_viewport: SubViewport = null
var _passthrough_overlay_layer: OpenXRCompositionLayerQuad = null

# VSTCapture subsystem (scripts/vst_capture.gd): owns GXRDualVstCapture setup,
# right-frame polling, tracker boxes, calibration diagnostics, and bbox->head
# math. The card keeps scene/UI side effects, target update wiring, and status
# snapshot assembly (ADR-4).
var _vst_capture = VSTCaptureScript.new({
	"ncnn_param_res": VST_NCNN_PARAM_RES,
	"ncnn_bin_res": VST_NCNN_BIN_RES,
	"ncnn_param_user": VST_NCNN_PARAM_USER,
	"ncnn_bin_user": VST_NCNN_BIN_USER,
	"right_tracker_enabled": VST_RIGHT_TRACKER_ENABLED,
	"right_tracker_frame_stride": VST_RIGHT_TRACKER_FRAME_STRIDE,
	"horizontal_fov_deg": BBOX_HORIZONTAL_FOV_DEG,
	"vertical_fov_deg": BBOX_VERTICAL_FOV_DEG,
	"min_depth_m": MIN_DEPTH_M,
	"max_depth_m": MAX_DEPTH_M,
	"start_depth_m": CARD_START_DEPTH_M,
})
var _vst_class_registered := false
var _vst_init_ok := false
var _vst_last_error := "not initialized"
var _vst_right_image_size := Vector2.ZERO
var _vst_right_frames := 0
var _vst_first_box := PackedFloat32Array()
var _vst_box_count := 0
var _vst_tracker_latency_ms := -1.0
var _vst_anchor_updates := 0
var _vst_eye_to_head_status := "eye2head: not queried"
var _vst_calibration_status := "cal: not queried"
var _vst_right_eye_to_head_matrix := PackedFloat64Array()
var _vst_uses_eye_to_head_anchor := false


func _ready() -> void:
	_passthrough_overlay_enabled = _use_passthrough_overlay()
	_setup_card_attachment()
	_setup_xr_bootstrap()
	_try_init_xr()
	_setup_camera()
	_build_passthrough_overlay_layer()
	_build_vst_raw_debug_panel()
	_setup_light()
	_build_card_anchor()
	_build_xr_render_probe()
	_build_vst_bbox_frame()
	_build_status_hud()
	_build_vst_target_proxy()
	_build_debug_target_marker()
	_build_proxy_targets_validation()
	_setup_ws_transports()
	_connect_ws()
	_connect_proxy_targets_ws()
	_setup_vst_capture()
	set_process(true)


## Wires the XRBootstrap subsystem: the fallback camera's look_at target
## routes back into the card's 3DoF anchor math so state resolution stays
## where the state lives (ADR-4). The interface lookup keeps the subsystem's
## default OpenXR lookup; probes inject fakes instead.
func _setup_xr_bootstrap() -> void:
	_xr_bootstrap.set_fallback_look_at_provider(_anchor_position_from_yaw_pitch_depth)


## Delegates the XR startup path to xr_bootstrap.gd, then copies the results
## into the card's state so every status-snapshot key keeps identical values
## (ADR-4): the xr.* keys read _xr_*, the passthrough_overlay blend keys read
## _passthrough_overlay_requested_blend_mode / _passthrough_overlay_blend_ok.
func _try_init_xr() -> void:
	_xr_bootstrap.try_init_xr(get_viewport())
	_xr_interface_found = _xr_bootstrap.interface_found()
	_xr_initialize_ok = _xr_bootstrap.initialize_ok()
	_xr_active = _xr_bootstrap.xr_active()
	_xr_init_error = _xr_bootstrap.init_error()
	_passthrough_overlay_requested_blend_mode = _xr_bootstrap.requested_blend_mode()
	_passthrough_overlay_blend_ok = _xr_bootstrap.blend_request_ok()


func _use_passthrough_overlay() -> bool:
	var value := OS.get_environment(PASSTHROUGH_OVERLAY_ENV).strip_edges().to_lower()
	return ["1", "true", "yes", "on"].has(value)


func _build_passthrough_overlay_layer() -> void:
	if not _passthrough_overlay_enabled:
		return
	if not _xr_active:
		return
	_passthrough_overlay_viewport = SubViewport.new()
	_passthrough_overlay_viewport.name = "PassthroughOverlayViewport"
	_passthrough_overlay_viewport.size = PASSTHROUGH_OVERLAY_VIEWPORT_SIZE
	_passthrough_overlay_viewport.transparent_bg = true
	_passthrough_overlay_viewport.disable_3d = true
	_passthrough_overlay_viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(_passthrough_overlay_viewport)
	_passthrough_overlay_viewport.add_child(_make_passthrough_overlay_ui())

	_passthrough_overlay_layer = OpenXRCompositionLayerQuad.new()
	_passthrough_overlay_layer.name = "AntmanPassthroughOverlayLayer"
	_passthrough_overlay_layer.layer_viewport = _passthrough_overlay_viewport
	_passthrough_overlay_layer.quad_size = PASSTHROUGH_OVERLAY_QUAD_SIZE_M
	# Antman_Smart gotcha: default false makes transparent viewport areas compose as black.
	_passthrough_overlay_layer.alpha_blend = true
	_passthrough_overlay_layer.visible = true
	add_child(_passthrough_overlay_layer)
	_update_passthrough_overlay_layer()


func _make_passthrough_overlay_ui() -> Control:
	var root := Control.new()
	root.name = "PassthroughOverlayUI"
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.size = Vector2(PASSTHROUGH_OVERLAY_VIEWPORT_SIZE)

	var panel := ColorRect.new()
	panel.name = "PassthroughOverlayPanel"
	panel.set_anchors_preset(Control.PRESET_FULL_RECT)
	panel.color = Color(0.05, 1.0, 0.35, 0.58)
	root.add_child(panel)

	var label := Label.new()
	label.name = "PassthroughOverlayLabel"
	label.text = "PASSTHROUGH OVERLAY"
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.set_anchors_preset(Control.PRESET_FULL_RECT)
	label.add_theme_font_size_override("font_size", 34)
	label.add_theme_color_override("font_color", Color(0.0, 0.05, 0.02, 1.0))
	root.add_child(label)
	return root


## Delegates camera/origin construction to xr_bootstrap.gd (XROrigin3D +
## XRCamera3D when XR is active, FallbackCamera otherwise) and copies the
## nodes back so the snapshot keys camera_position / camera_rotation_degrees /
## xr_origin_position keep identical values (ADR-4).
func _setup_camera() -> void:
	_xr_bootstrap.setup_camera(self)
	_xr_origin = _xr_bootstrap.xr_origin()
	_camera = _xr_bootstrap.camera()


func _setup_light() -> void:
	var light := DirectionalLight3D.new()
	light.name = "CardLight"
	light.rotation_degrees = Vector3(-25.0, 20.0, 0.0)
	light.light_energy = 1.25
	add_child(light)


func _build_card_anchor() -> void:
	_card_viewport = SubViewport.new()
	_card_viewport.name = "CardViewport"
	_card_viewport.size = CARD_VIEWPORT_SIZE
	_card_viewport.transparent_bg = true
	_card_viewport.disable_3d = true
	_card_viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(_card_viewport)
	_card_viewport.add_child(_make_card_ui())

	_card_anchor = Node3D.new()
	_card_anchor.name = CARD_ANCHOR_NAME
	add_child(_card_anchor)

	var mesh := QuadMesh.new()
	mesh.size = CARD_SIZE_M

	var material := StandardMaterial3D.new()
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_texture = _card_viewport.get_texture()
	material.albedo_color = Color(1.0, 1.0, 1.0, 1.0)
	material.no_depth_test = false
	material.cull_mode = BaseMaterial3D.CULL_DISABLED

	_card_mesh = MeshInstance3D.new()
	_card_mesh.name = "CardPanel"
	_card_mesh.mesh = mesh
	_card_mesh.set_surface_override_material(0, material)
	_card_anchor.add_child(_card_mesh)
	_apply_3dof_anchor_transform()


func _build_xr_render_probe() -> void:
	if _card_anchor == null:
		return
	var mesh := QuadMesh.new()
	mesh.size = XR_PROBE_SIZE_M

	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_color = Color(1.0, 0.05, 0.05, 1.0)
	material.no_depth_test = true
	material.cull_mode = BaseMaterial3D.CULL_DISABLED

	_xr_probe_mesh = MeshInstance3D.new()
	_xr_probe_mesh.name = "XRRenderProbe"
	_xr_probe_mesh.mesh = mesh
	_xr_probe_mesh.position = Vector3(-0.56, 0.58, 0.025)
	_xr_probe_mesh.set_surface_override_material(0, material)
	_card_anchor.add_child(_xr_probe_mesh)


func _build_vst_bbox_frame() -> void:
	_vst_bbox_frame_anchor = Node3D.new()
	_vst_bbox_frame_anchor.name = "VSTBBoxFrame"
	_vst_bbox_frame_anchor.visible = false
	add_child(_vst_bbox_frame_anchor)

	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_color = VST_BBOX_FRAME_COLOR
	material.no_depth_test = true
	material.cull_mode = BaseMaterial3D.CULL_DISABLED

	for part_name in ["Top", "Bottom", "Left", "Right"]:
		var part := MeshInstance3D.new()
		part.name = "VSTBBoxFrame" + part_name
		part.mesh = QuadMesh.new()
		part.set_surface_override_material(0, material)
		_vst_bbox_frame_anchor.add_child(part)
		_vst_bbox_frame_parts.append(part)


func _build_vst_raw_debug_panel() -> void:
	if _camera == null:
		return
	_vst_raw_debug_anchor = Node3D.new()
	_vst_raw_debug_anchor.name = "VSTRawDebugPanel"
	_vst_raw_debug_anchor.position = VST_RAW_DEBUG_POSITION
	_camera.add_child(_vst_raw_debug_anchor)

	_vst_raw_right_sprite = Sprite3D.new()
	_vst_raw_right_sprite.name = "VSTRawRightImage"
	_vst_raw_right_sprite.pixel_size = VST_RAW_DEBUG_PIXEL_SIZE_M
	_vst_raw_right_sprite.no_depth_test = true
	_vst_raw_right_sprite.modulate = Color(1.0, 1.0, 1.0, 0.72)
	_vst_raw_debug_anchor.add_child(_vst_raw_right_sprite)

	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_color = VST_BBOX_FRAME_COLOR
	material.no_depth_test = true
	material.cull_mode = BaseMaterial3D.CULL_DISABLED

	for part_name in ["Top", "Bottom", "Left", "Right"]:
		var part := MeshInstance3D.new()
		part.name = "VSTRawBBox" + part_name
		part.mesh = QuadMesh.new()
		part.visible = false
		part.set_surface_override_material(0, material)
		_vst_raw_debug_anchor.add_child(part)
		_vst_raw_bbox_parts.append(part)

	var label := Label3D.new()
	label.name = "VSTRawDebugLabel"
	label.text = "RAW VST"
	label.font_size = 18
	label.no_depth_test = true
	label.modulate = VST_BBOX_FRAME_COLOR
	label.position = Vector3(0.0, 0.19, 0.02)
	_vst_raw_debug_anchor.add_child(label)


func _make_card_ui() -> Control:
	var panel := PanelContainer.new()
	panel.name = "MovingCardUI"
	panel.set_anchors_preset(Control.PRESET_FULL_RECT)
	panel.offset_left = 24
	panel.offset_top = 24
	panel.offset_right = -24
	panel.offset_bottom = -24
	panel.add_theme_stylebox_override("panel", _make_panel_style())

	var margin := MarginContainer.new()
	margin.set_anchors_preset(Control.PRESET_FULL_RECT)
	margin.add_theme_constant_override("margin_left", 48)
	margin.add_theme_constant_override("margin_top", 56)
	margin.add_theme_constant_override("margin_right", 48)
	margin.add_theme_constant_override("margin_bottom", 56)
	panel.add_child(margin)

	var body := VBoxContainer.new()
	body.alignment = BoxContainer.ALIGNMENT_CENTER
	body.add_theme_constant_override("separation", 18)
	margin.add_child(body)

	body.add_child(_make_label("安炫百  C17PROJ-90", 58, Color(0.95, 1.0, 0.35, 1.0)))
	body.add_child(_make_label("Jira issues: 1", 38, Color(0.72, 0.95, 1.0, 1.0)))
	body.add_child(_make_label("Matting 效果", 50, Color(0.92, 0.98, 1.0, 1.0)))
	body.add_child(_make_label("Status: New    Priority: Medium", 36, Color(0.72, 0.95, 1.0, 1.0)))
	body.add_child(_make_label("Updated: 2026-03-05", 30, Color(0.62, 0.82, 0.92, 1.0)))
	return panel


func _make_label(text: String, font_size: int, color: Color) -> Label:
	var label := Label.new()
	label.text = text
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	label.add_theme_color_override("font_outline_color", Color(0.0, 0.0, 0.0, 0.82))
	label.add_theme_constant_override("outline_size", 5)
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return label


func _build_status_hud() -> void:
	_status_hud = StatusHudScript.new()
	_status_hud.name = "StatusHud"
	add_child(_status_hud)
	_status_hud.build_status_label(_card_anchor)
	_status_hud.update_status_label(_build_status_snapshot())


func _build_debug_target_marker() -> void:
	if not DEBUG_NODE3D_TARGET_ENABLED:
		return
	if _debug_target_marker != null and is_instance_valid(_debug_target_marker):
		_debug_target_marker.queue_free()
	var marker := MeshInstance3D.new()
	marker.name = "MovingTargetMarker"
	var mesh := BoxMesh.new()
	mesh.size = DEBUG_TARGET_SIZE_M
	marker.mesh = mesh
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_color = Color(1.0, 0.92, 0.1, 1.0)
	material.no_depth_test = true
	material.cull_mode = BaseMaterial3D.CULL_DISABLED
	marker.set_surface_override_material(0, material)
	marker.position = DEBUG_TARGET_BASE_POSITION
	add_child(marker)
	_debug_target_marker = marker
	_debug_target_elapsed_seconds = 0.0
	register_node3d_target(DEBUG_TARGET_ID, _debug_target_marker)
	attach_to_target(CARD_ANCHOR_NAME, DEBUG_TARGET_ID, {"mode": "right_top", "offset_space": "world", "right_m": 0.35, "up_m": 0.25, "fallback": "hold_last_pose"})
	print("Debug Node3D target attached: %s marker=%s" % [DEBUG_TARGET_ID, marker.name])


func _build_proxy_targets_validation() -> void:
	if not PROXY_TARGETS_VALIDATION_ENABLED:
		return
	_proxy_targets_consumer = ProxyTargetsConsumerScript.new()
	_proxy_targets_consumer.name = "ProxyTargetsConsumer"
	if _camera != null and _proxy_targets_consumer.has_method("set_head_reference"):
		_proxy_targets_consumer.set_head_reference(_camera)
	add_child(_proxy_targets_consumer)
	_proxy_targets_card_adapter = ProxyTargetsCardAdapterScript.new()
	_proxy_targets_card_adapter.name = "ProxyTargetsCardAdapter"
	add_child(_proxy_targets_card_adapter)
	_proxy_targets_card_adapter.bind(_proxy_targets_consumer, self)
	_proxy_targets_target_source = TargetSourceScript.ProxyTargetsTargetSource.new(_proxy_targets_card_adapter)
	_apply_proxy_targets_sample()
	_proxy_targets_target_source.set_on_message_parsed(_on_proxy_targets_message_parsed)


func _apply_proxy_targets_sample() -> void:
	if _proxy_targets_target_source == null:
		return
	if not FileAccess.file_exists(PROXY_TARGETS_SAMPLE_RES):
		_last_command = "proxy_sample_missing"
		return
	var sample := FileAccess.get_file_as_string(PROXY_TARGETS_SAMPLE_RES)
	if sample.is_empty():
		_last_command = "proxy_sample_empty"
		return
	var applied: bool = bool(_proxy_targets_target_source.apply_proxy_targets_json(sample))
	_last_command = "proxy_sample" if applied else "proxy_sample_failed"


func _connect_proxy_targets_ws() -> void:
	if not _proxy_targets_ws_enabled():
		return
	_proxy_targets_ws.connect_to(_proxy_targets_ws_url())


func _proxy_targets_ws_enabled() -> bool:
	return _options.proxy_targets_ws_enabled(PROXY_TARGETS_WS_ENABLED)


func _proxy_targets_ws_url() -> String:
	return _options.proxy_targets_ws_url(PROXY_TARGETS_WS_URL)


func _control_ws_url() -> String:
	return _options.control_ws_url(WS_URL)


func _poll_proxy_targets_ws(delta: float) -> void:
	if not _proxy_targets_ws_enabled():
		return
	_proxy_targets_ws.poll(delta)


func _on_proxy_targets_ws_packet(payload: String) -> void:
	_proxy_targets_last_packet_preview = StatusHudScript.sanitize_status_text(payload)
	_apply_proxy_targets_live_payload(payload)


func _apply_proxy_targets_live_payload(payload: String) -> void:
	if _proxy_targets_target_source == null:
		_proxy_targets_last_error = "adapter_null"
		return
	var applied: bool = bool(_proxy_targets_target_source.apply_proxy_targets_json(payload))
	var source_error := str(_proxy_targets_target_source.last_error())
	if source_error == "json_invalid":
		_proxy_targets_last_message_type = "invalid"
		_proxy_targets_last_error = "json_invalid"
		_last_command = "proxy_live_invalid"
		return
	if applied:
		_proxy_targets_live_messages += 1
		_proxy_targets_last_error = "-"
		_last_command = "proxy_live"
	else:
		_proxy_targets_last_error = source_error
		_last_command = "proxy_live_failed"


func _on_proxy_targets_message_parsed(message: Dictionary) -> void:
	_proxy_targets_parsed_messages += 1
	_record_proxy_targets_diagnostics(message)


func _record_proxy_targets_diagnostics(message: Dictionary) -> void:
	_proxy_targets_last_message_type = str(message.get("type", "-"))
	_proxy_targets_last_sequence = int(message.get("sequence", _proxy_targets_last_sequence))
	var targets = message.get("targets", [])
	if not (targets is Array) or targets.is_empty():
		return
	var target = targets[0]
	if typeof(target) != TYPE_DICTIONARY:
		return
	var transform = target.get("transform", {})
	if typeof(transform) != TYPE_DICTIONARY:
		return
	var position = transform.get("position", [])
	if not (position is Array) or position.size() < 3:
		return
	_proxy_targets_last_position = Vector3(float(position[0]), float(position[1]), float(position[2]))
	var source_coordinate = target.get("source_coordinate", {})
	if typeof(source_coordinate) == TYPE_DICTIONARY:
		_proxy_targets_last_source_coordinate = source_coordinate.duplicate(true)
	else:
		_proxy_targets_last_source_coordinate = {}
	_record_proxy_targets_head_to_world_diagnostics()


func _record_proxy_targets_head_to_world_diagnostics() -> void:
	_proxy_targets_last_world_from_head_applied = false
	if _proxy_targets_consumer == null:
		return
	if not _proxy_targets_consumer.has_method("get_last_applied_target_info"):
		return
	var info = _proxy_targets_consumer.get_last_applied_target_info()
	if typeof(info) != TYPE_DICTIONARY:
		return
	_proxy_targets_last_world_from_head_applied = bool(info.get("world_from_head_applied", false))
	_proxy_targets_last_local_position = _vector3_from_status_array(info.get("local_position", []), _proxy_targets_last_local_position)
	_proxy_targets_last_world_position = _vector3_from_status_array(info.get("world_position", []), _proxy_targets_last_world_position)


func _proxy_targets_card_target_id() -> String:
	return _card_attachment.attached_target_id(CARD_ANCHOR_NAME)


func _proxy_targets_proxy_count() -> int:
	if _proxy_targets_consumer == null:
		return 0
	if not _proxy_targets_consumer.has_method("get_proxy_targets"):
		return 0
	var targets = _proxy_targets_consumer.get_proxy_targets()
	if typeof(targets) != TYPE_DICTIONARY:
		return 0
	return targets.size()


func _proxy_targets_proxy_ids() -> Array:
	if _proxy_targets_consumer == null:
		return []
	if not _proxy_targets_consumer.has_method("get_proxy_targets"):
		return []
	var targets = _proxy_targets_consumer.get_proxy_targets()
	if typeof(targets) != TYPE_DICTIONARY:
		return []
	var ids := []
	for target_id in targets.keys():
		ids.append(str(target_id))
	ids.sort()
	return ids


func _vector3_from_status_array(value, fallback: Vector3) -> Vector3:
	if typeof(value) != TYPE_ARRAY or value.size() < 3:
		return fallback
	return Vector3(float(value[0]), float(value[1]), float(value[2]))


# Untyped returns: Vector3 when resolvable, null otherwise. StatusHud formats
# null as "n/a" in the label and status files.
func _proxy_targets_card_resolved_position():
	return _card_attachment.last_resolved_position(CARD_ANCHOR_NAME)


func _proxy_targets_card_node_position():
	if _card_anchor == null:
		return null
	return _card_anchor.global_transform.origin


func _update_debug_target_marker(delta: float) -> void:
	if _debug_target_marker == null or not is_instance_valid(_debug_target_marker):
		return
	_debug_target_elapsed_seconds += delta
	_debug_target_marker.position = Vector3(
		DEBUG_TARGET_BASE_POSITION.x + sin(_debug_target_elapsed_seconds * 0.9) * DEBUG_TARGET_RADIUS_M,
		DEBUG_TARGET_BASE_POSITION.y + sin(_debug_target_elapsed_seconds * 1.7) * 0.08,
		DEBUG_TARGET_BASE_POSITION.z + cos(_debug_target_elapsed_seconds * 0.9) * 0.12
	)
	_debug_target_marker.rotation_degrees = Vector3(0.0, _debug_target_elapsed_seconds * 35.0, 0.0)


## Wires the two WSTransport instances (control + proxy_targets). The card
## keeps URL/enable resolution (via _options), packet handling, and error
## formatting; the transports own the peers and the 2.0 s retry loop. The
## url providers make every retry re-resolve through the card, matching the
## old loops byte-for-byte.
func _setup_ws_transports() -> void:
	_control_ws.set_on_packet(_handle_packet)
	_control_ws.set_on_connect_error(_on_control_ws_connect_error)
	_control_ws.set_url_provider(_control_ws_url)
	_proxy_targets_ws.set_on_packet(_on_proxy_targets_ws_packet)
	_proxy_targets_ws.set_subscribe_payload(JSON.stringify({"type": "subscribe", "stream": "proxy_targets"}))
	_proxy_targets_ws.set_on_connect_error(_on_proxy_targets_ws_connect_error)
	_proxy_targets_ws.set_url_provider(_proxy_targets_ws_url)


func _on_control_ws_connect_error(result: int) -> void:
	_last_command = "ws connect err " + str(result)


func _on_proxy_targets_ws_connect_error(result: int) -> void:
	_last_command = "proxy_ws_connect_err_" + str(result)


func _connect_ws() -> void:
	_control_ws.connect_to(_control_ws_url())


func _process(delta: float) -> void:
	_poll_ws(delta)
	_poll_proxy_targets_ws(delta)
	_poll_vst_bbox()
	_advance_vst_target_state(delta)
	_update_debug_target_marker(delta)
	if not _paused and _anchor_mode == "manual":
		_anchor_yaw_deg -= _speed_deg_per_second * delta
		if _anchor_yaw_deg < CARD_END_YAW_DEG:
			_anchor_yaw_deg = CARD_START_YAW_DEG
	if _anchor_mode == "bbox":
		_apply_bbox_anchor()
	if _anchor_mode == "target":
		_update_target_attachments()
	else:
		_apply_3dof_anchor_transform()
	_update_passthrough_overlay_layer()
	_update_status_hud(delta)


func _update_passthrough_overlay_layer() -> void:
	if not _passthrough_overlay_enabled:
		return
	if _passthrough_overlay_layer == null or _camera == null:
		return
	var camera_transform := _camera.global_transform
	var world_position: Vector3 = camera_transform * Vector3(0.0, 0.0, -PASSTHROUGH_OVERLAY_DEPTH_M)
	_passthrough_overlay_layer.global_transform = Transform3D(camera_transform.basis, world_position)


func _passthrough_overlay_layer_alpha_blend() -> bool:
	if _passthrough_overlay_layer == null:
		return false
	return bool(_passthrough_overlay_layer.alpha_blend)


# Untyped return: Vector3 when the layer exists, null otherwise (StatusHud
# formats null as "n/a").
func _passthrough_overlay_layer_position():
	if _passthrough_overlay_layer == null:
		return null
	return _passthrough_overlay_layer.global_transform.origin


func _build_vst_target_proxy() -> void:
	if _vst_target_proxy != null and is_instance_valid(_vst_target_proxy):
		return
	_vst_target_proxy = Node3D.new()
	_vst_target_proxy.name = "VSTTrackedTargetProxy"
	_vst_target_proxy.visible = false
	add_child(_vst_target_proxy)
	register_node3d_target(VST_TRACKED_TARGET_ID, _vst_target_proxy)
	_vst_target_source = TargetSourceScript.VSTTargetSource.new(
		VST_TRACKED_TARGET_ID,
		_vst_target_proxy,
		VST_TARGET_CONFIDENCE_THRESHOLD,
		VST_TARGET_PREDICT_MS,
		VST_TARGET_STALE_MS,
		VST_TARGET_LOST_MS,
		VST_TARGET_SMOOTHING_ALPHA
	)
	_vst_target_source.set_on_target_updated(_on_vst_target_updated)
	_vst_target_source.set_on_target_lost(_on_vst_target_lost)


func update_vst_target(target_id: String, transform: Transform3D, confidence: float, timestamp_ms: float) -> bool:
	if _vst_target_source == null:
		_build_vst_target_proxy()
	if _vst_target_source == null:
		return false
	var ok := bool(_vst_target_source.update_target(target_id, transform, confidence, timestamp_ms))
	if not ok:
		return false
	var attached := attach_to_target(CARD_ANCHOR_NAME, VST_TRACKED_TARGET_ID, VST_TARGET_OFFSET_RULE)
	if attached:
		_last_command = "vst_target"
	return attached


func _advance_vst_target_state(_delta: float) -> void:
	if _vst_target_source == null:
		return
	_vst_target_source.advance(float(Time.get_ticks_msec()))
	if _vst_target_source.target_state() == TargetSourceScript.TRACKABLE_STATE_LOST:
		return
	if _anchor_mode == "target" and _card_attachment.has_attachment(CARD_ANCHOR_NAME):
		_update_target_attachments()


func _on_vst_target_updated(_target_id: String, _transform: Transform3D) -> void:
	if _vst_target_proxy != null:
		_vst_target_proxy.visible = true


func _on_vst_target_lost(_target_id: String) -> void:
	if _vst_target_proxy != null:
		_vst_target_proxy.visible = false
	var attachment = _card_attachment.get_attachment(CARD_ANCHOR_NAME)
	if attachment != null and str(attachment.get("target_id", "")) == VST_TRACKED_TARGET_ID:
		_card_attachment.apply_fallback(attachment, _card_anchor, CARD_ANCHOR_NAME)


func register_node3d_target(target_id: String, node_or_path) -> bool:
	return bool(_target_registry.register(target_id, TargetRegistryScript.Node3DTargetAdapter.new(self, node_or_path)))


func unregister_target(target_id: String) -> void:
	_target_registry.unregister(target_id)


## Wires the CardAttachment subsystem: target lookup routes back into
## _target_registry (so attach_to_target resolves targets exactly as before),
## the apply counter stays card-side, and the detach fallback calls back into
## detach_card so the anchor-mode flip stays where the state lives (ADR-4).
func _setup_card_attachment() -> void:
	_card_attachment.set_resolver(_target_registry.resolve)
	_card_attachment.set_on_applied(_on_card_attachment_applied)
	_card_attachment.set_on_detach_card(detach_card)


func _on_card_attachment_applied() -> void:
	_proxy_targets_card_apply_count += 1


func attach_to_target(card_id: String, target_id: String, offset_rule = {}) -> bool:
	if not _card_attachment.attach(card_id, target_id, offset_rule):
		return false
	_anchor_mode = "target"
	_last_command = "attach_target:" + target_id
	_update_target_attachments()
	return true


func detach_card(card_id: String) -> void:
	_card_attachment.detach(card_id)
	if _card_attachment.is_empty() and _anchor_mode == "target":
		_anchor_mode = "manual"
		_apply_3dof_anchor_transform()


func _update_target_attachments() -> void:
	if _card_anchor == null:
		return
	if not _card_attachment.update_attachments(_card_anchor, CARD_ANCHOR_NAME):
		return
	if _face_camera_enabled:
		_orient_card_for_3dof_reading()
	_update_vst_bbox_frame()


func _poll_ws(delta: float) -> void:
	_control_ws.poll(delta)


func _handle_packet(payload: String) -> void:
	var parsed = JSON.parse_string(payload)
	if typeof(parsed) != TYPE_DICTIONARY:
		return
	if parsed.get("type", "") == "bbox":
		_apply_bbox_payload(parsed)
		return
	if parsed.get("type", "") != "control":
		return
	_apply_command(str(parsed.get("command", "")))


func _apply_command(command: String) -> void:
	_last_command = command
	match command:
		"yaw_left", "left", "move_left", "a":
			_anchor_mode = "manual"
			_anchor_yaw_deg -= CARD_YAW_STEP_DEG
		"yaw_right", "right", "move_right", "d":
			_anchor_mode = "manual"
			_anchor_yaw_deg += CARD_YAW_STEP_DEG
		"pitch_up", "up", "move_up", "w":
			_anchor_mode = "manual"
			_anchor_pitch_deg += CARD_PITCH_STEP_DEG
		"pitch_down", "down", "move_down", "s":
			_anchor_mode = "manual"
			_anchor_pitch_deg -= CARD_PITCH_STEP_DEG
		"depth_in", "closer":
			_anchor_mode = "manual"
			_anchor_depth_m = clampf(_anchor_depth_m - CARD_DEPTH_STEP_M, MIN_DEPTH_M, MAX_DEPTH_M)
		"depth_out", "farther":
			_anchor_mode = "manual"
			_anchor_depth_m = clampf(_anchor_depth_m + CARD_DEPTH_STEP_M, MIN_DEPTH_M, MAX_DEPTH_M)
		"toggle_bbox_mode":
			_anchor_mode = "manual" if _anchor_mode == "bbox" else "bbox"
			if _anchor_mode == "bbox":
				_apply_bbox_anchor()
		"bbox_left":
			_anchor_mode = "bbox"
			_bbox_center_px.x = clampf(_bbox_center_px.x - BBOX_CENTER_STEP_PX, 0.0, _bbox_image_size.x)
			_apply_bbox_anchor()
		"bbox_right":
			_anchor_mode = "bbox"
			_bbox_center_px.x = clampf(_bbox_center_px.x + BBOX_CENTER_STEP_PX, 0.0, _bbox_image_size.x)
			_apply_bbox_anchor()
		"bbox_up":
			_anchor_mode = "bbox"
			_bbox_center_px.y = clampf(_bbox_center_px.y - BBOX_CENTER_STEP_PX, 0.0, _bbox_image_size.y)
			_apply_bbox_anchor()
		"bbox_down":
			_anchor_mode = "bbox"
			_bbox_center_px.y = clampf(_bbox_center_px.y + BBOX_CENTER_STEP_PX, 0.0, _bbox_image_size.y)
			_apply_bbox_anchor()
		"bbox_depth_in":
			_anchor_mode = "bbox"
			_bbox_depth_m = clampf(_bbox_depth_m - BBOX_DEPTH_STEP_M, MIN_DEPTH_M, MAX_DEPTH_M)
			_apply_bbox_anchor()
		"bbox_depth_out":
			_anchor_mode = "bbox"
			_bbox_depth_m = clampf(_bbox_depth_m + BBOX_DEPTH_STEP_M, MIN_DEPTH_M, MAX_DEPTH_M)
			_apply_bbox_anchor()
		"speed_up", "plus":
			_speed_deg_per_second = clampf(_speed_deg_per_second + CARD_SPEED_STEP_DEG_PER_SECOND, MIN_SPEED_DEG_PER_SECOND, MAX_SPEED_DEG_PER_SECOND)
		"speed_down", "minus":
			_speed_deg_per_second = clampf(_speed_deg_per_second - CARD_SPEED_STEP_DEG_PER_SECOND, MIN_SPEED_DEG_PER_SECOND, MAX_SPEED_DEG_PER_SECOND)
		"pause", "toggle_pause", "space":
			_paused = not _paused
		"debug_target_free":
			if _debug_target_marker != null and is_instance_valid(_debug_target_marker):
				_debug_target_marker.queue_free()
			_debug_target_marker = null
		"debug_target_reset":
			_build_debug_target_marker()
		"reset", "r":
			_anchor_yaw_deg = CARD_START_YAW_DEG
			_anchor_pitch_deg = CARD_START_PITCH_DEG
			_anchor_depth_m = CARD_START_DEPTH_M
			_anchor_mode = "manual"
			_bbox_center_px = BBOX_START_CENTER_PX
			_bbox_size_px = BBOX_START_SIZE_PX
			_bbox_image_size = BBOX_IMAGE_SIZE
			_bbox_depth_m = CARD_START_DEPTH_M
			_bbox_angular_size_deg = Vector2.ZERO
			_set_vst_bbox_frame_visible(false)
			_paused = false
	_apply_3dof_anchor_transform()


func _apply_bbox_payload(parsed: Dictionary) -> void:
	var bbox = parsed.get("bbox", {})
	var image = parsed.get("image", {})
	if typeof(bbox) != TYPE_DICTIONARY or typeof(image) != TYPE_DICTIONARY:
		return
	_bbox_center_px = Vector2(float(bbox.get("cx", _bbox_center_px.x)), float(bbox.get("cy", _bbox_center_px.y)))
	_bbox_size_px = Vector2(float(bbox.get("w", _bbox_size_px.x)), float(bbox.get("h", _bbox_size_px.y)))
	_bbox_image_size = Vector2(float(image.get("w", _bbox_image_size.x)), float(image.get("h", _bbox_image_size.y)))
	_bbox_depth_m = clampf(float(parsed.get("depth_m", _bbox_depth_m)), MIN_DEPTH_M, MAX_DEPTH_M)
	_anchor_mode = "bbox"
	_last_command = "bbox_payload"
	_apply_bbox_anchor()


func _apply_bbox_anchor() -> void:
	var anchor := _anchor_from_bbox(_bbox_center_px, _bbox_size_px, _bbox_image_size, _bbox_depth_m)
	_anchor_yaw_deg = anchor["yaw_deg"]
	_anchor_pitch_deg = anchor["pitch_deg"]
	_anchor_depth_m = anchor["depth_m"]
	_bbox_angular_size_deg = anchor["angular_size_deg"]


func _anchor_from_bbox(center_px: Vector2, size_px: Vector2, image_size: Vector2, depth_m: float) -> Dictionary:
	_sync_vst_capture_probe_matrix()
	return _vst_capture.anchor_from_bbox(center_px, size_px, image_size, depth_m)


func _target_position_from_bbox_anchor(anchor: Dictionary) -> Vector3:
	return _vst_capture.target_position_from_bbox_anchor(anchor)


func _convert_vst_camera_point_to_head_convention(point: Vector3) -> Vector3:
	return _vst_capture.convert_vst_camera_point_to_head_convention(point)


func _transform_right_vst_point_to_head(point: Vector3) -> Vector3:
	_sync_vst_capture_probe_matrix()
	return _vst_capture.transform_right_vst_point_to_head(point)


func _sync_vst_capture_probe_matrix() -> void:
	if _vst_uses_eye_to_head_anchor or _vst_right_eye_to_head_matrix.size() >= 16:
		_vst_capture.store_right_eye_to_head_matrix({
			"ret": 0,
			"right": _vst_right_eye_to_head_matrix,
		})
	else:
		_vst_capture.store_right_eye_to_head_matrix({"ret": -1})


func _anchor_position_from_yaw_pitch_depth() -> Vector3:
	var yaw := deg_to_rad(_anchor_yaw_deg)
	var pitch := deg_to_rad(_anchor_pitch_deg)
	var horizontal_depth := _anchor_depth_m * cos(pitch)
	return Vector3(
		horizontal_depth * sin(yaw),
		_anchor_depth_m * sin(pitch),
		-horizontal_depth * cos(yaw)
	)


func _apply_3dof_anchor_transform() -> void:
	if _card_anchor == null:
		return
	_card_anchor.position = _anchor_position_from_yaw_pitch_depth()
	if _face_camera_enabled:
		_orient_card_for_3dof_reading()
	_update_vst_bbox_frame()


func _orient_card_for_3dof_reading() -> void:
	if _card_anchor == null:
		return
	_orient_node_for_3dof_reading(_card_anchor)


func _orient_node_for_3dof_reading(node: Node3D) -> void:
	if node == null:
		return
	var camera_position := Vector3.ZERO
	if _camera != null:
		camera_position = _camera.global_transform.origin
	var world_position := node.global_transform.origin
	var away_from_camera := world_position + camera_position.direction_to(world_position)
	node.look_at(away_from_camera, Vector3.UP)


func _update_vst_bbox_frame() -> void:
	if _vst_bbox_frame_anchor == null or _vst_bbox_frame_parts.size() != 4:
		return
	if _bbox_angular_size_deg.x <= 0.0 or _bbox_angular_size_deg.y <= 0.0:
		_set_vst_bbox_frame_visible(false)
		return
	_set_vst_bbox_frame_visible(true)
	_vst_bbox_frame_anchor.position = _anchor_position_from_yaw_pitch_depth()
	if _face_camera_enabled:
		_orient_node_for_3dof_reading(_vst_bbox_frame_anchor)

	var width_m := maxf(2.0 * _anchor_depth_m * tan(deg_to_rad(_bbox_angular_size_deg.x) * 0.5), VST_BBOX_FRAME_LINE_M * 3.0)
	var height_m := maxf(2.0 * _anchor_depth_m * tan(deg_to_rad(_bbox_angular_size_deg.y) * 0.5), VST_BBOX_FRAME_LINE_M * 3.0)
	_configure_vst_bbox_frame_part(_vst_bbox_frame_parts[0], Vector2(width_m, VST_BBOX_FRAME_LINE_M), Vector3(0.0, height_m * 0.5, VST_BBOX_FRAME_Z_OFFSET_M))
	_configure_vst_bbox_frame_part(_vst_bbox_frame_parts[1], Vector2(width_m, VST_BBOX_FRAME_LINE_M), Vector3(0.0, -height_m * 0.5, VST_BBOX_FRAME_Z_OFFSET_M))
	_configure_vst_bbox_frame_part(_vst_bbox_frame_parts[2], Vector2(VST_BBOX_FRAME_LINE_M, height_m), Vector3(-width_m * 0.5, 0.0, VST_BBOX_FRAME_Z_OFFSET_M))
	_configure_vst_bbox_frame_part(_vst_bbox_frame_parts[3], Vector2(VST_BBOX_FRAME_LINE_M, height_m), Vector3(width_m * 0.5, 0.0, VST_BBOX_FRAME_Z_OFFSET_M))


func _configure_vst_bbox_frame_part(part: MeshInstance3D, size: Vector2, position: Vector3) -> void:
	var mesh := part.mesh as QuadMesh
	if mesh != null:
		mesh.size = size
	part.position = position


func _set_vst_bbox_frame_visible(visible: bool) -> void:
	if _vst_bbox_frame_anchor != null:
		_vst_bbox_frame_anchor.visible = visible


func _update_vst_raw_bbox_overlay(boxes: PackedFloat32Array) -> void:
	if _vst_raw_bbox_parts.size() != 4 or _vst_right_image_size.x <= 0.0 or _vst_right_image_size.y <= 0.0:
		return
	if boxes.size() < 5:
		_set_vst_raw_bbox_visible(false)
		return
	var x := clampf(float(boxes[0]), 0.0, 1.0)
	var y := clampf(float(boxes[1]), 0.0, 1.0)
	var w := clampf(float(boxes[2]), 0.02, 1.0)
	var h := clampf(float(boxes[3]), 0.02, 1.0)
	var overlay_size := _vst_right_image_size * VST_RAW_DEBUG_PIXEL_SIZE_M
	var center := Vector3((x + w * 0.5 - 0.5) * overlay_size.x, (0.5 - y - h * 0.5) * overlay_size.y, VST_RAW_DEBUG_FRAME_Z_OFFSET_M)
	var width_m := w * overlay_size.x
	var height_m := h * overlay_size.y
	_set_vst_raw_bbox_visible(true)
	_configure_vst_bbox_frame_part(_vst_raw_bbox_parts[0], Vector2(width_m, VST_BBOX_FRAME_LINE_M), center + Vector3(0.0, height_m * 0.5, 0.0))
	_configure_vst_bbox_frame_part(_vst_raw_bbox_parts[1], Vector2(width_m, VST_BBOX_FRAME_LINE_M), center + Vector3(0.0, -height_m * 0.5, 0.0))
	_configure_vst_bbox_frame_part(_vst_raw_bbox_parts[2], Vector2(VST_BBOX_FRAME_LINE_M, height_m), center + Vector3(-width_m * 0.5, 0.0, 0.0))
	_configure_vst_bbox_frame_part(_vst_raw_bbox_parts[3], Vector2(VST_BBOX_FRAME_LINE_M, height_m), center + Vector3(width_m * 0.5, 0.0, 0.0))


func _set_vst_raw_bbox_visible(visible: bool) -> void:
	for part in _vst_raw_bbox_parts:
		part.visible = visible


func _corner_world_points() -> Dictionary:
	var half := CARD_SIZE_M * 0.5
	var transform := _card_mesh.global_transform
	return {
		"TL": transform * Vector3(-half.x, half.y, 0.0),
		"TR": transform * Vector3(half.x, half.y, 0.0),
		"BL": transform * Vector3(-half.x, -half.y, 0.0),
		"BR": transform * Vector3(half.x, -half.y, 0.0),
	}


func _update_status_hud(delta: float) -> void:
	if _status_hud == null:
		return
	var snapshot := _build_status_snapshot()
	if _card_anchor != null:
		_status_hud.update_status_label(snapshot)
	_status_hud.write_status_files(snapshot, delta)


## Per-frame status snapshot consumed by StatusHud (label rendering + the
## user:// status file writers). This script resolves every value; StatusHud
## only formats and writes.
func _build_status_snapshot() -> Dictionary:
	return {
		"ws_connected": _control_ws.ws_connected(),
		"last_command": _last_command,
		"anchor_mode": _anchor_mode,
		"camera_position": _camera.global_position if _camera != null else null,
		"camera_rotation_degrees": _camera.global_rotation_degrees if _camera != null else null,
		"xr_origin_position": _xr_origin.global_position if _xr_origin != null else null,
		"bbox_center_px": _bbox_center_px,
		"bbox_size_px": _bbox_size_px,
		"bbox_depth_m": _bbox_depth_m,
		"anchor_yaw_deg": _anchor_yaw_deg,
		"anchor_pitch_deg": _anchor_pitch_deg,
		"anchor_depth_m": _anchor_depth_m,
		"bbox_angular_size_deg": _bbox_angular_size_deg,
		"card_rotation_degrees": _card_anchor.rotation_degrees if _card_anchor != null else Vector3.ZERO,
		"speed_deg_per_second": _speed_deg_per_second,
		"paused": _paused,
		"corners": _corner_world_points() if _card_mesh != null else {},
		"viewport_use_xr": get_viewport().use_xr,
		"viewport_transparent_bg": get_viewport().transparent_bg,
		"xr": _build_xr_status_snapshot(),
		"vst": _build_vst_status_snapshot(),
		"proxy_targets": _build_proxy_targets_status_snapshot(),
		"passthrough_overlay": _build_passthrough_overlay_status_snapshot(),
	}


func _build_xr_status_snapshot() -> Dictionary:
	return {
		"interface_found": _xr_interface_found,
		"initialize_ok": _xr_initialize_ok,
		"active": _xr_active,
		"init_error": _xr_init_error,
	}


func _build_vst_status_snapshot() -> Dictionary:
	var target_state := "lost"
	if _vst_target_source != null:
		target_state = _vst_target_source.target_state()
	var snapshot: Dictionary = _vst_capture.status_snapshot()
	snapshot["target_state"] = target_state
	return snapshot


func _build_proxy_targets_status_snapshot() -> Dictionary:
	return {
		"ws_connected": _proxy_targets_ws.ws_connected(),
		"ws_subscribed": _proxy_targets_ws.ws_subscribed(),
		"ws_url": _proxy_targets_ws_url(),
		"attachments": _card_attachment.size(),
		"card_target_id": _proxy_targets_card_target_id(),
		"proxy_target_count": _proxy_targets_proxy_count(),
		"proxy_target_ids": _proxy_targets_proxy_ids(),
		"last_position": _proxy_targets_last_position,
		"card_resolved_position": _proxy_targets_card_resolved_position(),
		"card_node_position": _proxy_targets_card_node_position(),
		"card_apply_count": _proxy_targets_card_apply_count,
		"packets": _proxy_targets_ws.packets_seen(),
		"parsed": _proxy_targets_parsed_messages,
		"live": _proxy_targets_live_messages,
		"sequence": _proxy_targets_last_sequence,
		"packet_bytes": _proxy_targets_ws.last_packet_bytes(),
		"packet_preview": _proxy_targets_last_packet_preview,
		"message_type": _proxy_targets_last_message_type,
		"source_coordinate": _proxy_targets_last_source_coordinate,
		"world_from_head_applied": _proxy_targets_last_world_from_head_applied,
		"local_position": _proxy_targets_last_local_position,
		"world_position": _proxy_targets_last_world_position,
		"error": _proxy_targets_last_error,
	}


func _build_passthrough_overlay_status_snapshot() -> Dictionary:
	return {
		"enabled": _passthrough_overlay_enabled,
		"requested_blend_mode": _passthrough_overlay_requested_blend_mode,
		"blend_request_ok": _passthrough_overlay_blend_ok,
		"layer_created": _passthrough_overlay_layer != null,
		"layer_visible": _passthrough_overlay_layer.visible if _passthrough_overlay_layer != null else false,
		"layer_alpha_blend": _passthrough_overlay_layer_alpha_blend(),
		"layer_position": _passthrough_overlay_layer_position(),
	}


func _exit_tree() -> void:
	_vst_capture.shutdown()


func _setup_vst_capture() -> void:
	_vst_capture.set_raw_image_callback(_on_vst_raw_right_image)
	_vst_capture.set_boxes_callback(_on_vst_tracker_boxes)
	_vst_capture.set_anchor_callback(_on_vst_tracker_anchor)
	_vst_capture.setup_capture(_xr_active)


func _poll_vst_bbox() -> void:
	_vst_capture.set_depth_m(_bbox_depth_m)
	_vst_capture.poll()


func _on_vst_raw_right_image(right_img: Image, image_size: Vector2, frames: int) -> void:
	_vst_right_image_size = image_size
	_vst_right_frames = frames
	if _vst_raw_right_sprite != null:
		_vst_raw_right_sprite.texture = ImageTexture.create_from_image(right_img)


func _on_vst_tracker_boxes(boxes: PackedFloat32Array, image_size: Vector2) -> void:
	_vst_right_image_size = image_size
	if boxes.size() >= 5:
		_update_vst_raw_bbox_overlay(boxes)
	else:
		_set_vst_raw_bbox_visible(false)
		_set_vst_bbox_frame_visible(false)


func _on_vst_tracker_anchor(anchor: Dictionary) -> void:
	_bbox_center_px = anchor.get("center_px", _bbox_center_px)
	_bbox_size_px = anchor.get("size_px", _bbox_size_px)
	_bbox_image_size = anchor.get("image_size", _bbox_image_size)
	_bbox_depth_m = float(anchor.get("depth_m", _bbox_depth_m))
	_bbox_angular_size_deg = anchor.get("angular_size_deg", _bbox_angular_size_deg)
	var target_transform: Transform3D = anchor.get("target_transform", Transform3D.IDENTITY)
	var confidence := float(anchor.get("confidence", 0.0))
	var updated := update_vst_target(VST_TRACKED_TARGET_ID, target_transform, confidence, float(Time.get_ticks_msec()))
	_update_vst_bbox_frame()
	if updated and int(anchor.get("anchor_updates", 0)) <= 5:
		print("VST target: center=%.1f %.1f size=%.1f %.1f image=%.0f %.0f pos=%.2f %.2f %.2f conf=%.2f" % [
			_bbox_center_px.x,
			_bbox_center_px.y,
			_bbox_size_px.x,
			_bbox_size_px.y,
			_bbox_image_size.x,
			_bbox_image_size.y,
			target_transform.origin.x,
			target_transform.origin.y,
			target_transform.origin.z,
			confidence,
		])


func _make_panel_style() -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.06, 0.075, 0.09, 0.92)
	style.border_color = Color(0.18, 0.78, 0.86, 0.98)
	style.set_border_width_all(4)
	style.set_corner_radius_all(4)
	style.shadow_color = Color(0.0, 0.0, 0.0, 0.45)
	style.shadow_size = 24
	return style
