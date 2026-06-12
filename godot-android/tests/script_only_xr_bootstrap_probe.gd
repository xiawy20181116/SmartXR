extends SceneTree

## Script-only runtime probe for the XR bootstrap subsystem (M3 step 5,
## YAN-79).
##
## Runs in no-project mode like the other script-only probes (a project run
## would boot the full main scene, which never exits headless):
##   godot --headless --script <abs path to this file>
## with the subsystem script injected via env:
##   SMARTXR_XR_BOOTSTRAP_SCRIPT             abs path to xr_bootstrap.gd
##   SMARTXR_XR_BOOTSTRAP_PROBE_STATUS_PATH  abs path for the probe result
##                                           JSON (optional)
##
## Verifies at runtime, with injected fake interfaces (no OpenXR runtime
## exists headless): the interface-not-found fallback, the initialize-false
## fallback, the fallback camera construction (name/far/current/look_at
## target, default and injected), the XR-active XROrigin3D + XRCamera3D
## construction, both blend-request branches (set_environment_blend_mode
## has_method branch with true/false results, the environment_blend_mode
## property branch) and their bookkeeping, the viewport use_xr /
## transparent_bg flips, and the exact init_error strings. Exits 0 only if
## every check passed.

const DEFAULT_STATUS_RES := "user://xr_bootstrap_probe_status.json"

var _checks := {}
var _error := "-"
var _exit_code := 1
var _ran := false


## Duck-typed stand-in for the OpenXR interface: the subsystem only calls
## initialize() / has_method() / call("set_environment_blend_mode", ...), so
## the probe can flip the initialize result and record blend requests.
class FakeXRInterface:
	var initialize_result := true
	var blend_result := true
	var blend_modes := []

	func initialize() -> bool:
		return initialize_result

	func set_environment_blend_mode(mode: int) -> bool:
		blend_modes.append(mode)
		return blend_result


## Fake without set_environment_blend_mode: exercises the property-assignment
## else-branch of the blend request.
class FakePropertyXRInterface:
	var environment_blend_mode := -1

	func initialize() -> bool:
		return true


# Checks run from the first main-loop iteration instead of _initialize: the
# camera's look_at needs global transforms, which error with
# "!is_inside_tree()" until the root Window has entered the tree, and quit()
# inside _initialize is not honored in script-only mode (same rule as the
# other script-only probes).
func _process(_delta: float) -> bool:
	if not _ran:
		_ran = true
		var run_error := _run_checks()
		if run_error != "-":
			_error = run_error
		elif _all_passed():
			_exit_code = 0
		_write_status(_exit_code)
	quit(_exit_code)
	return true


func _run_checks() -> String:
	var bootstrap_script_path := OS.get_environment("SMARTXR_XR_BOOTSTRAP_SCRIPT")
	if bootstrap_script_path.is_empty():
		return "missing_env:SMARTXR_XR_BOOTSTRAP_SCRIPT"
	var bootstrap_script = load(bootstrap_script_path)
	if bootstrap_script == null:
		return "load_failed:" + bootstrap_script_path
	_checks["bootstrap_script_loads"] = true
	_checks["bootstrap_script_can_instantiate"] = bootstrap_script.can_instantiate()

	# Scene-tree stage: setup_camera parents need to be inside the tree, and
	# each scenario gets its own parent so cameras do not collide.
	var stage := Node3D.new()
	stage.name = "ProbeStage"
	root.add_child(stage)

	# 1. Defaults match the card's pre-init state byte-for-byte.
	var fresh = bootstrap_script.new()
	_checks["defaults_error_not_attempted"] = fresh.init_error() == "not attempted"
	_checks["defaults_flags_false"] = fresh.interface_found() == false \
		and fresh.initialize_ok() == false \
		and fresh.xr_active() == false \
		and fresh.blend_request_ok() == false
	_checks["defaults_blend_mode_alpha"] = fresh.requested_blend_mode() == "alpha_blend"
	_checks["defaults_no_nodes"] = fresh.xr_origin() == null and fresh.camera() == null

	# 2. Interface-not-found path: flags, exact error string, viewport
	# untouched, then the fallback camera with an injected look_at target.
	var not_found = bootstrap_script.new()
	not_found.set_interface_provider(func(): return null)
	var not_found_viewport := SubViewport.new()
	stage.add_child(not_found_viewport)
	not_found.try_init_xr(not_found_viewport)
	_checks["not_found_reports_flags"] = not_found.interface_found() == false \
		and not_found.initialize_ok() == false \
		and not_found.xr_active() == false
	_checks["not_found_error_string"] = not_found.init_error() == "OpenXR interface not found"
	_checks["not_found_leaves_viewport"] = not_found_viewport.use_xr == false \
		and not_found_viewport.transparent_bg == false

	var look_at_target := Vector3(1.0, 0.5, -2.0)
	not_found.set_fallback_look_at_provider(func(): return look_at_target)
	var fallback_parent := Node3D.new()
	fallback_parent.name = "FallbackParent"
	stage.add_child(fallback_parent)
	not_found.setup_camera(fallback_parent)
	var fallback_camera = not_found.camera()
	_checks["fallback_camera_constructed"] = fallback_camera is Camera3D \
		and not (fallback_camera is XRCamera3D) \
		and fallback_camera.get_parent() == fallback_parent
	_checks["fallback_camera_name_far"] = fallback_camera != null \
		and str(fallback_camera.name) == "FallbackCamera" \
		and is_equal_approx(fallback_camera.far, 50.0)
	_checks["fallback_camera_position_zero"] = fallback_camera != null \
		and fallback_camera.position.is_equal_approx(Vector3(0.0, 0.0, 0.0))
	_checks["fallback_camera_no_origin"] = not_found.xr_origin() == null
	_checks["fallback_camera_made_current"] = fallback_camera != null and fallback_camera.current == true
	_checks["fallback_camera_looks_at_target"] = fallback_camera != null \
		and (-fallback_camera.global_transform.basis.z).is_equal_approx(look_at_target.normalized())

	# Default look_at target (one meter forward) when no provider is wired.
	var unwired = bootstrap_script.new()
	unwired.set_interface_provider(func(): return null)
	var unwired_viewport := SubViewport.new()
	stage.add_child(unwired_viewport)
	unwired.try_init_xr(unwired_viewport)
	var unwired_parent := Node3D.new()
	unwired_parent.name = "UnwiredParent"
	stage.add_child(unwired_parent)
	unwired.setup_camera(unwired_parent)
	var unwired_camera = unwired.camera()
	_checks["fallback_camera_default_look_at_forward"] = unwired_camera != null \
		and (-unwired_camera.global_transform.basis.z).is_equal_approx(Vector3(0.0, 0.0, -1.0))

	# 3. Initialize-false path: flags, exact error string, no blend request,
	# viewport untouched.
	var refuse_interface := FakeXRInterface.new()
	refuse_interface.initialize_result = false
	var init_false = bootstrap_script.new()
	init_false.set_interface_provider(func(): return refuse_interface)
	var init_false_viewport := SubViewport.new()
	stage.add_child(init_false_viewport)
	init_false.try_init_xr(init_false_viewport)
	_checks["init_false_reports_flags"] = init_false.interface_found() == true \
		and init_false.initialize_ok() == false \
		and init_false.xr_active() == false
	_checks["init_false_error_string"] = init_false.init_error() == "OpenXR initialize returned false"
	_checks["init_false_skips_blend_request"] = init_false.blend_request_ok() == false \
		and refuse_interface.blend_modes.is_empty()
	_checks["init_false_leaves_viewport"] = init_false_viewport.use_xr == false \
		and init_false_viewport.transparent_bg == false

	# 4. XR-active path with the has_method blend branch: flags, viewport
	# flips, blend bookkeeping (mode argument recorded), empty init_error,
	# then XROrigin3D + XRCamera3D construction.
	var live_interface := FakeXRInterface.new()
	var active = bootstrap_script.new()
	active.set_interface_provider(func(): return live_interface)
	var active_viewport := SubViewport.new()
	stage.add_child(active_viewport)
	active.try_init_xr(active_viewport)
	_checks["active_reports_flags"] = active.interface_found() == true \
		and active.initialize_ok() == true \
		and active.xr_active() == true
	_checks["active_clears_init_error"] = active.init_error() == ""
	_checks["active_flips_viewport"] = active_viewport.use_xr == true \
		and active_viewport.transparent_bg == true
	_checks["active_blend_request_bookkeeping"] = active.requested_blend_mode() == "alpha_blend" \
		and active.blend_request_ok() == true
	_checks["active_blend_mode_argument"] = live_interface.blend_modes == [XRInterface.XR_ENV_BLEND_MODE_ALPHA_BLEND]

	var active_parent := Node3D.new()
	active_parent.name = "ActiveParent"
	stage.add_child(active_parent)
	active.setup_camera(active_parent)
	var origin = active.xr_origin()
	var xr_camera = active.camera()
	_checks["active_origin_constructed"] = origin is XROrigin3D \
		and str(origin.name) == "XROrigin" \
		and origin.get_parent() == active_parent
	_checks["active_camera_constructed"] = xr_camera is XRCamera3D \
		and str(xr_camera.name) == "XRCamera" \
		and is_equal_approx(xr_camera.far, 50.0) \
		and xr_camera.get_parent() == origin

	# 5. has_method blend branch returning false: still active, bookkeeping
	# records the refusal.
	var refuse_blend_interface := FakeXRInterface.new()
	refuse_blend_interface.blend_result = false
	var blend_false = bootstrap_script.new()
	blend_false.set_interface_provider(func(): return refuse_blend_interface)
	var blend_false_viewport := SubViewport.new()
	stage.add_child(blend_false_viewport)
	blend_false.try_init_xr(blend_false_viewport)
	_checks["blend_false_still_active"] = blend_false.xr_active() == true \
		and blend_false.init_error() == ""
	_checks["blend_false_bookkeeping"] = blend_false.blend_request_ok() == false \
		and blend_false.requested_blend_mode() == "alpha_blend"

	# 6. Property else-branch (interface without set_environment_blend_mode):
	# assigns environment_blend_mode and reports the request as ok.
	var property_interface := FakePropertyXRInterface.new()
	var property_branch = bootstrap_script.new()
	property_branch.set_interface_provider(func(): return property_interface)
	var property_viewport := SubViewport.new()
	stage.add_child(property_viewport)
	property_branch.try_init_xr(property_viewport)
	_checks["property_branch_blend_ok"] = property_branch.xr_active() == true \
		and property_branch.blend_request_ok() == true
	_checks["property_branch_sets_mode"] = property_interface.environment_blend_mode == XRInterface.XR_ENV_BLEND_MODE_ALPHA_BLEND

	return "-"


func _all_passed() -> bool:
	if _checks.is_empty():
		return false
	for key in _checks:
		if not _checks[key]:
			return false
	return true


func _write_status(exit_code: int) -> void:
	var failed := []
	for key in _checks:
		if not _checks[key]:
			failed.append(key)
	var status := {
		"harness": "script_only_xr_bootstrap_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_XR_BOOTSTRAP_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("xr_bootstrap_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
