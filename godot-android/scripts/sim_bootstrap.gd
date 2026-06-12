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
const MIN_PITCH_DEG := -85.0
const MAX_PITCH_DEG := 85.0

var move_speed_mps := DEFAULT_MOVE_SPEED_MPS
var mouse_sensitivity := DEFAULT_MOUSE_SENSITIVITY

var _camera: Camera3D = null
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


func status_snapshot() -> Dictionary:
	return {
		"enabled": true,
		"mode": "desktop_sim",
		"camera_position": _camera.global_position if _camera != null else null,
		"camera_rotation_degrees": _camera.global_rotation_degrees if _camera != null else null,
		"move_speed_mps": move_speed_mps,
		"mouse_captured": _mouse_captured,
	}


func _apply_camera_rotation() -> void:
	if _camera == null:
		return
	_camera.rotation_degrees = Vector3(_pitch_deg, _yaw_deg, 0.0)
