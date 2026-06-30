extends SceneTree

## Script-only runtime probe for StatusHud (M3 step 1, YAN-74).
##
## Runs in no-project mode like the other script-only probes (a project run
## would boot the full main scene, which never exits headless):
##   godot --headless --script <abs path to this file>
## with the HUD script injected via env:
##   SMARTXR_STATUS_HUD_SCRIPT            abs path to status_hud.gd
##   SMARTXR_STATUS_HUD_PROBE_WORK_DIR    abs dir for the redirected status files
##   SMARTXR_STATUS_HUD_PROBE_STATUS_PATH abs path for the probe result JSON
##                                        (optional)
##
## Verifies at runtime: label construction/parenting, snapshot-driven label
## rendering, throttled status-file writes with the exact historical JSON
## keys/formatting, and sanitize_status_text. Exits 0 only if every check
## passed.

const DEFAULT_STATUS_RES := "user://status_hud_probe_status.json"

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


# Quit from the first main-loop iteration, matching the other script-only
# probes — quit() inside _initialize is not honored in script-only mode.
func _process(_delta: float) -> bool:
	quit(_exit_code)
	return true


func _run_checks() -> String:
	var hud_script_path := OS.get_environment("SMARTXR_STATUS_HUD_SCRIPT")
	if hud_script_path.is_empty():
		return "missing_env:SMARTXR_STATUS_HUD_SCRIPT"
	var hud_script = load(hud_script_path)
	if hud_script == null:
		return "load_failed:" + hud_script_path
	_checks["hud_script_loads"] = true

	var work_dir := OS.get_environment("SMARTXR_STATUS_HUD_PROBE_WORK_DIR")
	if work_dir.is_empty():
		return "missing_env:SMARTXR_STATUS_HUD_PROBE_WORK_DIR"

	var hud = hud_script.new()
	var parent := Node3D.new()

	# 1. Label construction and parenting.
	var label = hud.build_status_label(parent)
	_checks["label_is_label3d"] = label is Label3D
	_checks["label_named_mesh_card_status"] = label != null and str(label.name) == "MeshCardStatus"
	_checks["label_parented"] = label != null and label.get_parent() == parent

	# 2. Snapshot-driven label rendering.
	var snapshot := _make_snapshot()
	hud.update_status_label(snapshot, 0.0, true)
	var text: String = label.text
	_checks["label_anchor_header"] = text.contains("3DoF Anchor")
	_checks["label_ws_connected"] = text.contains("WS: connected")
	_checks["label_camera_pos"] = text.contains("Camera Pos xyz: 1.00 2.00 3.00")
	_checks["label_xr_origin_na"] = text.contains("XROrigin Pos xyz: n/a")
	_checks["label_proxy_line"] = text.contains("ProxyWS: connected")
	_checks["label_proxy_summary"] = text.contains("src=head right_eye fov=70.0x43.0 eye2head=true")
	_checks["label_vst_target_state"] = text.contains("target_state=tracked")
	_checks["label_vst_anchor_mode"] = text.contains("Anchor: raw-fov")

	# 3. Throttled status-file writes with the historical JSON shape.
	hud.proxy_targets_status_path = work_dir.path_join("proxy_targets_live_status.json")
	hud.passthrough_overlay_status_path = work_dir.path_join("passthrough_overlay_status.json")
	_remove_file(hud.proxy_targets_status_path)
	_remove_file(hud.passthrough_overlay_status_path)
	hud.write_status_files(snapshot, 0.1)
	_checks["throttle_skips_below_interval"] = not FileAccess.file_exists(hud.proxy_targets_status_path)
	hud.write_status_files(snapshot, 0.2)
	_checks["proxy_status_written"] = FileAccess.file_exists(hud.proxy_targets_status_path)
	_checks["overlay_status_written"] = FileAccess.file_exists(hud.passthrough_overlay_status_path)

	var proxy_status = _read_json(hud.proxy_targets_status_path)
	_checks["proxy_status_is_dict"] = typeof(proxy_status) == TYPE_DICTIONARY
	if typeof(proxy_status) == TYPE_DICTIONARY:
		_checks["proxy_status_ws_connected"] = proxy_status.get("ws_connected", false) == true
		_checks["proxy_status_position_formatted"] = str(proxy_status.get("last_proxy_position", "")) == "0.10 0.20 0.30"
		_checks["proxy_status_resolved_na"] = str(proxy_status.get("card_resolved_position", "")) == "n/a"
		_checks["proxy_status_node_position"] = str(proxy_status.get("card_node_position", "")) == "1.00 1.00 1.00"
		_checks["proxy_status_summary"] = str(proxy_status.get("source_coordinate_summary", "")) == "head right_eye fov=70.0x43.0 eye2head=true"
		_checks["proxy_status_last_command"] = str(proxy_status.get("last_command", "")) == "probe_cmd"
		_checks["proxy_status_sequence"] = int(proxy_status.get("sequence", -999)) == 7
		_checks["proxy_status_runtime_local_position"] = str(proxy_status.get("proxy_runtime_local_position", "")) == "0.40 0.50 -0.60"
		_checks["proxy_status_head_z_mode"] = str(proxy_status.get("proxy_head_z_mode", "")) == "positive_z_forward"

	var overlay_status = _read_json(hud.passthrough_overlay_status_path)
	_checks["overlay_status_is_dict"] = typeof(overlay_status) == TYPE_DICTIONARY
	if typeof(overlay_status) == TYPE_DICTIONARY:
		_checks["overlay_status_ready"] = str(overlay_status.get("status", "")) == "ready"
		_checks["overlay_layer_position"] = str(overlay_status.get("layer_position", "")) == "0.00 0.00 -1.50"
		_checks["overlay_transparent_bg"] = overlay_status.get("viewport_transparent_bg", false) == true

	# 4. sanitize_status_text (static helper used at packet-receive time).
	var sanitized: String = hud_script.sanitize_status_text("a\nb\r" + "x".repeat(200))
	_checks["sanitize_escapes_newlines"] = sanitized.begins_with("a\\nb\\r")
	_checks["sanitize_truncates_to_160"] = sanitized.length() == 160

	# 5. First-frame snapshots can contain null source_coordinate before a
	# live packet has supplied the full metadata. The HUD must render and write
	# status instead of tripping GDScript's typed argument checks.
	var null_source_snapshot := _make_snapshot()
	null_source_snapshot["proxy_targets"]["source_coordinate"] = null
	hud.update_status_label(null_source_snapshot, 0.0, true)
	_checks["null_source_coordinate_label_summary"] = label.text.contains("src=-")
	hud.write_status_files(null_source_snapshot, 0.3)
	var null_source_proxy_status = _read_json(hud.proxy_targets_status_path)
	_checks["null_source_coordinate_status_summary"] = (
		typeof(null_source_proxy_status) == TYPE_DICTIONARY
		and str(null_source_proxy_status.get("source_coordinate_summary", "")) == "-"
	)

	parent.free()
	hud.free()
	return "-"


func _make_snapshot() -> Dictionary:
	return {
		"ws_connected": true,
		"last_command": "probe_cmd",
		"anchor_mode": "target",
		"camera_position": Vector3(1.0, 2.0, 3.0),
		"camera_rotation_degrees": Vector3(4.0, 5.0, 6.0),
		"xr_origin_position": null,
		"bbox_center_px": Vector2(436.0, 326.0),
		"bbox_size_px": Vector2(180.0, 240.0),
		"bbox_depth_m": 1.35,
		"anchor_yaw_deg": 1.0,
		"anchor_pitch_deg": 2.0,
		"anchor_depth_m": 1.35,
		"bbox_angular_size_deg": Vector2(10.0, 12.0),
		"card_rotation_degrees": Vector3.ZERO,
		"speed_deg_per_second": 0.0,
		"paused": false,
		"corners": {
			"TL": Vector3(-0.36, 0.54, -1.35),
			"TR": Vector3(0.36, 0.54, -1.35),
			"BL": Vector3(-0.36, -0.54, -1.35),
			"BR": Vector3(0.36, -0.54, -1.35),
		},
		"viewport_use_xr": false,
		"viewport_transparent_bg": true,
		"xr": {
			"interface_found": false,
			"initialize_ok": false,
			"active": false,
			"init_error": "probe: no XR",
		},
		"vst": {
			"class_registered": false,
			"init_ok": false,
			"frames": 0,
			"box_count": 0,
			"latency_ms": -1.0,
			"image_size": Vector2.ZERO,
			"first_box": PackedFloat32Array(),
			"target_state": "tracked",
			"last_error": "-",
			"uses_eye_to_head_anchor": false,
			"eye_to_head_status": "eye2head: not queried",
			"calibration_status": "cal: not queried",
		},
		"proxy_targets": {
			"ws_connected": true,
			"ws_subscribed": true,
			"ws_url": "ws://127.0.0.1:8766/proxy_targets",
			"attachments": 1,
			"card_target_id": "probe_target",
			"proxy_target_count": 1,
			"proxy_target_ids": ["probe_target"],
			"last_position": Vector3(0.1, 0.2, 0.3),
			"card_resolved_position": null,
			"card_node_position": Vector3(1.0, 1.0, 1.0),
			"card_apply_count": 3,
			"packets": 5,
			"parsed": 4,
			"live": 4,
			"sequence": 7,
			"packet_bytes": 256,
			"packet_preview": "{\\\"type\\\": \\\"proxy_targets\\\"}",
			"message_type": "proxy_targets",
			"source_coordinate": {
				"coordinate_space": "head",
				"anchor": "right_eye",
				"source_frame": {
					"horizontal_fov_deg": 70.0,
					"vertical_fov_deg": 43.0,
				},
				"uses_right_eye_to_head": true,
			},
			"world_from_head_applied": true,
			"local_position": Vector3(0.4, 0.5, 0.6),
			"runtime_local_position": Vector3(0.4, 0.5, -0.6),
			"world_position": Vector3(0.7, 0.8, 0.9),
			"head_z_mode": "positive_z_forward",
			"error": "-",
		},
		"passthrough_overlay": {
			"enabled": true,
			"requested_blend_mode": "alpha_blend",
			"blend_request_ok": true,
			"layer_created": true,
			"layer_visible": true,
			"layer_alpha_blend": true,
			"layer_position": Vector3(0.0, 0.0, -1.5),
		},
	}


func _read_json(path: String):
	if not FileAccess.file_exists(path):
		return null
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return null
	var text := file.get_as_text()
	file.close()
	return JSON.parse_string(text)


func _remove_file(path: String) -> void:
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(path))


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
		"harness": "script_only_status_hud_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_STATUS_HUD_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("status_hud_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
