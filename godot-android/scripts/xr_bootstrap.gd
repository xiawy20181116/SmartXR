extends RefCounted
class_name XRBootstrap

## XR bootstrap subsystem (M3 step 5 of the YAN-73 encapsulation roadmap,
## extracted from AndroidMovingCard.gd).
##
## Owns the OpenXR startup path (interface lookup, initialize, viewport
## use_xr / transparent_bg, the alpha-blend environment request including the
## set_environment_blend_mode has_method branch, vsync disable, the "XR init:"
## prints) and the camera/origin construction (XROrigin3D + XRCamera3D when XR
## is active, FallbackCamera with look_at otherwise).
##
## State resolution stays in the card per ADR-4 (DECISIONS.md): the card calls
## try_init_xr() / setup_camera() and copies the results into its own
## _xr_* / _camera / _passthrough_overlay_* fields through the read-only
## getters below, so every status-snapshot key keeps identical values. The
## fallback camera's look_at target routes back into the card through a
## Callable (set_fallback_look_at_provider) so the 3DoF anchor math stays
## where the state lives.
##
## XRServer access is injectable for probeability: set_interface_provider
## replaces the default XRServer.find_interface("OpenXR") lookup, and the
## interface is only used duck-typed (initialize / has_method / call /
## environment_blend_mode), so a script-only probe can exercise the not-found
## path, the initialize-false path, and both blend-request branches headless
## with fakes, where no OpenXR runtime exists.
##
## Keep this script dependency-free and loadable in no-project mode: no
## preloads, no env reads, no tree access of its own, and never reference its
## own class_name inside this file (global class registration does not happen
## in script-only probes; see tools/run_godot_xr_bootstrap_probe.ps1).

var _interface_found := false
var _initialize_ok := false
var _active := false
var _init_error := "not attempted"
var _requested_blend_mode := "alpha_blend"
var _blend_request_ok := false
var _xr_origin: XROrigin3D = null
var _camera: Camera3D = null
var _interface_provider := Callable()
var _fallback_look_at_provider := Callable()


## Optional interface lookup override: func() -> XR interface object or null.
## Defaults to XRServer.find_interface("OpenXR"); probes inject fakes here.
## The returned object is used duck-typed (initialize / has_method / call /
## environment_blend_mode), never as a typed XRInterface.
func set_interface_provider(provider: Callable) -> void:
	_interface_provider = provider


## Look-at target for the fallback (non-XR) camera: func() -> Vector3. The
## card wires _anchor_position_from_yaw_pitch_depth here so the 3DoF anchor
## math stays card-side (ADR-4); defaults to one meter forward when unwired
## (probe / standalone use).
func set_fallback_look_at_provider(provider: Callable) -> void:
	_fallback_look_at_provider = provider


## The XR startup path, moved verbatim from the card's _try_init_xr. Resolves
## the interface, initializes it, flips the viewport to XR + transparent
## composition, requests the alpha-blend environment mode, and disables
## vsync. Every result is exposed through the getters below; the error
## strings and the "XR init:" prints are byte-for-byte the card's originals.
func try_init_xr(viewport: Viewport) -> void:
	var xr = _find_interface()
	_interface_found = xr != null
	if xr == null:
		_initialize_ok = false
		_active = false
		_init_error = "OpenXR interface not found"
		print("XR init: " + _init_error)
		return
	_initialize_ok = bool(xr.initialize())
	if not _initialize_ok:
		_active = false
		_init_error = "OpenXR initialize returned false"
		print("XR init: " + _init_error)
		return
	_active = true
	viewport.use_xr = true
	viewport.transparent_bg = true
	_requested_blend_mode = "alpha_blend"
	if xr.has_method("set_environment_blend_mode"):
		_blend_request_ok = bool(xr.call("set_environment_blend_mode", XRInterface.XR_ENV_BLEND_MODE_ALPHA_BLEND))
	else:
		xr.environment_blend_mode = XRInterface.XR_ENV_BLEND_MODE_ALPHA_BLEND
		_blend_request_ok = true
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	_init_error = ""
	print("XR init: active use_xr=%s transparent=%s blend=alpha" % [str(viewport.use_xr), str(viewport.transparent_bg)])


## Camera/origin construction, moved verbatim from the card's _setup_camera:
## XROrigin3D + XRCamera3D under parent when XR is active, a FallbackCamera
## looking at the card anchor otherwise. parent must already be inside the
## tree (look_at needs a global transform).
func setup_camera(parent: Node3D) -> void:
	if _active:
		var origin := XROrigin3D.new()
		origin.name = "XROrigin"
		parent.add_child(origin)
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
	parent.add_child(camera)
	camera.look_at(_fallback_look_at_target(), Vector3.UP)
	camera.make_current()
	_xr_origin = null
	_camera = camera


func interface_found() -> bool:
	return _interface_found


func initialize_ok() -> bool:
	return _initialize_ok


func xr_active() -> bool:
	return _active


func init_error() -> String:
	return _init_error


func requested_blend_mode() -> String:
	return _requested_blend_mode


func blend_request_ok() -> bool:
	return _blend_request_ok


func xr_origin() -> XROrigin3D:
	return _xr_origin


func camera() -> Camera3D:
	return _camera


func _find_interface():
	if _interface_provider.is_valid():
		return _interface_provider.call()
	return XRServer.find_interface("OpenXR")


func _fallback_look_at_target() -> Vector3:
	if _fallback_look_at_provider.is_valid():
		return _fallback_look_at_provider.call()
	return Vector3(0.0, 0.0, -1.0)
