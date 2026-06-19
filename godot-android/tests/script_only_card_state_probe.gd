extends SceneTree

## Script-only runtime probe for card_state.gd.

const DEFAULT_STATUS_RES := "user://card_state_probe_status.json"

var _checks := {}
var _error := "-"
var _exit_code := 1


func _initialize() -> void:
	var run_error := _run_checks()
	if run_error != "-":
		_error = run_error
	elif _all_passed():
		_exit_code = 0
	_write_status(_exit_code)


func _process(_delta: float) -> bool:
	quit(_exit_code)
	return true


func _run_checks() -> String:
	var script_path := OS.get_environment("SMARTXR_CARD_STATE_SCRIPT")
	if script_path.is_empty():
		return "missing_env:SMARTXR_CARD_STATE_SCRIPT"
	var state_script = load(script_path)
	if state_script == null:
		return "load_failed:" + script_path
	_checks["card_state_script_loads"] = true

	var state = state_script.new({
		"speed_deg_per_second": 4.0,
		"anchor_yaw_deg": -31.0,
		"anchor_pitch_deg": 2.0,
		"anchor_depth_m": 1.35,
		"min_depth_m": 0.65,
		"max_depth_m": 4.0,
		"card_start_yaw_deg": 0.0,
		"card_end_yaw_deg": -32.0,
	})
	_checks["command_state_has_defaults"] = state.command_state().get("anchor_mode", "") == "manual" and state.command_state().get("last_command", "") == "none"

	state.advance_manual(1.0)
	_checks["manual_tick_wraps_yaw"] = is_equal_approx(float(state.status_values().get("anchor_yaw_deg", 99.0)), 0.0)

	var invalid := {"bbox": [], "image": {"w": 872, "h": 652}, "depth_m": 2.0}
	_checks["invalid_bbox_rejected"] = not state.apply_bbox_payload(invalid)

	var valid := {
		"bbox": {"cx": 100.0, "cy": 120.0, "w": 50.0, "h": 80.0},
		"image": {"w": 872.0, "h": 652.0},
		"depth_m": 9.0,
	}
	_checks["valid_bbox_updates_state"] = state.apply_bbox_payload(valid)
	var bbox_values: Dictionary = state.status_values()
	_checks["bbox_sets_mode_command_and_clamps_depth"] = bbox_values.get("anchor_mode", "") == "bbox" and bbox_values.get("last_command", "") == "bbox_payload" and is_equal_approx(float(bbox_values.get("bbox_depth_m", 0.0)), 4.0)

	state.apply_bbox_anchor({"yaw_deg": -12.0, "pitch_deg": 3.0, "depth_m": 2.25, "angular_size_deg": Vector2(5.0, 7.0)})
	var anchor_values: Dictionary = state.status_values()
	_checks["bbox_anchor_updates_snapshot"] = is_equal_approx(float(anchor_values.get("anchor_yaw_deg", 0.0)), -12.0) and anchor_values.get("bbox_angular_size_deg", Vector2.ZERO) == Vector2(5.0, 7.0)

	state.mark_attached("target-a")
	_checks["attach_sets_target_mode"] = state.anchor_mode() == "target" and state.last_command() == "attach_target:target-a"
	state.mark_detached(true)
	_checks["detach_empty_returns_manual"] = state.anchor_mode() == "manual"
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
		"harness": "script_only_card_state_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_CARD_STATE_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("card_state_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
