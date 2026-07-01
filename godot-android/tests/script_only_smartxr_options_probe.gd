extends SceneTree

## Script-only runtime probe for SmartXROptions (M1, YAN-73).
##
## Runs in no-project mode like the other script-only probes (a project run
## would boot the full main scene, which never exits headless):
##   godot --headless --script <abs path to this file>
## with the options script injected via env:
##   SMARTXR_OPTIONS_SCRIPT            abs path to smartxr_options.gd
##   SMARTXR_OPTIONS_PROBE_STATUS_PATH abs path for the status JSON (optional)
##   SMARTXR_OPTIONS_PROBE_CONFIG_PATH abs path for the temp config file
##                                     (optional; defaults to user://)
##
## Verifies at runtime: default resolution, config-file override, env-var
## priority over the config file, and bool parsing. Exits 0 only if every
## check passed.

const DEFAULT_STATUS_RES := "user://smartxr_options_probe_status.json"

var _checks := {}
var _error := "-"
var _config_path := ""
var _exit_code := 1


func _initialize() -> void:
	var run_error := _run_checks()
	_remove_config_file()
	if run_error != "-":
		_error = run_error
	elif _all_passed():
		_exit_code = 0
	_write_status(_exit_code)


# Quit from the first main-loop iteration, matching the other script-only
# probes — quit() inside _initialize is not honored in script-only mode.
func _process(_delta: float) -> bool:
	quit(_exit_code)
	return true


func _run_checks() -> String:
	_clear_probe_env()

	var options_script_path := OS.get_environment("SMARTXR_OPTIONS_SCRIPT")
	if options_script_path.is_empty():
		return "missing_env:SMARTXR_OPTIONS_SCRIPT"
	var options_script = load(options_script_path)
	if options_script == null:
		return "load_failed:" + options_script_path
	_checks["options_script_loads"] = true

	_config_path = OS.get_environment("SMARTXR_OPTIONS_PROBE_CONFIG_PATH")
	if _config_path.is_empty():
		_config_path = options_script.CONFIG_RES

	# 1. Defaults only: no env, no config file.
	_remove_config_file()
	var options = options_script.load_options()
	_checks["default_string"] = (
		options.control_ws_url("ws://default:1/control") == "ws://default:1/control"
	)
	_checks["default_bool_true"] = options.proxy_targets_ws_enabled(true) == true
	_checks["default_bool_false"] = options.proxy_targets_ws_enabled(false) == false
	_checks["default_proxy_anchor_mode"] = options.proxy_targets_anchor_mode("dynamic") == "dynamic"
	_checks["default_proxy_head_z_mode"] = options.proxy_targets_head_z_mode("negative_z_forward") == "negative_z_forward"
	_checks["default_pose_trace_path"] = options.proxy_targets_pose_trace_path("") == ""
	_checks["default_card_offset_rule"] = _offset_rule_matches(
		options.proxy_targets_card_offset_rule(_default_card_offset_rule()),
		"depth_scaled_right_half_width",
		1.3,
		0.0,
		0.5,
		15.0,
		0.0
	)

	# 2. Config file overrides the default. The probe writes the config to the
	# same path SmartXROptions reads (CONFIG_RES unless overridden for tests).
	var config := {
		"control_ws_url": "ws://from-config:2/control",
		"proxy_targets_ws_url": "ws://from-config:2/proxy_targets",
		"proxy_targets_ws_enabled": false,
		"proxy_targets_anchor_mode": "world_latched",
		"proxy_targets_head_z_mode": "positive_z_forward",
		"proxy_targets_pose_trace_path": "user://pose_trace_config.jsonl",
		"proxy_targets_card_offset_rule": {
			"mode": "depth_scaled_right_angle",
			"depth_scale": 1.15,
			"depth_offset_m": 0.2,
			"right_angle_deg": 12.5,
			"right_width_fraction": -0.5,
			"up_m": 0.1,
		},
	}
	var file := FileAccess.open(_config_path, FileAccess.WRITE)
	if file == null:
		return "config_write_failed:" + _config_path
	file.store_string(JSON.stringify(config))
	file.close()
	options = options_script.load_options_from(_config_path)
	_checks["config_string"] = (
		options.control_ws_url("ws://default:1/control") == "ws://from-config:2/control"
	)
	_checks["config_bool"] = options.proxy_targets_ws_enabled(true) == false
	_checks["config_proxy_anchor_mode"] = options.proxy_targets_anchor_mode("dynamic") == "world_latched"
	_checks["config_proxy_head_z_mode"] = options.proxy_targets_head_z_mode("negative_z_forward") == "positive_z_forward"
	_checks["config_pose_trace_path"] = options.proxy_targets_pose_trace_path("") == "user://pose_trace_config.jsonl"
	_checks["config_card_offset_rule"] = _offset_rule_matches(
		options.proxy_targets_card_offset_rule(_default_card_offset_rule()),
		"depth_scaled_right_angle",
		1.15,
		0.2,
		-0.5,
		12.5,
		0.1
	)
	OS.set_environment("SMARTXR_OPTIONS_PATH", _config_path)
	options = options_script.load_options()
	_checks["env_options_path"] = (
		options.control_ws_url("ws://default:1/control") == "ws://from-config:2/control"
	)

	# 3. Env var beats the config file (resolution happens at call time).
	OS.set_environment("SMARTXR_CONTROL_WS_URL", "ws://from-env:3/control")
	OS.set_environment("PROXY_TARGETS_WS_URL", "ws://from-env:3/proxy_targets")
	OS.set_environment("SMARTXR_PROXY_TARGETS_WS_ENABLED", "on")
	OS.set_environment("SMARTXR_PROXY_TARGETS_ANCHOR_MODE", "dynamic")
	OS.set_environment("SMARTXR_PROXY_TARGETS_HEAD_Z_MODE", "negative_z_forward")
	OS.set_environment("SMARTXR_PROXY_TARGETS_POSE_TRACE_PATH", "user://pose_trace_env.jsonl")
	OS.set_environment("SMARTXR_PROXY_TARGETS_CARD_DEPTH_SCALE", "0.95")
	OS.set_environment("SMARTXR_PROXY_TARGETS_CARD_DEPTH_OFFSET_M", "-0.15")
	OS.set_environment("SMARTXR_PROXY_TARGETS_CARD_RIGHT_WIDTH_FRACTION", "0.25")
	OS.set_environment("SMARTXR_PROXY_TARGETS_CARD_RIGHT_ANGLE_DEG", "20.0")
	OS.set_environment("SMARTXR_PROXY_TARGETS_CARD_UP_M", "0.2")
	_checks["env_beats_config"] = (
		options.control_ws_url("ws://default:1/control") == "ws://from-env:3/control"
	)
	_checks["env_proxy_url"] = (
		options.proxy_targets_ws_url("ws://default:1/proxy_targets") == "ws://from-env:3/proxy_targets"
	)
	_checks["env_bool_on"] = options.proxy_targets_ws_enabled(false) == true
	_checks["env_proxy_anchor_mode"] = options.proxy_targets_anchor_mode("world_latched") == "dynamic"
	_checks["env_proxy_head_z_mode"] = options.proxy_targets_head_z_mode("positive_z_forward") == "negative_z_forward"
	_checks["env_pose_trace_path"] = options.proxy_targets_pose_trace_path("user://default_pose_trace.jsonl") == "user://pose_trace_env.jsonl"
	_checks["env_card_offset_rule"] = _offset_rule_matches(
		options.proxy_targets_card_offset_rule(_default_card_offset_rule()),
		"depth_scaled_right_angle",
		0.95,
		-0.15,
		0.25,
		20.0,
		0.2
	)
	OS.set_environment("SMARTXR_PROXY_TARGETS_WS_ENABLED", "definitely_not")
	_checks["env_bool_other_is_false"] = options.proxy_targets_ws_enabled(true) == false

	_clear_probe_env()
	return "-"


func _default_card_offset_rule() -> Dictionary:
	return {
		"mode": "depth_scaled_right_half_width",
		"offset_space": "world",
		"depth_scale": 1.3,
		"depth_offset_m": 0.0,
		"right_width_fraction": 0.5,
		"right_angle_deg": 15.0,
		"up_m": 0.0,
		"fallback": "hold_last_pose"
	}


func _offset_rule_matches(rule: Dictionary, expected_mode: String, depth_scale: float, depth_offset_m: float, right_width_fraction: float, right_angle_deg: float, up_m: float) -> bool:
	return (
		str(rule.get("mode", "")) == expected_mode
		and str(rule.get("offset_space", "")) == "world"
		and is_equal_approx(float(rule.get("depth_scale", -1.0)), depth_scale)
		and is_equal_approx(float(rule.get("depth_offset_m", -99.0)), depth_offset_m)
		and is_equal_approx(float(rule.get("right_width_fraction", -99.0)), right_width_fraction)
		and is_equal_approx(float(rule.get("right_angle_deg", -99.0)), right_angle_deg)
		and is_equal_approx(float(rule.get("up_m", -99.0)), up_m)
		and str(rule.get("fallback", "")) == "hold_last_pose"
	)


func _all_passed() -> bool:
	if _checks.is_empty():
		return false
	for key in _checks:
		if not _checks[key]:
			return false
	return true


func _clear_probe_env() -> void:
	OS.set_environment("SMARTXR_OPTIONS_PATH", "")
	OS.set_environment("SMARTXR_CONTROL_WS_URL", "")
	OS.set_environment("PROXY_TARGETS_WS_URL", "")
	OS.set_environment("SMARTXR_PROXY_TARGETS_WS_ENABLED", "")
	OS.set_environment("SMARTXR_PROXY_TARGETS_ANCHOR_MODE", "")
	OS.set_environment("SMARTXR_PROXY_TARGETS_HEAD_Z_MODE", "")
	OS.set_environment("SMARTXR_PROXY_TARGETS_POSE_TRACE_PATH", "")
	OS.set_environment("SMARTXR_PROXY_TARGETS_CARD_OFFSET_MODE", "")
	OS.set_environment("SMARTXR_PROXY_TARGETS_CARD_OFFSET_SPACE", "")
	OS.set_environment("SMARTXR_PROXY_TARGETS_CARD_DEPTH_SCALE", "")
	OS.set_environment("SMARTXR_PROXY_TARGETS_CARD_DEPTH_OFFSET_M", "")
	OS.set_environment("SMARTXR_PROXY_TARGETS_CARD_RIGHT_WIDTH_FRACTION", "")
	OS.set_environment("SMARTXR_PROXY_TARGETS_CARD_RIGHT_ANGLE_DEG", "")
	OS.set_environment("SMARTXR_PROXY_TARGETS_CARD_UP_M", "")
	OS.set_environment("SMARTXR_PROXY_TARGETS_CARD_FALLBACK", "")
	OS.set_environment("SMARTXR_VST_HORIZONTAL_FOV_DEG", "")
	OS.set_environment("SMARTXR_VST_VERTICAL_FOV_DEG", "")
	OS.set_environment("SMARTXR_VST_PRINCIPAL_POINT_X", "")
	OS.set_environment("SMARTXR_VST_PRINCIPAL_POINT_Y", "")
	OS.set_environment("SMARTXR_VST_FOCAL_LENGTH_X", "")
	OS.set_environment("SMARTXR_VST_FOCAL_LENGTH_Y", "")


func _remove_config_file() -> void:
	if _config_path.is_empty():
		return
	if FileAccess.file_exists(_config_path):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(_config_path))


func _write_status(exit_code: int) -> void:
	var failed := []
	for key in _checks:
		if not _checks[key]:
			failed.append(key)
	var status := {
		"harness": "script_only_smartxr_options_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_OPTIONS_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("smartxr_options_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
