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
const WS_URL := "ws://10.1.98.195:8766/control"

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
const GXR_CAL_CV_DEWARP_L := 0x00400060
const GXR_CAL_CV_DEWARP_R := 0x00400061
const GXR_CAL_CV_SLAM := 0x00400070

var _xr_active := false
var _xr_interface_found := false
var _xr_initialize_ok := false
var _xr_init_error := "not attempted"
var _xr_origin: XROrigin3D = null
var _camera: Camera3D = null
var _ws := WebSocketPeer.new()
var _ws_connected := false
var _ws_retry_seconds := 0.0
var _card_viewport: SubViewport = null
var _card_anchor: Node3D = null
var _card_mesh: MeshInstance3D = null
var _xr_probe_mesh: MeshInstance3D = null
var _vst_bbox_frame_anchor: Node3D = null
var _vst_bbox_frame_parts: Array[MeshInstance3D] = []
var _vst_raw_debug_anchor: Node3D = null
var _vst_raw_right_sprite: Sprite3D = null
var _vst_raw_bbox_parts: Array[MeshInstance3D] = []
var _status_label: Label3D = null
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

# M1: VST capture state. _vst_capture stays null on vanilla SDK and every helper
# below short-circuits in that case, so all existing behaviour is preserved.
var _vst_class_registered := false
var _vst_capture: Object = null
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
	_try_init_xr()
	_setup_camera()
	_build_vst_raw_debug_panel()
	_setup_light()
	_build_card_anchor()
	_build_xr_render_probe()
	_build_vst_bbox_frame()
	_build_status_label()
	_connect_ws()
	_setup_vst_capture()
	set_process(true)


func _try_init_xr() -> void:
	var xr := XRServer.find_interface("OpenXR")
	_xr_interface_found = xr != null
	if xr == null:
		_xr_initialize_ok = false
		_xr_active = false
		_xr_init_error = "OpenXR interface not found"
		print("XR init: " + _xr_init_error)
		return
	_xr_initialize_ok = bool(xr.initialize())
	if not _xr_initialize_ok:
		_xr_active = false
		_xr_init_error = "OpenXR initialize returned false"
		print("XR init: " + _xr_init_error)
		return
	_xr_active = true
	get_viewport().use_xr = true
	get_viewport().transparent_bg = false
	xr.environment_blend_mode = XRInterface.XR_ENV_BLEND_MODE_OPAQUE
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	_xr_init_error = ""
	print("XR init: active use_xr=%s transparent=%s blend=opaque" % [str(get_viewport().use_xr), str(get_viewport().transparent_bg)])


func _setup_camera() -> void:
	if _xr_active:
		var origin := XROrigin3D.new()
		origin.name = "XROrigin"
		add_child(origin)
		_xr_origin = origin
		var camera := XRCamera3D.new()
		camera.name = "XRCamera"
		camera.far = 50.0
		origin.add_child(camera)
		_camera = camera
		return

	var camera := Camera3D.new()
	camera.name = "FallbackCamera"
	camera.position = Vector3(0.0, 0.0, 0.0)
	camera.far = 50.0
	add_child(camera)
	camera.look_at(_anchor_position_from_yaw_pitch_depth(), Vector3.UP)
	camera.make_current()
	_xr_origin = null
	_camera = camera


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


func _build_status_label() -> void:
	_status_label = Label3D.new()
	_status_label.name = "MeshCardStatus"
	_status_label.font_size = 22
	_status_label.outline_size = 8
	_status_label.no_depth_test = true
	_status_label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	_status_label.modulate = Color(0.72, 0.95, 1.0, 1.0)
	_status_label.position = Vector3(0.0, -0.72, 0.03)
	_card_anchor.add_child(_status_label)
	_update_status_label()


func _connect_ws() -> void:
	_ws.close()
	var result := _ws.connect_to_url(WS_URL)
	_ws_connected = false
	_ws_retry_seconds = 0.0
	if result != OK:
		_last_command = "ws connect err " + str(result)


func _process(delta: float) -> void:
	_poll_ws(delta)
	_poll_vst_bbox()
	if not _paused and _anchor_mode == "manual":
		_anchor_yaw_deg -= _speed_deg_per_second * delta
		if _anchor_yaw_deg < CARD_END_YAW_DEG:
			_anchor_yaw_deg = CARD_START_YAW_DEG
	if _anchor_mode == "bbox":
		_apply_bbox_anchor()
	_apply_3dof_anchor_transform()
	_update_status_label()


func _poll_ws(delta: float) -> void:
	_ws.poll()
	var state := _ws.get_ready_state()
	_ws_connected = state == WebSocketPeer.STATE_OPEN
	if state == WebSocketPeer.STATE_OPEN:
		while _ws.get_available_packet_count() > 0:
			_handle_packet(_ws.get_packet().get_string_from_utf8())
	elif state == WebSocketPeer.STATE_CLOSED:
		_ws_retry_seconds += delta
		if _ws_retry_seconds >= 2.0:
			_connect_ws()


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
	var fx := (image_size.x * 0.5) / tan(deg_to_rad(BBOX_HORIZONTAL_FOV_DEG) * 0.5)
	var fy := (image_size.y * 0.5) / tan(deg_to_rad(BBOX_VERTICAL_FOV_DEG) * 0.5)
	var nx := (center_px.x - image_size.x * 0.5) / fx
	var ny := (center_px.y - image_size.y * 0.5) / fy
	var ray := Vector3(nx, -ny, -1.0).normalized()
	var point := ray * depth_m
	if _vst_uses_eye_to_head_anchor:
		point = _transform_right_vst_point_to_head(point)
	var yaw_deg := rad_to_deg(atan2(point.x, -point.z))
	var pitch_deg := rad_to_deg(atan2(point.y, sqrt(point.x * point.x + point.z * point.z)))
	var angular_w := rad_to_deg(2.0 * atan((size_px.x * 0.5) / fx))
	var angular_h := rad_to_deg(2.0 * atan((size_px.y * 0.5) / fy))
	return {
		"yaw_deg": yaw_deg,
		"pitch_deg": pitch_deg,
		"depth_m": point.length() if _vst_uses_eye_to_head_anchor else depth_m,
		"angular_size_deg": Vector2(angular_w, angular_h),
	}


func _transform_right_vst_point_to_head(point: Vector3) -> Vector3:
	if _vst_right_eye_to_head_matrix.size() < 16:
		return point
	var m := _vst_right_eye_to_head_matrix
	return Vector3(
		float(m[0]) * point.x + float(m[1]) * point.y + float(m[2]) * point.z + float(m[3]),
		float(m[4]) * point.x + float(m[5]) * point.y + float(m[6]) * point.z + float(m[7]),
		float(m[8]) * point.x + float(m[9]) * point.y + float(m[10]) * point.z + float(m[11])
	)


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


func _format_vec3(value: Vector3) -> String:
	return "%.2f %.2f %.2f" % [value.x, value.y, value.z]


func _update_status_label() -> void:
	if _status_label == null or _card_anchor == null:
		return
	var corners := _corner_world_points()
	var rotation := _card_anchor.rotation_degrees
	var camera_pos := "n/a"
	var camera_rot := "n/a"
	if _camera != null:
		camera_pos = _format_vec3(_camera.global_position)
		camera_rot = _format_vec3(_camera.global_rotation_degrees)
	var xr_origin_pos := "n/a"
	if _xr_origin != null:
		xr_origin_pos = _format_vec3(_xr_origin.global_position)
	var xr_line := _format_xr_status_line()
	var vst_line := _format_vst_status_line()
	_status_label.text = "3DoF Anchor\nWS: %s  Cmd: %s  Face: 3DoF  Mode: %s\nCamera Pos xyz: %s\nCamera Rot xyz: %s\nXROrigin Pos xyz: %s\nBBox cx/cy/w/h: %.0f %.0f %.0f %.0f  Depth: %.2f\nYaw/Pitch/Depth: %.1f %.1f %.2f  Angular W/H: %.1f %.1f  Rot: %.1f %.1f %.1f\nSpeed: %.1f deg/s  Paused: %s\nTL %.2f %.2f %.2f  TR %.2f %.2f %.2f\nBL %.2f %.2f %.2f  BR %.2f %.2f %.2f\n%s\n%s" % [
		"connected" if _ws_connected else "waiting",
		_last_command,
		_anchor_mode,
		camera_pos,
		camera_rot,
		xr_origin_pos,
		_bbox_center_px.x,
		_bbox_center_px.y,
		_bbox_size_px.x,
		_bbox_size_px.y,
		_bbox_depth_m,
		_anchor_yaw_deg,
		_anchor_pitch_deg,
		_anchor_depth_m,
		_bbox_angular_size_deg.x,
		_bbox_angular_size_deg.y,
		rotation.x,
		rotation.y,
		rotation.z,
		_speed_deg_per_second,
		str(_paused),
		corners["TL"].x,
		corners["TL"].y,
		corners["TL"].z,
		corners["TR"].x,
		corners["TR"].y,
		corners["TR"].z,
		corners["BL"].x,
		corners["BL"].y,
		corners["BL"].z,
		corners["BR"].x,
		corners["BR"].y,
		corners["BR"].z,
		xr_line,
		vst_line,
	]


func _format_xr_status_line() -> String:
	var err_str := _xr_init_error if not _xr_init_error.is_empty() else "-"
	return "XR: iface=%s init=%s active=%s use_xr=%s err=%s" % [
		str(_xr_interface_found),
		str(_xr_initialize_ok),
		str(_xr_active),
		str(get_viewport().use_xr),
		err_str,
	]


func _exit_tree() -> void:
	if _vst_capture != null and _vst_capture.has_method(&"shutdown"):
		_vst_capture.shutdown()


func _setup_vst_capture() -> void:
	if not _xr_active:
		_vst_last_error = "OpenXR inactive; VST disabled to avoid passthrough-only false success"
		print("VST init blocked: " + _vst_last_error)
		return
	_vst_class_registered = ClassDB.class_exists(&"GXRDualVstCapture")
	if not _vst_class_registered:
		_vst_last_error = "GXRDualVstCapture class not registered"
		return
	_vst_capture = ClassDB.instantiate(&"GXRDualVstCapture")
	if _vst_capture == null:
		_vst_last_error = "instantiate GXRDualVstCapture failed"
		return
	if VST_RIGHT_TRACKER_ENABLED:
		_configure_vst_right_tracker_model()
	_vst_init_ok = bool(_vst_capture.initialize())
	if _vst_init_ok:
		_vst_last_error = ""
		_refresh_vst_calibration_diagnostics()
	else:
		_vst_last_error = str(_vst_capture.get_last_error()) if _vst_capture.has_method(&"get_last_error") else "initialize returned false"


func _configure_vst_right_tracker_model() -> void:
	if _vst_capture == null or not _vst_capture.has_method(&"configure_right_tracker_model"):
		_vst_last_error = "configure_right_tracker_model API unavailable"
		return
	var param_path := _stage_vst_tracker_asset(VST_NCNN_PARAM_RES, VST_NCNN_PARAM_USER)
	var bin_path := _stage_vst_tracker_asset(VST_NCNN_BIN_RES, VST_NCNN_BIN_USER)
	if param_path.is_empty() or bin_path.is_empty():
		_vst_last_error = "ncnn asset staging failed"
		return
	var ok := bool(_vst_capture.configure_right_tracker_model(param_path, bin_path))
	print("VST tracker model: ok=%s param=%s bin=%s" % [str(ok), param_path, bin_path])
	if _vst_capture.has_method(&"set_right_tracker_enabled"):
		_vst_capture.set_right_tracker_enabled(true)
	if _vst_capture.has_method(&"set_right_tracker_frame_stride"):
		_vst_capture.set_right_tracker_frame_stride(VST_RIGHT_TRACKER_FRAME_STRIDE)
	if not ok:
		_vst_last_error = "configure_right_tracker_model returned false"


func _stage_vst_tracker_asset(source_path: String, target_path: String) -> String:
	if not DirAccess.dir_exists_absolute("user://ncnn"):
		var err := DirAccess.make_dir_recursive_absolute("user://ncnn")
		if err != OK:
			return ""
	if FileAccess.file_exists(target_path):
		return ProjectSettings.globalize_path(target_path)
	var source := FileAccess.open(source_path, FileAccess.READ)
	if source == null:
		return ""
	var target := FileAccess.open(target_path, FileAccess.WRITE)
	if target == null:
		source.close()
		return ""
	target.store_buffer(source.get_buffer(source.get_length()))
	target.close()
	source.close()
	return ProjectSettings.globalize_path(target_path)


func _poll_vst_bbox() -> void:
	if _vst_capture == null or not _vst_init_ok:
		return
	if _vst_capture.has_method(&"has_new_frame_right") and bool(_vst_capture.has_new_frame_right()):
		var right_img: Image = _vst_capture.capture_frame_right() if _vst_capture.has_method(&"capture_frame_right") else null
		if right_img != null:
			_vst_right_image_size = Vector2(right_img.get_width(), right_img.get_height())
			if _vst_raw_right_sprite != null:
				_vst_raw_right_sprite.texture = ImageTexture.create_from_image(right_img)
			_vst_right_frames += 1
	if _vst_capture.has_method(&"get_right_tracker_boxes"):
		var boxes: PackedFloat32Array = _vst_capture.get_right_tracker_boxes()
		_vst_box_count = boxes.size() / 5
		if boxes.size() >= 5:
			_vst_first_box = PackedFloat32Array()
			for i in range(5):
				_vst_first_box.push_back(float(boxes[i]))
			_update_vst_raw_bbox_overlay(boxes)
			_apply_vst_tracker_anchor(boxes)
		else:
			_vst_first_box = PackedFloat32Array()
			_set_vst_raw_bbox_visible(false)
			_set_vst_bbox_frame_visible(false)
	if _vst_capture.has_method(&"get_right_tracker_total_latency_ms"):
		_vst_tracker_latency_ms = float(_vst_capture.get_right_tracker_total_latency_ms())


func _refresh_vst_calibration_diagnostics() -> void:
	if _vst_capture == null:
		return
	if _vst_capture.has_method(&"get_eye_to_head_matrices"):
		var eye_info = _vst_capture.get_eye_to_head_matrices()
		if typeof(eye_info) == TYPE_DICTIONARY:
			_store_right_eye_to_head_matrix(eye_info)
			_vst_eye_to_head_status = _format_eye_to_head_status(eye_info)
		else:
			_vst_eye_to_head_status = "eye2head: invalid response"
	else:
		_vst_eye_to_head_status = "eye2head: API missing"

	if _vst_capture.has_method(&"get_calibration_coeff_info"):
		var right_info = _vst_capture.get_calibration_coeff_info(GXR_CAL_CV_DEWARP_R, 4096)
		var slam_info = _vst_capture.get_calibration_coeff_info(GXR_CAL_CV_SLAM, 4096)
		var left_info = _vst_capture.get_calibration_coeff_info(GXR_CAL_CV_DEWARP_L, 256)
		_vst_calibration_status = "cal: L %s R %s SLAM %s" % [
			_format_calibration_probe(left_info),
			_format_calibration_probe(right_info),
			_format_calibration_probe(slam_info),
		]
	else:
		_vst_calibration_status = "cal: API missing"
	print("VST calibration: %s | %s" % [_vst_eye_to_head_status, _vst_calibration_status])


func _store_right_eye_to_head_matrix(eye_info: Dictionary) -> void:
	_vst_right_eye_to_head_matrix = PackedFloat64Array()
	_vst_uses_eye_to_head_anchor = false
	if int(eye_info.get("ret", -999)) != 0:
		return
	var right = eye_info.get("right", PackedFloat64Array())
	if not (right is PackedFloat64Array) or right.size() < 16:
		return
	for i in range(16):
		_vst_right_eye_to_head_matrix.push_back(float(right[i]))
	_vst_uses_eye_to_head_anchor = true


func _format_eye_to_head_status(eye_info: Dictionary) -> String:
	var ret := int(eye_info.get("ret", -999))
	var right = eye_info.get("right", PackedFloat64Array())
	if right is PackedFloat64Array and right.size() >= 16:
		return "eye2head: ret=%d r03=%.4f r13=%.4f r23=%.4f" % [
			ret,
			float(right[3]),
			float(right[7]),
			float(right[11]),
		]
	return "eye2head: ret=%d no-matrix" % ret


func _format_calibration_probe(info) -> String:
	if typeof(info) != TYPE_DICTIONARY:
		return "invalid"
	var bytes_size := 0
	var bytes = info.get("bytes", PackedByteArray())
	if bytes is PackedByteArray:
		bytes_size = bytes.size()
	return "ret=%d size=%d bytes=%d" % [
		int(info.get("result", -999)),
		int(info.get("actual_size", 0)),
		bytes_size,
	]


func _apply_vst_tracker_anchor(boxes: PackedFloat32Array) -> void:
	if boxes.size() < 5 or _vst_right_image_size.x <= 0.0 or _vst_right_image_size.y <= 0.0:
		return
	var x := clampf(float(boxes[0]), 0.0, 1.0)
	var y := clampf(float(boxes[1]), 0.0, 1.0)
	var w := clampf(float(boxes[2]), 0.02, 1.0)
	var h := clampf(float(boxes[3]), 0.02, 1.0)
	_bbox_center_px = Vector2((x + w * 0.5) * _vst_right_image_size.x, (y + h * 0.5) * _vst_right_image_size.y)
	_bbox_size_px = Vector2(w * _vst_right_image_size.x, h * _vst_right_image_size.y)
	_bbox_image_size = _vst_right_image_size
	_bbox_depth_m = clampf(_bbox_depth_m, MIN_DEPTH_M, MAX_DEPTH_M)
	_anchor_mode = "bbox"
	_last_command = "vst_bbox"
	_apply_bbox_anchor()
	_update_vst_bbox_frame()
	_vst_anchor_updates += 1
	if _vst_anchor_updates <= 5:
		print("VST anchor: center=%.1f %.1f size=%.1f %.1f image=%.0f %.0f yaw=%.1f pitch=%.1f" % [
			_bbox_center_px.x,
			_bbox_center_px.y,
			_bbox_size_px.x,
			_bbox_size_px.y,
			_bbox_image_size.x,
			_bbox_image_size.y,
			_anchor_yaw_deg,
			_anchor_pitch_deg,
		])


func _format_vst_status_line() -> String:
	var class_state := "registered" if _vst_class_registered else "missing"
	var init_state := "ok" if _vst_init_ok else "blocked"
	var box_str := "n/a"
	if _vst_first_box.size() >= 5:
		box_str = "%.2f %.2f %.2f %.2f %.2f" % [_vst_first_box[0], _vst_first_box[1], _vst_first_box[2], _vst_first_box[3], _vst_first_box[4]]
	var err_str := _vst_last_error if not _vst_last_error.is_empty() else "-"
	return "VST: cls=%s init=%s frames=%d boxes=%d latency=%.1fms img=%.0fx%.0f box0=%s err=%s\nAnchor: %s\n%s\n%s" % [
		class_state,
		init_state,
		_vst_right_frames,
		_vst_box_count,
		_vst_tracker_latency_ms,
		_vst_right_image_size.x,
		_vst_right_image_size.y,
		box_str,
		err_str,
		"eye2head" if _vst_uses_eye_to_head_anchor else "raw-fov",
		_vst_eye_to_head_status,
		_vst_calibration_status,
	]


func _make_panel_style() -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.06, 0.075, 0.09, 0.92)
	style.border_color = Color(0.18, 0.78, 0.86, 0.98)
	style.set_border_width_all(4)
	style.set_corner_radius_all(4)
	style.shadow_color = Color(0.0, 0.0, 0.0, 0.45)
	style.shadow_size = 24
	return style
