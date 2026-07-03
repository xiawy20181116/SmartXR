extends RefCounted
class_name SmartXROptions

## Centralized runtime configuration for SmartXR (M1 of the encapsulation plan).
##
## Resolution order for every setting, highest priority first:
##   1. environment variable (e.g. set per adb session or test harness)
##   2. user://smartxr_options.json config file on the device
##   3. the default value passed by the caller (usually a script const)
##
## Keep this class dependency-free: it must stay loadable in script-only
## probes and on a vanilla GXR SDK.

const CONFIG_RES := "user://smartxr_options.json"

## Environment variable names. PROXY_TARGETS_WS_URL predates this class and
## keeps its historical name; new settings use the SMARTXR_ prefix.
const ENV_OPTIONS_PATH := "SMARTXR_OPTIONS_PATH"
const ENV_CONTROL_WS_URL := "SMARTXR_CONTROL_WS_URL"
const ENV_PROXY_TARGETS_WS_URL := "PROXY_TARGETS_WS_URL"
const ENV_PROXY_TARGETS_WS_ENABLED := "SMARTXR_PROXY_TARGETS_WS_ENABLED"
const ENV_PROXY_TARGETS_ANCHOR_MODE := "SMARTXR_PROXY_TARGETS_ANCHOR_MODE"
const ENV_PROXY_TARGETS_HEAD_Z_MODE := "SMARTXR_PROXY_TARGETS_HEAD_Z_MODE"
const ENV_PROXY_TARGETS_POSE_TRACE_PATH := "SMARTXR_PROXY_TARGETS_POSE_TRACE_PATH"
const ENV_XR_POSE_TRACE_PATH := "SMARTXR_XR_POSE_TRACE_PATH"
const ENV_PROXY_TARGETS_CARD_OFFSET_MODE := "SMARTXR_PROXY_TARGETS_CARD_OFFSET_MODE"
const ENV_PROXY_TARGETS_CARD_OFFSET_SPACE := "SMARTXR_PROXY_TARGETS_CARD_OFFSET_SPACE"
const ENV_PROXY_TARGETS_CARD_DEPTH_SCALE := "SMARTXR_PROXY_TARGETS_CARD_DEPTH_SCALE"
const ENV_PROXY_TARGETS_CARD_DEPTH_OFFSET_M := "SMARTXR_PROXY_TARGETS_CARD_DEPTH_OFFSET_M"
const ENV_PROXY_TARGETS_CARD_RIGHT_WIDTH_FRACTION := "SMARTXR_PROXY_TARGETS_CARD_RIGHT_WIDTH_FRACTION"
const ENV_PROXY_TARGETS_CARD_RIGHT_ANGLE_DEG := "SMARTXR_PROXY_TARGETS_CARD_RIGHT_ANGLE_DEG"
const ENV_PROXY_TARGETS_CARD_UP_M := "SMARTXR_PROXY_TARGETS_CARD_UP_M"
const ENV_PROXY_TARGETS_CARD_FALLBACK := "SMARTXR_PROXY_TARGETS_CARD_FALLBACK"
const ENV_PROXY_TARGETS_CARD_REACQUIRE_ENABLED := "SMARTXR_PROXY_TARGETS_CARD_REACQUIRE_ENABLED"
const ENV_PROXY_TARGETS_CARD_REACQUIRE_SMOOTHING_MS := "SMARTXR_PROXY_TARGETS_CARD_REACQUIRE_SMOOTHING_MS"
const ENV_PROXY_TARGETS_CARD_REACQUIRE_MAX_STEP_M := "SMARTXR_PROXY_TARGETS_CARD_REACQUIRE_MAX_STEP_M"
const ENV_PROXY_TARGETS_CARD_REACQUIRE_SETTLE_EPSILON_M := "SMARTXR_PROXY_TARGETS_CARD_REACQUIRE_SETTLE_EPSILON_M"
const ENV_VST_HORIZONTAL_FOV_DEG := "SMARTXR_VST_HORIZONTAL_FOV_DEG"
const ENV_VST_VERTICAL_FOV_DEG := "SMARTXR_VST_VERTICAL_FOV_DEG"
const ENV_VST_PRINCIPAL_POINT_X := "SMARTXR_VST_PRINCIPAL_POINT_X"
const ENV_VST_PRINCIPAL_POINT_Y := "SMARTXR_VST_PRINCIPAL_POINT_Y"
const ENV_VST_FOCAL_LENGTH_X := "SMARTXR_VST_FOCAL_LENGTH_X"
const ENV_VST_FOCAL_LENGTH_Y := "SMARTXR_VST_FOCAL_LENGTH_Y"
const ENV_STATUS_HUD_VISIBLE := "SMARTXR_STATUS_HUD_VISIBLE"

var _config := {}
var _config_loaded := false


# Untyped returns and bare new() on purpose: naming SmartXROptions inside its
# own file breaks compilation in no-project mode (script-only probes), where
# class_name global registration does not happen.
static func load_options():
	var config_path := OS.get_environment(ENV_OPTIONS_PATH).strip_edges()
	if config_path.is_empty():
		config_path = CONFIG_RES
	return load_options_from(config_path)


## Same as load_options() but reading the config from an explicit path.
## Used by the script-only runtime probe; production code uses CONFIG_RES.
static func load_options_from(config_path: String):
	var options = new()
	options._load_config_file(config_path)
	return options


func _load_config_file(config_path: String = CONFIG_RES) -> void:
	_config_loaded = true
	_config = {}
	if not FileAccess.file_exists(config_path):
		return
	var file := FileAccess.open(config_path, FileAccess.READ)
	if file == null:
		return
	var text := file.get_as_text()
	file.close()
	var parsed = JSON.parse_string(text)
	if typeof(parsed) == TYPE_DICTIONARY:
		_config = parsed
	else:
		push_warning("SmartXROptions: %s is not a JSON object; ignoring" % config_path)


func resolve_string(config_key: String, env_name: String, default_value: String) -> String:
	var env_value := OS.get_environment(env_name).strip_edges()
	if not env_value.is_empty():
		return env_value
	if _config.has(config_key) and typeof(_config[config_key]) == TYPE_STRING:
		var config_value := str(_config[config_key]).strip_edges()
		if not config_value.is_empty():
			return config_value
	return default_value


func resolve_bool(config_key: String, env_name: String, default_value: bool) -> bool:
	var env_value := OS.get_environment(env_name).strip_edges().to_lower()
	if not env_value.is_empty():
		return ["1", "true", "yes", "on"].has(env_value)
	if _config.has(config_key) and typeof(_config[config_key]) == TYPE_BOOL:
		return _config[config_key]
	return default_value


func resolve_float(config_key: String, env_name: String, default_value: float) -> float:
	var env_value := OS.get_environment(env_name).strip_edges()
	if not env_value.is_empty():
		return float(env_value)
	if _config.has(config_key) and (typeof(_config[config_key]) == TYPE_FLOAT or typeof(_config[config_key]) == TYPE_INT):
		return float(_config[config_key])
	return default_value


## Control channel (keyboard ws_control server). Overridable so the URL is
## no longer pinned to one development machine's LAN address.
func control_ws_url(default_url: String) -> String:
	return resolve_string("control_ws_url", ENV_CONTROL_WS_URL, default_url)


## proxy_targets live stream endpoint.
func proxy_targets_ws_url(default_url: String) -> String:
	return resolve_string("proxy_targets_ws_url", ENV_PROXY_TARGETS_WS_URL, default_url)


## Whether the proxy_targets live WebSocket consumer should run.
func proxy_targets_ws_enabled(default_enabled: bool) -> bool:
	return resolve_bool("proxy_targets_ws_enabled", ENV_PROXY_TARGETS_WS_ENABLED, default_enabled)


## proxy_targets card anchor comparison mode: dynamic or world_latched.
func proxy_targets_anchor_mode(default_mode: String) -> String:
	return resolve_string("proxy_targets_anchor_mode", ENV_PROXY_TARGETS_ANCHOR_MODE, default_mode)


## proxy_targets head-space Z convention comparison mode.
func proxy_targets_head_z_mode(default_mode: String) -> String:
	return resolve_string("proxy_targets_head_z_mode", ENV_PROXY_TARGETS_HEAD_Z_MODE, default_mode)


## Per-frame Godot pose trace JSONL path. Empty means disabled.
func proxy_targets_pose_trace_path(default_path: String) -> String:
	return resolve_string("proxy_targets_pose_trace_path", ENV_PROXY_TARGETS_POSE_TRACE_PATH, default_path)


## High-frequency XR pose trace JSONL path. Empty means disabled.
func xr_pose_trace_path(default_path: String) -> String:
	return resolve_string("xr_pose_trace_path", ENV_XR_POSE_TRACE_PATH, default_path)


## proxy_targets card offset rule used when the card binding omits one.
func proxy_targets_card_offset_rule(default_rule: Dictionary) -> Dictionary:
	var rule := default_rule.duplicate(true)
	var nested = _config.get("proxy_targets_card_offset_rule", {})
	if typeof(nested) == TYPE_DICTIONARY:
		for key in nested.keys():
			rule[key] = nested[key]
	rule["mode"] = resolve_string("proxy_targets_card_offset_mode", ENV_PROXY_TARGETS_CARD_OFFSET_MODE, str(rule.get("mode", "depth_scaled_right_half_width")))
	rule["offset_space"] = resolve_string("proxy_targets_card_offset_space", ENV_PROXY_TARGETS_CARD_OFFSET_SPACE, str(rule.get("offset_space", "world")))
	rule["depth_scale"] = resolve_float("proxy_targets_card_depth_scale", ENV_PROXY_TARGETS_CARD_DEPTH_SCALE, float(rule.get("depth_scale", 1.0)))
	rule["depth_offset_m"] = resolve_float("proxy_targets_card_depth_offset_m", ENV_PROXY_TARGETS_CARD_DEPTH_OFFSET_M, float(rule.get("depth_offset_m", 0.0)))
	rule["right_width_fraction"] = resolve_float("proxy_targets_card_right_width_fraction", ENV_PROXY_TARGETS_CARD_RIGHT_WIDTH_FRACTION, float(rule.get("right_width_fraction", 0.5)))
	rule["right_angle_deg"] = resolve_float("proxy_targets_card_right_angle_deg", ENV_PROXY_TARGETS_CARD_RIGHT_ANGLE_DEG, float(rule.get("right_angle_deg", 15.0)))
	rule["up_m"] = resolve_float("proxy_targets_card_up_m", ENV_PROXY_TARGETS_CARD_UP_M, float(rule.get("up_m", 0.0)))
	rule["fallback"] = resolve_string("proxy_targets_card_fallback", ENV_PROXY_TARGETS_CARD_FALLBACK, str(rule.get("fallback", "hold_last_pose")))
	return rule


## proxy_targets card dynamic_held -> dynamic re-acquire smoothing/clamp rule.
func proxy_targets_card_reacquire_rule(default_rule: Dictionary) -> Dictionary:
	var rule := default_rule.duplicate(true)
	var nested = _config.get("proxy_targets_card_reacquire_rule", {})
	if typeof(nested) == TYPE_DICTIONARY:
		for key in nested.keys():
			rule[key] = nested[key]
	rule["enabled"] = resolve_bool("proxy_targets_card_reacquire_enabled", ENV_PROXY_TARGETS_CARD_REACQUIRE_ENABLED, bool(rule.get("enabled", false)))
	rule["smoothing_ms"] = resolve_float("proxy_targets_card_reacquire_smoothing_ms", ENV_PROXY_TARGETS_CARD_REACQUIRE_SMOOTHING_MS, float(rule.get("smoothing_ms", 250.0)))
	rule["max_step_m"] = resolve_float("proxy_targets_card_reacquire_max_step_m", ENV_PROXY_TARGETS_CARD_REACQUIRE_MAX_STEP_M, float(rule.get("max_step_m", 0.2)))
	rule["settle_epsilon_m"] = resolve_float("proxy_targets_card_reacquire_settle_epsilon_m", ENV_PROXY_TARGETS_CARD_REACQUIRE_SETTLE_EPSILON_M, float(rule.get("settle_epsilon_m", 0.03)))
	return rule


## Whether the in-headset diagnostic Label3D is visible.
func status_hud_visible(default_visible: bool) -> bool:
	return resolve_bool("status_hud_visible", ENV_STATUS_HUD_VISIBLE, default_visible)


## Right-eye VST camera calibration for bbox->head projection.
func vst_camera_calibration(default_hfov_deg: float, default_vfov_deg: float) -> Dictionary:
	return {
		"horizontal_fov_deg": resolve_float("vst_horizontal_fov_deg", ENV_VST_HORIZONTAL_FOV_DEG, default_hfov_deg),
		"vertical_fov_deg": resolve_float("vst_vertical_fov_deg", ENV_VST_VERTICAL_FOV_DEG, default_vfov_deg),
		"principal_point_px": Vector2(
			resolve_float("vst_principal_point_x", ENV_VST_PRINCIPAL_POINT_X, -1.0),
			resolve_float("vst_principal_point_y", ENV_VST_PRINCIPAL_POINT_Y, -1.0)
		),
		"focal_length_px": Vector2(
			resolve_float("vst_focal_length_x", ENV_VST_FOCAL_LENGTH_X, -1.0),
			resolve_float("vst_focal_length_y", ENV_VST_FOCAL_LENGTH_Y, -1.0)
		),
	}
