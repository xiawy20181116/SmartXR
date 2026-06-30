extends SceneTree

## Script-only runtime probe for status_snapshot_composer.gd.
##
## Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with:
##   SMARTXR_STATUS_SNAPSHOT_COMPOSER_SCRIPT            abs path to status_snapshot_composer.gd
##   SMARTXR_STATUS_SNAPSHOT_COMPOSER_PROBE_STATUS_PATH abs path for result JSON (optional)

const DEFAULT_STATUS_RES := "user://status_snapshot_composer_probe_status.json"

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
	var script_path := OS.get_environment("SMARTXR_STATUS_SNAPSHOT_COMPOSER_SCRIPT")
	if script_path.is_empty():
		return "missing_env:SMARTXR_STATUS_SNAPSHOT_COMPOSER_SCRIPT"
	var composer_script = load(script_path)
	if composer_script == null:
		return "load_failed:" + script_path
	_checks["composer_script_loads"] = true

	var composer = composer_script.new()
	var capture_snapshot := {
		"enabled": true,
		"active": false,
		"frames": 7,
		"last_error": "probe_capture",
	}
	var vst_snapshot: Dictionary = composer.build_vst_status_snapshot(capture_snapshot, "tracked")
	_checks["vst_copies_capture_values"] = vst_snapshot.get("frames") == 7 and vst_snapshot.get("last_error") == "probe_capture"
	_checks["vst_adds_target_state"] = vst_snapshot.get("target_state") == "tracked"
	_checks["vst_does_not_mutate_input"] = not capture_snapshot.has("target_state")

	var xr_snapshot: Dictionary = composer.build_xr_status_snapshot(true, false, true, "probe_xr")
	_checks["xr_fragment_matches_card_keys"] = xr_snapshot == {
		"interface_found": true,
		"initialize_ok": false,
		"active": true,
		"init_error": "probe_xr",
	}

	var proxy_snapshot: Dictionary = composer.build_proxy_targets_status_snapshot({
		"ws_connected": true,
		"ws_subscribed": false,
		"ws_url": "ws://probe",
		"attachments": 2,
		"card_target_id": "card_a",
		"proxy_target_count": 3,
		"proxy_target_ids": ["card_a", "card_b"],
		"last_position": Vector3(1.0, 2.0, 3.0),
		"card_resolved_position": Vector3(4.0, 5.0, 6.0),
		"card_node_position": Vector3(7.0, 8.0, 9.0),
		"card_apply_count": 11,
		"packets": 13,
		"parsed": 17,
		"live": 19,
		"sequence": 23,
		"packet_bytes": 29,
		"packet_preview": "packet",
		"message_type": "targets",
		"source_coordinate": {"space": "head"},
		"world_from_head_applied": true,
		"local_position": Vector3(0.1, 0.2, 0.3),
		"runtime_local_position": Vector3(0.1, 0.2, -0.3),
		"world_position": Vector3(0.4, 0.5, 0.6),
		"head_z_mode": "positive_z_forward",
		"anchor_mode": "world_latched",
		"world_latched": true,
		"world_latch_state": "latched_fresh",
		"error": "-",
	})
	_checks["proxy_fragment_preserves_ordered_contract"] = proxy_snapshot.keys() == [
		"ws_connected",
		"ws_subscribed",
		"ws_url",
		"attachments",
		"card_target_id",
		"proxy_target_count",
		"proxy_target_ids",
		"last_position",
		"card_resolved_position",
		"card_node_position",
		"card_apply_count",
		"packets",
		"parsed",
		"live",
		"sequence",
		"packet_bytes",
		"packet_preview",
		"message_type",
		"source_coordinate",
		"world_from_head_applied",
		"local_position",
		"runtime_local_position",
		"world_position",
		"head_z_mode",
		"anchor_mode",
		"world_latched",
		"world_latch_state",
		"error",
	]
	_checks["proxy_fragment_uses_values"] = proxy_snapshot.get("ws_url") == "ws://probe" and proxy_snapshot.get("sequence") == 23

	var overlay_snapshot: Dictionary = composer.build_passthrough_overlay_status_snapshot({
		"enabled": true,
		"requested_blend_mode": "alpha_blend",
		"blend_request_ok": true,
		"layer_created": true,
		"layer_visible": false,
		"layer_alpha_blend": true,
		"layer_position": Vector3(0.0, 0.1, -1.5),
	})
	_checks["overlay_fragment_matches_card_keys"] = overlay_snapshot == {
		"enabled": true,
		"requested_blend_mode": "alpha_blend",
		"blend_request_ok": true,
		"layer_created": true,
		"layer_visible": false,
		"layer_alpha_blend": true,
		"layer_position": Vector3(0.0, 0.1, -1.5),
	}

	var full_snapshot: Dictionary = composer.build_status_snapshot({
		"ws_connected": true,
		"last_command": "probe_cmd",
		"anchor_mode": "target",
		"camera_position": Vector3(1.0, 0.0, 0.0),
		"camera_rotation_degrees": Vector3(0.0, 10.0, 0.0),
		"xr_origin_position": Vector3(0.0, 1.0, 0.0),
		"bbox_center_px": Vector2(436.0, 326.0),
		"bbox_size_px": Vector2(180.0, 240.0),
		"bbox_depth_m": 1.35,
		"anchor_yaw_deg": -12.0,
		"anchor_pitch_deg": 4.0,
		"anchor_depth_m": 1.5,
		"bbox_angular_size_deg": Vector2(10.0, 12.0),
		"card_rotation_degrees": Vector3(0.0, -12.0, 0.0),
		"speed_deg_per_second": 3.0,
		"paused": false,
		"corners": {"TL": Vector3(-1.0, 1.0, -1.5)},
		"viewport_use_xr": true,
		"viewport_transparent_bg": true,
		"xr": xr_snapshot,
		"vst": vst_snapshot,
		"proxy_targets": proxy_snapshot,
		"passthrough_overlay": overlay_snapshot,
	})
	_checks["full_snapshot_preserves_top_level_order"] = full_snapshot.keys() == [
		"ws_connected",
		"last_command",
		"anchor_mode",
		"camera_position",
		"camera_rotation_degrees",
		"xr_origin_position",
		"bbox_center_px",
		"bbox_size_px",
		"bbox_depth_m",
		"anchor_yaw_deg",
		"anchor_pitch_deg",
		"anchor_depth_m",
		"bbox_angular_size_deg",
		"card_rotation_degrees",
		"speed_deg_per_second",
		"paused",
		"corners",
		"viewport_use_xr",
		"viewport_transparent_bg",
		"xr",
		"vst",
		"proxy_targets",
		"passthrough_overlay",
	]
	_checks["full_snapshot_uses_nested_fragments"] = full_snapshot.get("xr") == xr_snapshot and full_snapshot.get("vst") == vst_snapshot
	_checks["full_snapshot_uses_top_level_values"] = full_snapshot.get("last_command") == "probe_cmd" and full_snapshot.get("bbox_depth_m") == 1.35
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
		"harness": "script_only_status_snapshot_composer_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_STATUS_SNAPSHOT_COMPOSER_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("status_snapshot_composer_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
