extends RefCounted
class_name SimBootstrap

## Desktop simulator bootstrap for the card scene.
##
## Keeps the simulator dependency-free enough for script-only probes: it owns
## the non-XR interface override and fallback camera movement, while
## AndroidMovingCard keeps card state, anchor math, HUD snapshot assembly, and
## all card UI/target logic.

const MODE := "desktop_sim"
const DEFAULT_MOVE_SPEED_MPS := 1.75
const DEFAULT_MOUSE_SENSITIVITY := 0.10
const DEFAULT_IPD_M := 0.064
const DEFAULT_STEREO_FOV_DEG := 70.0
const DEFAULT_STEREO_VIEWPORT_SIZE := Vector2i(640, 720)
const MIN_PITCH_DEG := -85.0
const MAX_PITCH_DEG := 85.0

var move_speed_mps := DEFAULT_MOVE_SPEED_MPS
var mouse_sensitivity := DEFAULT_MOUSE_SENSITIVITY
var ipd_m := DEFAULT_IPD_M
var stereo_fov_deg := DEFAULT_STEREO_FOV_DEG

var _camera: Camera3D = null
var _stereo_layer: CanvasLayer = null
var _left_eye_viewport: SubViewport = null
var _right_eye_viewport: SubViewport = null
var _left_eye_camera: Camera3D = null
var _right_eye_camera: Camera3D = null
var _yaw_deg := 0.0
var _pitch_deg := 0.0
var _mouse_captured := false


func apply_to_xr_bootstrap(xr_bootstrap) -> void:
	if xr_bootstrap == null:
		return
	xr_bootstrap.set_interface_provider(func(): return null)


func bind_camera(camera: Camera3D) -> void:
	_camera = camera
	if _camera == null:
		return
	_camera.name = "SimFallbackCamera"
	_camera.position = Vector3(0.0, 0.0, 0.0)
	_yaw_deg = _camera.rotation_degrees.y
	_pitch_deg = _camera.rotation_degrees.x
	_apply_camera_rotation()
	_camera.make_current()
	_sync_stereo_eye_transforms()


func build_stereo_preview(owner: Node, source_viewport: Viewport) -> void:
	if owner == null or source_viewport == null or _camera == null:
		return
	if _stereo_layer != null:
		return

	_stereo_layer = CanvasLayer.new()
	_stereo_layer.name = "SimStereoPreview"
	owner.add_child(_stereo_layer)

	var root := Control.new()
	root.name = "SimStereoRoot"
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_stereo_layer.add_child(root)

	var views := HBoxContainer.new()
	views.name = "SimStereoViews"
	views.set_anchors_preset(Control.PRESET_FULL_RECT)
	views.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(views)

	_left_eye_viewport = _make_eye_viewport("LeftEyeViewport", "LeftEyeCamera", source_viewport)
	_right_eye_viewport = _make_eye_viewport("RightEyeViewport", "RightEyeCamera", source_viewport)
	root.add_child(_left_eye_viewport)
	root.add_child(_right_eye_viewport)
	_left_eye_camera = _left_eye_viewport.get_node("LeftEyeCamera")
	_right_eye_camera = _right_eye_viewport.get_node("RightEyeCamera")

	views.add_child(_make_eye_panel("LeftEyePanel", "LeftEyeTexture", "LeftEyeLabel", "LEFT", _left_eye_viewport))
	views.add_child(_make_eye_panel("RightEyePanel", "RightEyeTexture", "RightEyeLabel", "RIGHT", _right_eye_viewport))
	_sync_stereo_eye_transforms()


func handle_input(event: InputEvent) -> void:
	if _camera == null:
		return
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
		_mouse_captured = true
		Input.set_mouse_mode(Input.MOUSE_MODE_CAPTURED)
	if event is InputEventKey and event.keycode == KEY_ESCAPE and event.pressed:
		_mouse_captured = false
		Input.set_mouse_mode(Input.MOUSE_MODE_VISIBLE)
	if event is InputEventMouseMotion and _mouse_captured:
		_yaw_deg -= event.relative.x * mouse_sensitivity
		_pitch_deg = clampf(_pitch_deg - event.relative.y * mouse_sensitivity, MIN_PITCH_DEG, MAX_PITCH_DEG)
		_apply_camera_rotation()


func update(delta: float) -> void:
	if _camera == null:
		return
	var direction := Vector3.ZERO
	if Input.is_key_pressed(KEY_W):
		direction -= _camera.global_transform.basis.z
	if Input.is_key_pressed(KEY_S):
		direction += _camera.global_transform.basis.z
	if Input.is_key_pressed(KEY_A):
		direction -= _camera.global_transform.basis.x
	if Input.is_key_pressed(KEY_D):
		direction += _camera.global_transform.basis.x
	if Input.is_key_pressed(KEY_E):
		direction += Vector3.UP
	if Input.is_key_pressed(KEY_Q):
		direction -= Vector3.UP
	if direction.length_squared() > 0.0:
		_camera.global_position += direction.normalized() * move_speed_mps * delta
	_sync_stereo_eye_transforms()


func status_snapshot() -> Dictionary:
	return {
		"enabled": true,
		"mode": "desktop_sim",
		"camera_position": _camera.global_position if _camera != null else null,
		"camera_rotation_degrees": _camera.global_rotation_degrees if _camera != null else null,
		"move_speed_mps": move_speed_mps,
		"mouse_captured": _mouse_captured,
		"stereo_enabled": _stereo_layer != null,
		"ipd_m": ipd_m,
		"stereo_fov_deg": stereo_fov_deg,
		"left_eye_position": _left_eye_camera.global_position if _left_eye_camera != null else null,
		"right_eye_position": _right_eye_camera.global_position if _right_eye_camera != null else null,
	}


func _apply_camera_rotation() -> void:
	if _camera == null:
		return
	_camera.rotation_degrees = Vector3(_pitch_deg, _yaw_deg, 0.0)
	_sync_stereo_eye_transforms()


func _make_eye_viewport(viewport_name: String, camera_name: String, source_viewport: Viewport) -> SubViewport:
	var viewport := SubViewport.new()
	viewport.name = viewport_name
	viewport.size = _stereo_viewport_size(source_viewport)
	viewport.transparent_bg = false
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	viewport.world_3d = source_viewport.world_3d

	var camera := Camera3D.new()
	camera.name = camera_name
	camera.projection = Camera3D.PROJECTION_PERSPECTIVE
	camera.fov = stereo_fov_deg
	camera.current = true
	viewport.add_child(camera)
	return viewport


func _make_eye_texture_rect(rect_name: String, viewport: SubViewport) -> TextureRect:
	var rect := TextureRect.new()
	rect.name = rect_name
	rect.texture = viewport.get_texture()
	rect.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	rect.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	rect.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rect.size_flags_vertical = Control.SIZE_EXPAND_FILL
	rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return rect


func _make_eye_panel(panel_name: String, rect_name: String, label_name: String, label_text: String, viewport: SubViewport) -> Control:
	var panel := Control.new()
	panel.name = panel_name
	panel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	panel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	panel.mouse_filter = Control.MOUSE_FILTER_IGNORE

	var rect := _make_eye_texture_rect(rect_name, viewport)
	rect.set_anchors_preset(Control.PRESET_FULL_RECT)
	panel.add_child(rect)

	var label := Label.new()
	label.name = label_name
	label.text = label_text
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_LEFT
	label.vertical_alignment = VERTICAL_ALIGNMENT_TOP
	label.offset_left = 16.0
	label.offset_top = 12.0
	label.add_theme_font_size_override("font_size", 20)
	label.add_theme_color_override("font_color", Color(0.6, 0.95, 1.0, 1.0))
	label.add_theme_color_override("font_shadow_color", Color(0.0, 0.0, 0.0, 0.75))
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	panel.add_child(label)
	return panel


func _stereo_viewport_size(source_viewport: Viewport) -> Vector2i:
	var visible_size := source_viewport.get_visible_rect().size
	if visible_size.x <= 0.0 or visible_size.y <= 0.0:
		return DEFAULT_STEREO_VIEWPORT_SIZE
	return Vector2i(maxi(1, int(visible_size.x * 0.5)), maxi(1, int(visible_size.y)))


func _sync_stereo_eye_transforms() -> void:
	if _camera == null or _left_eye_camera == null or _right_eye_camera == null:
		return
	var head_transform := _camera.global_transform
	var head_basis := head_transform.basis.orthonormalized()
	_left_eye_camera.global_transform = Transform3D(
		head_basis,
		head_transform * Vector3(-ipd_m * 0.5, 0.0, 0.0)
	)
	_right_eye_camera.global_transform = Transform3D(
		head_basis,
		head_transform * Vector3(ipd_m * 0.5, 0.0, 0.0)
	)
