extends SceneTree

## Script-only runtime probe for vst_capture.gd. Runs in no-project mode with:
##   SMARTXR_VST_CAPTURE_SCRIPT             abs path to vst_capture.gd
##   SMARTXR_VST_CAPTURE_PROBE_STATUS_PATH  abs path for result JSON

const DEFAULT_STATUS_RES := "user://vst_capture_probe_status.json"
const TOLERANCE := 0.0001

var _checks := {}
var _error := "-"
var _exit_code := 1
var _ran := false
var _anchor_events := []


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


func _approx(a: float, b: float) -> bool:
	return absf(a - b) <= TOLERANCE


func _vec3_close(actual: Vector3, expected: Vector3) -> bool:
	return _approx(actual.x, expected.x) and _approx(actual.y, expected.y) and _approx(actual.z, expected.z)


func _on_anchor(anchor: Dictionary) -> void:
	_anchor_events.append(anchor.duplicate(true))


func _run_checks() -> String:
	var script_path := OS.get_environment("SMARTXR_VST_CAPTURE_SCRIPT")
	if script_path.is_empty():
		return "missing_env:SMARTXR_VST_CAPTURE_SCRIPT"
	var script = load(script_path)
	if script == null:
		return "load_failed:" + script_path
	_checks["vst_capture_script_loads"] = true
	_checks["vst_capture_script_can_instantiate"] = script.can_instantiate()

	var capture = script.new({
		"horizontal_fov_deg": 70.0,
		"vertical_fov_deg": 43.0,
		"min_depth_m": 0.65,
		"max_depth_m": 4.0,
		"start_depth_m": 1.35,
	})
	capture.set_anchor_callback(_on_anchor)

	var status: Dictionary = capture.status_snapshot()
	_checks["status_snapshot_defaults"] = \
		not bool(status.get("class_registered", true)) \
		and not bool(status.get("init_ok", true)) \
		and int(status.get("frames", -1)) == 0 \
		and int(status.get("box_count", -1)) == 0 \
		and str(status.get("last_error", "")) == "not initialized"

	capture.setup_capture(false)
	_checks["xr_inactive_blocks_capture"] = str(capture.last_error()).begins_with("OpenXR inactive")

	var center_anchor: Dictionary = capture.anchor_from_bbox(
		Vector2(436.0, 326.0),
		Vector2(180.0, 240.0),
		Vector2(872.0, 652.0),
		1.35
	)
	_checks["bbox_center_math"] = \
		_approx(float(center_anchor.get("yaw_deg")), 0.0) \
		and _approx(float(center_anchor.get("pitch_deg")), 0.0) \
		and _approx(float(center_anchor.get("depth_m")), 1.35) \
		and _vec3_close(capture.target_position_from_bbox_anchor(center_anchor), Vector3(0.0, 0.0, -1.35))

	_checks["default_head_conversion"] = capture.convert_vst_camera_point_to_head_convention(Vector3(1.0, 2.0, 3.0)).is_equal_approx(Vector3(1.0, -2.0, -3.0))

	capture.store_right_eye_to_head_matrix({
		"ret": 0,
		"right": PackedFloat64Array([
			1.0, 0.0, 0.0, 0.1,
			0.0, 1.0, 0.0, 0.2,
			0.0, 0.0, 1.0, 0.3,
			0.0, 0.0, 0.0, 1.0,
		]),
	})
	_checks["eye_to_head_matrix_path"] = capture.uses_eye_to_head_anchor() \
		and capture.transform_right_vst_point_to_head(Vector3(1.0, 2.0, 3.0)).is_equal_approx(Vector3(1.1, 2.2, 3.3))

	capture._right_image_size = Vector2(872.0, 652.0)
	var boxes := PackedFloat32Array([0.4, 0.4, 0.2, 0.2, 0.9])
	var transform: Transform3D = capture.tracker_box_to_target_transform(boxes, 1.35)
	_checks["tracker_box_to_target_transform"] = not transform.origin.is_equal_approx(Vector3.ZERO)
	capture._apply_vst_tracker_anchor(boxes)
	_checks["anchor_callback_fired"] = _anchor_events.size() == 1 \
		and _approx(float(_anchor_events[0].get("confidence", 0.0)), 0.9) \
		and int(_anchor_events[0].get("anchor_updates", 0)) == 1

	return "-"


func _all_passed() -> bool:
	for key in _checks.keys():
		if not bool(_checks[key]):
			_error = "check_failed:" + str(key)
			return false
	return true


func _write_status(exit_code: int) -> void:
	var status_path := OS.get_environment("SMARTXR_VST_CAPTURE_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file == null:
		return
	file.store_string(JSON.stringify({
		"harness": "script_only_vst_capture_probe",
		"exit_code": exit_code,
		"error": _error,
		"checks": _checks,
	}, "\t"))
	file.close()
