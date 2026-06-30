extends SceneTree

## Script-only runtime probe for the command dispatcher state reducer.
##
## Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with the reducer script injected via env:
##   SMARTXR_COMMAND_DISPATCHER_SCRIPT             abs path to command_dispatcher.gd
##   SMARTXR_COMMAND_DISPATCHER_PROBE_STATUS_PATH  abs path for JSON status

const DEFAULT_STATUS_RES := "user://command_dispatcher_probe_status.json"

var _checks := {}
var _error := "-"
var _exit_code := 1
var _ran := false


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
	var dispatcher_script_path := OS.get_environment("SMARTXR_COMMAND_DISPATCHER_SCRIPT")
	if dispatcher_script_path.is_empty():
		return "missing_env:SMARTXR_COMMAND_DISPATCHER_SCRIPT"
	var dispatcher_script = load(dispatcher_script_path)
	if dispatcher_script == null:
		return "load_failed:" + dispatcher_script_path
	_checks["dispatcher_script_loads"] = true
	_checks["dispatcher_script_can_instantiate"] = dispatcher_script.can_instantiate()

	var config: Dictionary = dispatcher_script.default_config({
		"start_yaw_deg": 0.0,
		"start_pitch_deg": 0.0,
		"start_depth_m": 1.35,
		"default_speed_deg_per_second": 0.0,
		"yaw_step_deg": 3.0,
		"pitch_step_deg": 3.0,
		"depth_step_m": 0.10,
		"bbox_center_step_px": 32.0,
		"bbox_depth_step_m": 0.10,
		"speed_step_deg_per_second": 2.0,
		"min_speed_deg_per_second": 0.0,
		"max_speed_deg_per_second": 45.0,
		"min_depth_m": 0.65,
		"max_depth_m": 4.0,
		"bbox_start_center_px": Vector2(436.0, 326.0),
		"bbox_start_size_px": Vector2(180.0, 240.0),
		"bbox_image_size": Vector2(872.0, 652.0),
	})
	var state: Dictionary = dispatcher_script.default_state(config)
	_checks["default_state_matches_config"] = str(state.get("anchor_mode")) == "manual" \
		and float(state.get("anchor_depth_m")) == 1.35 \
		and Vector2(state.get("bbox_center_px")).is_equal_approx(Vector2(436.0, 326.0)) \
		and str(state.get("last_command")) == "none"

	var yaw_left: Dictionary = dispatcher_script.apply_command(state, "left", config)
	var yaw_right: Dictionary = dispatcher_script.apply_command(yaw_left, "d", config)
	_checks["yaw_aliases_switch_to_manual"] = str(yaw_left.get("anchor_mode")) == "manual" \
		and float(yaw_left.get("anchor_yaw_deg")) == -3.0 \
		and float(yaw_right.get("anchor_yaw_deg")) == 0.0 \
		and _effects(yaw_right) == [dispatcher_script.EFFECT_APPLY_3DOF_ANCHOR]

	var pitch_up: Dictionary = dispatcher_script.apply_command(state, "w", config)
	var pitch_down: Dictionary = dispatcher_script.apply_command(pitch_up, "pitch_down", config)
	_checks["pitch_aliases_switch_to_manual"] = float(pitch_up.get("anchor_pitch_deg")) == 3.0 \
		and float(pitch_down.get("anchor_pitch_deg")) == 0.0 \
		and str(pitch_down.get("anchor_mode")) == "manual"

	var near_state := state.duplicate()
	near_state["anchor_depth_m"] = 0.66
	var min_depth: Dictionary = dispatcher_script.apply_command(near_state, "closer", config)
	var far_state := state.duplicate()
	far_state["anchor_depth_m"] = 3.95
	var max_depth: Dictionary = dispatcher_script.apply_command(far_state, "farther", config)
	_checks["depth_clamps_to_min_and_max"] = float(min_depth.get("anchor_depth_m")) == 0.65 \
		and float(max_depth.get("anchor_depth_m")) == 4.0 \
		and str(min_depth.get("anchor_mode")) == "manual" \
		and str(max_depth.get("anchor_mode")) == "manual"

	var speed_up: Dictionary = dispatcher_script.apply_command(state, "plus", config)
	var max_speed_state := state.duplicate()
	max_speed_state["speed_deg_per_second"] = 44.0
	var max_speed: Dictionary = dispatcher_script.apply_command(max_speed_state, "speed_up", config)
	var speed_down: Dictionary = dispatcher_script.apply_command(speed_up, "minus", config)
	_checks["speed_commands_clamp_and_do_not_change_anchor_mode"] = float(speed_up.get("speed_deg_per_second")) == 2.0 \
		and float(max_speed.get("speed_deg_per_second")) == 45.0 \
		and float(speed_down.get("speed_deg_per_second")) == 0.0 \
		and str(speed_up.get("anchor_mode")) == "manual"

	var paused: Dictionary = dispatcher_script.apply_command(state, "space", config)
	var unpaused: Dictionary = dispatcher_script.apply_command(paused, "toggle_pause", config)
	_checks["pause_aliases_toggle"] = bool(paused.get("paused")) == true and bool(unpaused.get("paused")) == false

	var bbox_left: Dictionary = dispatcher_script.apply_command(state, "bbox_left", config)
	var bbox_right: Dictionary = dispatcher_script.apply_command(bbox_left, "bbox_right", config)
	var bbox_up: Dictionary = dispatcher_script.apply_command(state, "bbox_up", config)
	var bbox_down: Dictionary = dispatcher_script.apply_command(bbox_up, "bbox_down", config)
	_checks["bbox_commands_request_bbox_anchor"] = str(bbox_left.get("anchor_mode")) == "bbox" \
		and Vector2(bbox_right.get("bbox_center_px")).is_equal_approx(Vector2(436.0, 326.0)) \
		and Vector2(bbox_down.get("bbox_center_px")).is_equal_approx(Vector2(436.0, 326.0)) \
		and _effects(bbox_down) == [dispatcher_script.EFFECT_APPLY_BBOX_ANCHOR, dispatcher_script.EFFECT_APPLY_3DOF_ANCHOR]

	var bbox_depth_in: Dictionary = dispatcher_script.apply_command(state, "bbox_depth_in", config)
	var bbox_depth_out: Dictionary = dispatcher_script.apply_command(bbox_depth_in, "bbox_depth_out", config)
	_checks["bbox_depth_commands_clamp_and_request_bbox_anchor"] = str(bbox_depth_in.get("anchor_mode")) == "bbox" \
		and float(bbox_depth_out.get("bbox_depth_m")) == 1.35 \
		and _effects(bbox_depth_out).has(dispatcher_script.EFFECT_APPLY_BBOX_ANCHOR)

	var manual_to_bbox: Dictionary = dispatcher_script.apply_command(state, "toggle_bbox_mode", config)
	var bbox_to_manual: Dictionary = dispatcher_script.apply_command(manual_to_bbox, "toggle_bbox_mode", config)
	_checks["toggle_bbox_mode_requests_bbox_anchor_only_when_entering_bbox"] = str(manual_to_bbox.get("anchor_mode")) == "bbox" \
		and _effects(manual_to_bbox).has(dispatcher_script.EFFECT_APPLY_BBOX_ANCHOR) \
		and str(bbox_to_manual.get("anchor_mode")) == "manual" \
		and not _effects(bbox_to_manual).has(dispatcher_script.EFFECT_APPLY_BBOX_ANCHOR)

	var moved := state.duplicate()
	moved["anchor_yaw_deg"] = 12.0
	moved["anchor_pitch_deg"] = -6.0
	moved["anchor_depth_m"] = 2.0
	moved["anchor_mode"] = "bbox"
	moved["bbox_center_px"] = Vector2(10.0, 20.0)
	moved["bbox_size_px"] = Vector2(30.0, 40.0)
	moved["bbox_image_size"] = Vector2(100.0, 200.0)
	moved["bbox_depth_m"] = 3.0
	moved["bbox_angular_size_deg"] = Vector2(1.0, 2.0)
	moved["paused"] = true
	var reset: Dictionary = dispatcher_script.apply_command(moved, "r", config)
	_checks["reset_restores_defaults_and_requests_3dof"] = float(reset.get("anchor_yaw_deg")) == 0.0 \
		and float(reset.get("anchor_depth_m")) == 1.35 \
		and str(reset.get("anchor_mode")) == "manual" \
		and Vector2(reset.get("bbox_size_px")).is_equal_approx(Vector2(180.0, 240.0)) \
		and bool(reset.get("paused")) == false \
		and _effects(reset).has(dispatcher_script.EFFECT_HIDE_VST_BBOX_FRAME) \
		and _effects(reset).has(dispatcher_script.EFFECT_APPLY_3DOF_ANCHOR)

	var debug_free: Dictionary = dispatcher_script.apply_command(state, "debug_target_free", config)
	var debug_reset: Dictionary = dispatcher_script.apply_command(state, "debug_target_reset", config)
	_checks["debug_commands_return_side_effects"] = _effects(debug_free) == [dispatcher_script.EFFECT_DEBUG_TARGET_FREE, dispatcher_script.EFFECT_APPLY_3DOF_ANCHOR] \
		and _effects(debug_reset) == [dispatcher_script.EFFECT_DEBUG_TARGET_RESET, dispatcher_script.EFFECT_APPLY_3DOF_ANCHOR]

	var latch_reset: Dictionary = dispatcher_script.apply_command(state, "reset_world_anchor", config)
	_checks["reset_proxy_world_latch_returns_latch_effect"] = str(latch_reset.get("last_command")) == "reset_world_anchor" \
		and _effects(latch_reset) == [dispatcher_script.EFFECT_RESET_PROXY_WORLD_LATCHES]

	var unknown: Dictionary = dispatcher_script.apply_command(state, "unknown", config)
	_checks["unknown_command_only_tracks_last_command_and_3dof"] = str(unknown.get("last_command")) == "unknown" \
		and float(unknown.get("anchor_yaw_deg")) == 0.0 \
		and _effects(unknown) == [dispatcher_script.EFFECT_APPLY_3DOF_ANCHOR]

	return "-"


func _effects(state: Dictionary) -> Array:
	return Array(state.get("effects", []))


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
		"harness": "script_only_command_dispatcher_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_COMMAND_DISPATCHER_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("command_dispatcher_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
