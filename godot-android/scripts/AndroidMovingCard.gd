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
const STATUS_HUD_VISIBLE := true
const PASSTHROUGH_OVERLAY_ENV := "SMARTXR_USE_PASSTHROUGH_OVERLAY"
const PASSTHROUGH_OVERLAY_VIEWPORT_SIZE := Vector2i(512, 256)
const PASSTHROUGH_OVERLAY_QUAD_SIZE_M := Vector2(0.42, 0.20)
const PASSTHROUGH_OVERLAY_DEPTH_M := 1.5
const CardAttachmentScript := preload("res://scripts/card_attachment.gd")
const CardStateScript := preload("res://scripts/card_state.gd")
const CardViewScript := preload("res://scripts/card_view.gd")
const CardReceiverScript := preload("res://scripts/card_receiver.gd")
const CommandDispatcherScript := preload("res://scripts/command_dispatcher.gd")
const ProxyTargetsConsumerScript := preload("res://scripts/proxy_targets_consumer.gd")
const ProxyTargetsCardAdapterScript := preload("res://scripts/proxy_targets_card_adapter.gd")
const ProxyTargetsStatusFragmentScript := preload("res://scripts/proxy_targets_status_fragment.gd")
const PassthroughOverlayPresenterScript := preload("res://scripts/passthrough_overlay_presenter.gd")
const SmartXROptionsScript := preload("res://scripts/smartxr_options.gd")
const StatusHudScript := preload("res://scripts/status_hud.gd")
const StatusSnapshotComposerScript := preload("res://scripts/status_snapshot_composer.gd")
const TargetRegistryScript := preload("res://scripts/target_registry.gd")
const TargetSourceScript := preload("res://scripts/target_source.gd")
const ValidationSceneBuilderScript := preload("res://scripts/validation_scene_builder.gd")
const VSTCaptureScript := preload("res://scripts/vst_capture.gd")
const VSTDebugUIScript := preload("res://scripts/vst_debug_ui.gd")
const WSTransportScript := preload("res://scripts/ws_transport.gd")
const XRBootstrapScript := preload("res://scripts/xr_bootstrap.gd")

# Centralized runtime configuration (env var -> user://smartxr_options.json
# -> script const default). The consts below stay as the defaults; deployment
# overrides go through SmartXROptions instead of source edits.
var _options = SmartXROptionsScript.load_options()
var _card_state = CardStateScript.new({
	"speed_deg_per_second": CARD_DEFAULT_SPEED_DEG_PER_SECOND,
	"anchor_yaw_deg": CARD_START_YAW_DEG,
	"anchor_pitch_deg": CARD_START_PITCH_DEG,
	"anchor_depth_m": CARD_START_DEPTH_M,
	"bbox_center_px": BBOX_START_CENTER_PX,
	"bbox_size_px": BBOX_START_SIZE_PX,
	"bbox_image_size": BBOX_IMAGE_SIZE,
	"bbox_depth_m": CARD_START_DEPTH_M,
	"min_depth_m": MIN_DEPTH_M,
	"max_depth_m": MAX_DEPTH_M,
	"card_start_yaw_deg": CARD_START_YAW_DEG,
	"card_end_yaw_deg": CARD_END_YAW_DEG,
})

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
var _card_view = CardViewScript.new({
	"viewport_size": CARD_VIEWPORT_SIZE,
	"card_size_m": CARD_SIZE_M,
	"xr_probe_size_m": XR_PROBE_SIZE_M,
})
var _status_hud: Node = null
var _status_snapshot_composer = StatusSnapshotComposerScript.new()
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
var _command_dispatcher_config := CommandDispatcherScript.default_config()
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
var _validation_scene_builder = ValidationSceneBuilderScript.new()
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
var _card_receiver = CardReceiverScript.new()
var _proxy_targets_status_fragment = ProxyTargetsStatusFragmentScript.new()
var _proxy_targets_card_apply_count := 0
var _passthrough_overlay_enabled := false
var _passthrough_overlay_blend_ok := false
var _passthrough_overlay_requested_blend_mode := "alpha_blend"
var _passthrough_overlay_presenter = PassthroughOverlayPresenterScript.new({
	"viewport_size": PASSTHROUGH_OVERLAY_VIEWPORT_SIZE,
	"quad_size_m": PASSTHROUGH_OVERLAY_QUAD_SIZE_M,
	"depth_m": PASSTHROUGH_OVERLAY_DEPTH_M,
})

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
# VSTDebugUI subsystem (scripts/vst_debug_ui.gd): owns the VST debug scene
# nodes and visual updates. AndroidMovingCard keeps capture callbacks, target
# updates, and status snapshots.
var _vst_debug_ui = VSTDebugUIScript.new()


func _ready() -> void:
	_passthrough_overlay_enabled = _use_passthrough_overlay()
	_setup_card_attachment()
	_setup_xr_bootstrap()
	_try_init_xr()
	_setup_camera()
	_build_passthrough_overlay_layer()
	_build_vst_debug_ui()
	_setup_light()
	_build_card_anchor()
	_build_xr_render_probe()
	_build_status_hud()
	_build_vst_target_proxy()
	_build_debug_target_marker()
	_build_proxy_targets_validation()
	_setup_ws_transports()
	_setup_card_receiver()
	_connect_ws()
	_card_receiver.connect_if_enabled()
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
	return _passthrough_overlay_presenter.overlay_enabled_from_env(PASSTHROUGH_OVERLAY_ENV)


func _build_passthrough_overlay_layer() -> void:
	_passthrough_overlay_presenter.build_layer(self, _xr_active, _passthrough_overlay_enabled)
	_update_passthrough_overlay_layer()


func _make_passthrough_overlay_ui() -> Control:
	return Control.new()


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
	_card_view.build(self, CARD_ANCHOR_NAME)
	_card_viewport = _card_view.viewport()
	_card_anchor = _card_view.anchor()
	_card_mesh = _card_view.card_mesh()
	_apply_3dof_anchor_transform()


func _build_xr_render_probe() -> void:
	_xr_probe_mesh = _card_view.build_xr_render_probe()


func _build_vst_debug_ui() -> void:
	_vst_debug_ui.build_raw_debug_panel(_camera)
	_vst_debug_ui.build_world_bbox_frame(self)


func _build_status_hud() -> void:
	_status_hud = StatusHudScript.new()
	_status_hud.name = "StatusHud"
	add_child(_status_hud)
	var status_label: Label3D = _status_hud.build_status_label(_card_anchor)
	status_label.visible = _status_hud_visible()
	_status_hud.update_status_label(_build_status_snapshot(), 0.0, true)


func _build_debug_target_marker() -> void:
	if not DEBUG_NODE3D_TARGET_ENABLED:
		return
	var result: Dictionary = _validation_scene_builder.build_debug_target_marker(
		self,
		_debug_target_marker,
		{"target_id": DEBUG_TARGET_ID, "card_id": CARD_ANCHOR_NAME, "marker_name": "MovingTargetMarker", "size_m": DEBUG_TARGET_SIZE_M, "base_position": DEBUG_TARGET_BASE_POSITION, "radius_m": DEBUG_TARGET_RADIUS_M, "offset_rule": {"mode": "right_top", "offset_space": "world", "right_m": 0.35, "up_m": 0.25, "fallback": "hold_last_pose"}},
		Callable(self, "register_node3d_target"),
		Callable(self, "attach_to_target")
	)
	_debug_target_marker = result.get("marker", null)
	_debug_target_elapsed_seconds = float(result.get("elapsed_seconds", 0.0))
	if _debug_target_marker != null:
		print("Debug Node3D target attached: %s marker=%s" % [DEBUG_TARGET_ID, _debug_target_marker.name])


func _build_proxy_targets_validation() -> void:
	if not PROXY_TARGETS_VALIDATION_ENABLED:
		return
	var consumer_factory := func():
		return ProxyTargetsConsumerScript.new()
	var adapter_factory := func():
		return ProxyTargetsCardAdapterScript.new()
	var target_source_factory := func(adapter):
		return TargetSourceScript.ProxyTargetsTargetSource.new(adapter)
	var result: Dictionary = _validation_scene_builder.build_proxy_targets_validation(
		self,
		self,
		_camera,
		consumer_factory,
		adapter_factory,
		target_source_factory,
		PROXY_TARGETS_SAMPLE_RES
	)
	_proxy_targets_consumer = result.get("consumer", null)
	_proxy_targets_card_adapter = result.get("card_adapter", null)
	_proxy_targets_target_source = result.get("target_source", null)
	var sample_command := str(result.get("sample_command", ""))
	if not sample_command.is_empty():
		_last_command = sample_command


func _proxy_targets_ws_enabled() -> bool:
	return _options.proxy_targets_ws_enabled(PROXY_TARGETS_WS_ENABLED)


func _proxy_targets_ws_url() -> String:
	return _options.proxy_targets_ws_url(PROXY_TARGETS_WS_URL)


func _control_ws_url() -> String:
	return _options.control_ws_url(WS_URL)


func _status_hud_visible() -> bool:
	return _options.status_hud_visible(STATUS_HUD_VISIBLE)


func _proxy_targets_head_to_world_info() -> Dictionary:
	if _proxy_targets_consumer == null:
		return {}
	if not _proxy_targets_consumer.has_method("get_last_applied_target_info"):
		return {}
	var info = _proxy_targets_consumer.get_last_applied_target_info()
	if typeof(info) != TYPE_DICTIONARY:
		return {}
	return info


func _proxy_targets_card_target_id() -> String:
	return _card_attachment.attached_target_id(CARD_ANCHOR_NAME)


func _proxy_targets_proxy_count() -> int:
	return ProxyTargetsStatusFragmentScript.proxy_target_count(_proxy_targets_proxy_dictionary())


func _proxy_targets_proxy_ids() -> Array:
	return ProxyTargetsStatusFragmentScript.proxy_target_ids(_proxy_targets_proxy_dictionary())


func _proxy_targets_proxy_dictionary():
	if _proxy_targets_consumer == null:
		return {}
	if not _proxy_targets_consumer.has_method("get_proxy_targets"):
		return {}
	return _proxy_targets_consumer.get_proxy_targets()


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
	_debug_target_elapsed_seconds = _validation_scene_builder.update_debug_target_marker(
		_debug_target_marker,
		_debug_target_elapsed_seconds,
		delta,
		{"base_position": DEBUG_TARGET_BASE_POSITION, "radius_m": DEBUG_TARGET_RADIUS_M}
	)


## Wires the two WSTransport instances (control + proxy_targets). The card
## keeps URL/enable resolution (via _options), packet handling, and error
## formatting; the transports own the peers and the 2.0 s retry loop. The
## url providers make every retry re-resolve through the card, matching the
## old loops byte-for-byte.
func _setup_ws_transports() -> void:
	_control_ws.set_on_packet(_handle_packet)
	_control_ws.set_on_connect_error(_on_control_ws_connect_error)
	_control_ws.set_url_provider(_control_ws_url)


func _setup_card_receiver() -> void:
	_card_receiver.setup({
		"ws": _proxy_targets_ws,
		"status_fragment": _proxy_targets_status_fragment,
		"target_source": _proxy_targets_target_source,
		"ws_url_provider": _proxy_targets_ws_url,
		"ws_enabled_provider": _proxy_targets_ws_enabled,
		"last_command_callback": _set_last_command,
		"head_info_provider": _proxy_targets_head_to_world_info,
	})


func _on_control_ws_connect_error(result: int) -> void:
	_set_last_command("ws connect err " + str(result))


func _set_last_command(command: String) -> void:
	_last_command = command
	_sync_card_state_from_fields()


func _connect_ws() -> void:
	_control_ws.connect_to(_control_ws_url())


func _process(delta: float) -> void:
	_poll_ws(delta)
	_card_receiver.poll(delta)
	_poll_vst_bbox()
	_advance_vst_target_state(delta)
	_update_debug_target_marker(delta)
	_sync_card_state_from_fields()
	_card_state.advance_manual(delta)
	_sync_card_fields_from_state()
	if _anchor_mode == "bbox":
		_apply_bbox_anchor()
	if _anchor_mode == "target":
		_update_target_attachments()
	else:
		_apply_3dof_anchor_transform()
	_update_passthrough_overlay_layer()
	_update_status_hud(delta)


func _update_passthrough_overlay_layer() -> void:
	_passthrough_overlay_presenter.update_layer(_camera)


func _passthrough_overlay_layer_alpha_blend() -> bool:
	return _passthrough_overlay_presenter.layer_alpha_blend()


# Untyped return: Vector3 when the layer exists, null otherwise (StatusHud
# formats null as "n/a").
func _passthrough_overlay_layer_position():
	return _passthrough_overlay_presenter.layer_position()


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
	_sync_card_state_from_fields()
	_card_state.mark_attached(target_id)
	_sync_card_fields_from_state()
	_update_target_attachments()
	return true


func detach_card(card_id: String) -> void:
	_card_attachment.detach(card_id)
	_sync_card_state_from_fields()
	_card_state.mark_detached(_card_attachment.is_empty())
	_sync_card_fields_from_state()
	if _anchor_mode == "manual":
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
	var next_state: Dictionary = CommandDispatcherScript.apply_command(
		_command_state(),
		command,
		_command_dispatcher_config
	)
	_apply_command_state(next_state)
	_run_command_effects(Array(next_state.get("effects", [])))


func _command_state() -> Dictionary:
	_sync_card_state_from_fields()
	return _card_state.command_state()


func _apply_command_state(next_state: Dictionary) -> void:
	_card_state.apply_command_state(next_state)
	_sync_card_fields_from_state()


func _sync_card_state_from_fields() -> void:
	_card_state.apply_command_state({
		"speed_deg_per_second": _speed_deg_per_second,
		"anchor_yaw_deg": _anchor_yaw_deg,
		"anchor_pitch_deg": _anchor_pitch_deg,
		"anchor_depth_m": _anchor_depth_m,
		"anchor_mode": _anchor_mode,
		"bbox_center_px": _bbox_center_px,
		"bbox_size_px": _bbox_size_px,
		"bbox_image_size": _bbox_image_size,
		"bbox_depth_m": _bbox_depth_m,
		"bbox_angular_size_deg": _bbox_angular_size_deg,
		"paused": _paused,
		"last_command": _last_command,
	})


func _sync_card_fields_from_state() -> void:
	var state := _card_state.status_values()
	_speed_deg_per_second = float(state.get("speed_deg_per_second", _speed_deg_per_second))
	_anchor_yaw_deg = float(state.get("anchor_yaw_deg", _anchor_yaw_deg))
	_anchor_pitch_deg = float(state.get("anchor_pitch_deg", _anchor_pitch_deg))
	_anchor_depth_m = float(state.get("anchor_depth_m", _anchor_depth_m))
	_anchor_mode = str(state.get("anchor_mode", _anchor_mode))
	_bbox_center_px = Vector2(state.get("bbox_center_px", _bbox_center_px))
	_bbox_size_px = Vector2(state.get("bbox_size_px", _bbox_size_px))
	_bbox_image_size = Vector2(state.get("bbox_image_size", _bbox_image_size))
	_bbox_depth_m = float(state.get("bbox_depth_m", _bbox_depth_m))
	_bbox_angular_size_deg = Vector2(state.get("bbox_angular_size_deg", _bbox_angular_size_deg))
	_paused = bool(state.get("paused", _paused))
	_last_command = str(state.get("last_command", _last_command))


func _run_command_effects(effects: Array) -> void:
	for effect in effects:
		match str(effect):
			CommandDispatcherScript.EFFECT_APPLY_BBOX_ANCHOR:
				_apply_bbox_anchor()
			CommandDispatcherScript.EFFECT_HIDE_VST_BBOX_FRAME:
				_set_vst_bbox_frame_visible(false)
			CommandDispatcherScript.EFFECT_DEBUG_TARGET_FREE:
				if _debug_target_marker != null and is_instance_valid(_debug_target_marker):
					_debug_target_marker.queue_free()
				_debug_target_marker = null
			CommandDispatcherScript.EFFECT_DEBUG_TARGET_RESET:
				_build_debug_target_marker()
			CommandDispatcherScript.EFFECT_APPLY_3DOF_ANCHOR:
				_apply_3dof_anchor_transform()


func _apply_bbox_payload(parsed: Dictionary) -> void:
	_sync_card_state_from_fields()
	if not _card_state.apply_bbox_payload(parsed):
		return
	_sync_card_fields_from_state()
	_apply_bbox_anchor()


func _apply_bbox_anchor() -> void:
	var anchor := _anchor_from_bbox(_bbox_center_px, _bbox_size_px, _bbox_image_size, _bbox_depth_m)
	_card_state.apply_bbox_anchor(anchor)
	_sync_card_fields_from_state()


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
	var orient_callable := Callable()
	if _face_camera_enabled:
		orient_callable = Callable(self, "_orient_node_for_3dof_reading")
	_vst_debug_ui.update_world_bbox_frame(_anchor_position_from_yaw_pitch_depth(), _anchor_depth_m, _bbox_angular_size_deg, orient_callable)


func _set_vst_bbox_frame_visible(visible: bool) -> void:
	_vst_debug_ui.set_world_bbox_visible(visible)


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
		_status_hud.update_status_label(snapshot, delta)
	_status_hud.write_status_files(snapshot, delta)


## Per-frame status snapshot consumed by StatusHud (label rendering + the
## user:// status file writers). This script resolves live values; the
## dependency-free composer owns the stable dictionary shape.
func _build_status_snapshot() -> Dictionary:
	return _status_snapshot_composer.build_status_snapshot({
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
	})


func _build_xr_status_snapshot() -> Dictionary:
	return _status_snapshot_composer.build_xr_status_snapshot(
		_xr_interface_found,
		_xr_initialize_ok,
		_xr_active,
		_xr_init_error
	)


func _build_vst_status_snapshot() -> Dictionary:
	var target_state := "lost"
	if _vst_target_source != null:
		target_state = _vst_target_source.target_state()
	var snapshot: Dictionary = _vst_capture.status_snapshot()
	return _status_snapshot_composer.build_vst_status_snapshot(snapshot, target_state)


func _build_proxy_targets_status_snapshot() -> Dictionary:
	return _status_snapshot_composer.build_proxy_targets_status_snapshot(_card_receiver.status_values({
		"attachments": _card_attachment.size(),
		"card_target_id": _proxy_targets_card_target_id(),
		"proxy_target_count": _proxy_targets_proxy_count(),
		"proxy_target_ids": _proxy_targets_proxy_ids(),
		"card_resolved_position": _proxy_targets_card_resolved_position(),
		"card_node_position": _proxy_targets_card_node_position(),
		"card_apply_count": _proxy_targets_card_apply_count,
	}))


func _build_passthrough_overlay_status_snapshot() -> Dictionary:
	return _status_snapshot_composer.build_passthrough_overlay_status_snapshot(_passthrough_overlay_presenter.status_values(
		_passthrough_overlay_enabled,
		_passthrough_overlay_requested_blend_mode,
		_passthrough_overlay_blend_ok
	))


func _exit_tree() -> void:
	_vst_capture.shutdown()


func _setup_vst_capture() -> void:
	var vst_calibration: Dictionary = _options.vst_camera_calibration(BBOX_HORIZONTAL_FOV_DEG, BBOX_VERTICAL_FOV_DEG)
	_vst_capture.set_camera_calibration(
		float(vst_calibration.get("horizontal_fov_deg", BBOX_HORIZONTAL_FOV_DEG)),
		float(vst_calibration.get("vertical_fov_deg", BBOX_VERTICAL_FOV_DEG)),
		Vector2(vst_calibration.get("principal_point_px", Vector2(-1.0, -1.0))),
		Vector2(vst_calibration.get("focal_length_px", Vector2(-1.0, -1.0)))
	)
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
	_vst_debug_ui.update_raw_image(right_img, image_size)


func _on_vst_tracker_boxes(boxes: PackedFloat32Array, image_size: Vector2) -> void:
	_vst_right_image_size = image_size
	if boxes.size() >= 5:
		_vst_debug_ui.update_raw_bbox_overlay(boxes, image_size)
	else:
		_vst_debug_ui.set_raw_bbox_visible(false)
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


