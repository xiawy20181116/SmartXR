extends SceneTree

## Script-only runtime probe for sim_bootstrap.gd.
##
## Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with:
##   SMARTXR_SIM_BOOTSTRAP_SCRIPT             abs path to sim_bootstrap.gd
##   SMARTXR_SIM_BOOTSTRAP_PROBE_STATUS_PATH  optional result JSON path

const DEFAULT_STATUS_RES := "user://sim_bootstrap_probe_status.json"

var _checks := {}
var _error := "-"
var _exit_code := 1
var _ran := false


class FakeXRBootstrap:
	var provider = Callable()

	func set_interface_provider(next_provider: Callable) -> void:
		provider = next_provider


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
	var sim_script_path := OS.get_environment("SMARTXR_SIM_BOOTSTRAP_SCRIPT")
	if sim_script_path.is_empty():
		return "missing_env:SMARTXR_SIM_BOOTSTRAP_SCRIPT"
	var sim_script = load(sim_script_path)
	if sim_script == null:
		return "load_failed:" + sim_script_path
	_checks["sim_script_loads"] = true
	_checks["sim_script_can_instantiate"] = sim_script.can_instantiate()

	var sim = sim_script.new()
	var fake_xr := FakeXRBootstrap.new()
	sim.apply_to_xr_bootstrap(fake_xr)
	_checks["force_non_xr_provider"] = fake_xr.provider.is_valid() and fake_xr.provider.call() == null

	var stage := Node3D.new()
	stage.name = "SimProbeStage"
	root.add_child(stage)
	var camera := Camera3D.new()
	camera.name = "ProbeCamera"
	stage.add_child(camera)
	sim.bind_camera(camera)
	_checks["bind_camera_names_and_currents"] = str(camera.name) == "SimFallbackCamera" \
		and camera.current == true \
		and camera.position.is_equal_approx(Vector3.ZERO)

	var click := InputEventMouseButton.new()
	click.button_index = MOUSE_BUTTON_LEFT
	click.pressed = true
	sim.handle_input(click)
	var motion := InputEventMouseMotion.new()
	motion.relative = Vector2(25.0, -10.0)
	sim.handle_input(motion)
	_checks["mouse_motion_updates_rotation"] = not camera.rotation_degrees.is_equal_approx(Vector3.ZERO)

	var snapshot: Dictionary = sim.status_snapshot()
	_checks["status_snapshot_reports_desktop_sim"] = bool(snapshot.get("enabled", false)) \
		and str(snapshot.get("mode", "")) == "desktop_sim" \
		and snapshot.get("camera_position") is Vector3 \
		and snapshot.get("camera_rotation_degrees") is Vector3 \
		and float(snapshot.get("move_speed_mps", 0.0)) > 0.0
	sim.build_stereo_preview(stage, root)
	var left_viewport := stage.get_node_or_null("SimStereoPreview/SimStereoRoot/LeftEyeViewport")
	var right_viewport := stage.get_node_or_null("SimStereoPreview/SimStereoRoot/RightEyeViewport")
	var left_label := stage.get_node_or_null("SimStereoPreview/SimStereoRoot/SimStereoViews/LeftEyePanel/LeftEyeLabel")
	var right_label := stage.get_node_or_null("SimStereoPreview/SimStereoRoot/SimStereoViews/RightEyePanel/RightEyeLabel")
	var stereo_root := stage.get_node_or_null("SimStereoPreview/SimStereoRoot")
	var stereo_views := stage.get_node_or_null("SimStereoPreview/SimStereoRoot/SimStereoViews")
	var left_panel := stage.get_node_or_null("SimStereoPreview/SimStereoRoot/SimStereoViews/LeftEyePanel")
	var right_panel := stage.get_node_or_null("SimStereoPreview/SimStereoRoot/SimStereoViews/RightEyePanel")
	var left_texture := stage.get_node_or_null("SimStereoPreview/SimStereoRoot/SimStereoViews/LeftEyePanel/LeftEyeTexture")
	var right_texture := stage.get_node_or_null("SimStereoPreview/SimStereoRoot/SimStereoViews/RightEyePanel/RightEyeTexture")
	var left_camera := left_viewport.get_node_or_null("LeftEyeCamera") if left_viewport != null else null
	var right_camera := right_viewport.get_node_or_null("RightEyeCamera") if right_viewport != null else null
	_checks["stereo_preview_builds_left_and_right_eye_viewports"] = left_viewport is SubViewport \
		and right_viewport is SubViewport \
		and left_camera is Camera3D \
		and right_camera is Camera3D \
		and left_camera.current == true \
		and right_camera.current == true
	_checks["stereo_preview_labels_left_and_right_eyes"] = left_label is Label \
		and right_label is Label \
		and str(left_label.text) == "LEFT" \
		and str(right_label.text) == "RIGHT"
	_checks["stereo_preview_ignores_mouse_input"] = stereo_root is Control \
		and stereo_views is Control \
		and left_panel is Control \
		and right_panel is Control \
		and left_texture is Control \
		and right_texture is Control \
		and stereo_root.mouse_filter == Control.MOUSE_FILTER_IGNORE \
		and stereo_views.mouse_filter == Control.MOUSE_FILTER_IGNORE \
		and left_panel.mouse_filter == Control.MOUSE_FILTER_IGNORE \
		and right_panel.mouse_filter == Control.MOUSE_FILTER_IGNORE \
		and left_texture.mouse_filter == Control.MOUSE_FILTER_IGNORE \
		and right_texture.mouse_filter == Control.MOUSE_FILTER_IGNORE
	var stereo_snapshot: Dictionary = sim.status_snapshot()
	_checks["stereo_status_reports_ipd_and_eye_positions"] = bool(stereo_snapshot.get("stereo_enabled", false)) \
		and float(stereo_snapshot.get("ipd_m", 0.0)) > 0.0 \
		and stereo_snapshot.get("left_eye_position") is Vector3 \
		and stereo_snapshot.get("right_eye_position") is Vector3 \
		and not stereo_snapshot.get("left_eye_position").is_equal_approx(stereo_snapshot.get("right_eye_position"))
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
		"harness": "script_only_sim_bootstrap_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_SIM_BOOTSTRAP_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("sim_bootstrap_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
