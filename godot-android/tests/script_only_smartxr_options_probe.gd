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

	# 2. Config file overrides the default. The probe writes the config to the
	# same path SmartXROptions reads (CONFIG_RES unless overridden for tests).
	var config := {
		"control_ws_url": "ws://from-config:2/control",
		"proxy_targets_ws_url": "ws://from-config:2/proxy_targets",
		"proxy_targets_ws_enabled": false,
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

	# 3. Env var beats the config file (resolution happens at call time).
	OS.set_environment("SMARTXR_CONTROL_WS_URL", "ws://from-env:3/control")
	OS.set_environment("PROXY_TARGETS_WS_URL", "ws://from-env:3/proxy_targets")
	OS.set_environment("SMARTXR_PROXY_TARGETS_WS_ENABLED", "on")
	_checks["env_beats_config"] = (
		options.control_ws_url("ws://default:1/control") == "ws://from-env:3/control"
	)
	_checks["env_proxy_url"] = (
		options.proxy_targets_ws_url("ws://default:1/proxy_targets") == "ws://from-env:3/proxy_targets"
	)
	_checks["env_bool_on"] = options.proxy_targets_ws_enabled(false) == true
	OS.set_environment("SMARTXR_PROXY_TARGETS_WS_ENABLED", "definitely_not")
	_checks["env_bool_other_is_false"] = options.proxy_targets_ws_enabled(true) == false

	_clear_probe_env()
	return "-"


func _all_passed() -> bool:
	if _checks.is_empty():
		return false
	for key in _checks:
		if not _checks[key]:
			return false
	return true


func _clear_probe_env() -> void:
	OS.set_environment("SMARTXR_CONTROL_WS_URL", "")
	OS.set_environment("PROXY_TARGETS_WS_URL", "")
	OS.set_environment("SMARTXR_PROXY_TARGETS_WS_ENABLED", "")
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
