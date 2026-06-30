extends Node
class_name StatusHud

## Status HUD + diagnostics-file subsystem (M3 step 1 of the YAN-73
## encapsulation roadmap, extracted from AndroidMovingCard.gd).
##
## AndroidMovingCard assembles a status snapshot Dictionary per frame and
## passes it in; this node renders the Label3D and writes the user:// status
## files (proxy_targets_live_status.json, passthrough_overlay_status.json).
## It owns no gameplay state and resolves no other nodes, so a script-only
## probe can exercise it headless
## (godot-android/tests/script_only_status_hud_probe.gd).
##
## Keep this script loadable in no-project mode: never reference its own
## class_name inside this file (global class registration does not happen in
## script-only probes).

const PROXY_TARGETS_STATUS_RES := "user://proxy_targets_live_status.json"
const PASSTHROUGH_OVERLAY_STATUS_RES := "user://passthrough_overlay_status.json"
const STATUS_FILE_WRITE_INTERVAL_SECONDS := 0.25
const STATUS_LABEL_UPDATE_INTERVAL_SECONDS := 0.25

## Status file paths are vars (defaulting to the historical user:// consts) so
## the script-only probe can redirect writes to a temp directory.
var proxy_targets_status_path: String = PROXY_TARGETS_STATUS_RES
var passthrough_overlay_status_path: String = PASSTHROUGH_OVERLAY_STATUS_RES

var _status_label: Label3D = null
var _status_label_update_elapsed := 0.0
var _proxy_targets_status_write_elapsed := 0.0
var _passthrough_overlay_status_write_elapsed := 0.0


## Truncated single-line preview used for packet diagnostics in the status
## file. Static so the card can sanitize at packet-receive time without going
## through the per-frame snapshot.
static func sanitize_status_text(value: String) -> String:
	return value.replace("\r", "\\r").replace("\n", "\\n").substr(0, 160)


func build_status_label(parent: Node3D) -> Label3D:
	_status_label = Label3D.new()
	_status_label.name = "MeshCardStatus"
	_status_label.font_size = 22
	_status_label.pixel_size = 0.0025
	_status_label.outline_size = 8
	_status_label.no_depth_test = true
	_status_label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	_status_label.modulate = Color(0.72, 0.95, 1.0, 1.0)
	_status_label.position = Vector3(0.0, -0.72, 0.03)
	parent.add_child(_status_label)
	return _status_label


func update_status_label(snapshot: Dictionary, delta: float = 0.0, force: bool = false) -> void:
	if _status_label == null:
		return
	if not _status_label.visible:
		return
	_status_label_update_elapsed += delta
	if not force and _status_label_update_elapsed < STATUS_LABEL_UPDATE_INTERVAL_SECONDS:
		return
	_status_label_update_elapsed = 0.0
	var corners: Dictionary = snapshot.get("corners", {})
	var tl: Vector3 = corners.get("TL", Vector3.ZERO)
	var tr: Vector3 = corners.get("TR", Vector3.ZERO)
	var bl: Vector3 = corners.get("BL", Vector3.ZERO)
	var br: Vector3 = corners.get("BR", Vector3.ZERO)
	var card_rotation: Vector3 = snapshot.get("card_rotation_degrees", Vector3.ZERO)
	var bbox_center: Vector2 = snapshot.get("bbox_center_px", Vector2.ZERO)
	var bbox_size: Vector2 = snapshot.get("bbox_size_px", Vector2.ZERO)
	var angular_size: Vector2 = snapshot.get("bbox_angular_size_deg", Vector2.ZERO)
	var xr_line := _format_xr_status_line(snapshot)
	var vst_line := _format_vst_status_line(snapshot.get("vst", {}))
	var proxy_targets_line := _format_proxy_targets_status_line(snapshot.get("proxy_targets", {}))
	var next_text := "3DoF Anchor\nWS: %s  Cmd: %s  Face: 3DoF  Mode: %s\nCamera Pos xyz: %s\nCamera Rot xyz: %s\nXROrigin Pos xyz: %s\nBBox cx/cy/w/h: %.0f %.0f %.0f %.0f  Depth: %.2f\nYaw/Pitch/Depth: %.1f %.1f %.2f  Angular W/H: %.1f %.1f  Rot: %.1f %.1f %.1f\nSpeed: %.1f deg/s  Paused: %s\nTL %.2f %.2f %.2f  TR %.2f %.2f %.2f\nBL %.2f %.2f %.2f  BR %.2f %.2f %.2f\n%s\n%s\n%s" % [
		"connected" if _truthy(snapshot.get("ws_connected", false)) else "waiting",
		str(snapshot.get("last_command", "none")),
		str(snapshot.get("anchor_mode", "manual")),
		_format_vec3_or_na(snapshot.get("camera_position")),
		_format_vec3_or_na(snapshot.get("camera_rotation_degrees")),
		_format_vec3_or_na(snapshot.get("xr_origin_position")),
		bbox_center.x,
		bbox_center.y,
		bbox_size.x,
		bbox_size.y,
		_number_value(snapshot.get("bbox_depth_m", 0.0)),
		_number_value(snapshot.get("anchor_yaw_deg", 0.0)),
		_number_value(snapshot.get("anchor_pitch_deg", 0.0)),
		_number_value(snapshot.get("anchor_depth_m", 0.0)),
		angular_size.x,
		angular_size.y,
		card_rotation.x,
		card_rotation.y,
		card_rotation.z,
		_number_value(snapshot.get("speed_deg_per_second", 0.0)),
		str(_truthy(snapshot.get("paused", false))),
		tl.x,
		tl.y,
		tl.z,
		tr.x,
		tr.y,
		tr.z,
		bl.x,
		bl.y,
		bl.z,
		br.x,
		br.y,
		br.z,
		proxy_targets_line,
		xr_line,
		vst_line,
	]
	if next_text != _status_label.text:
		_status_label.text = next_text


func write_status_files(snapshot: Dictionary, delta: float) -> void:
	_write_proxy_targets_status_file(snapshot, delta)
	_write_passthrough_overlay_status_file(snapshot, delta)


func _write_proxy_targets_status_file(snapshot: Dictionary, delta: float) -> void:
	_proxy_targets_status_write_elapsed += delta
	if _proxy_targets_status_write_elapsed < STATUS_FILE_WRITE_INTERVAL_SECONDS:
		return
	_proxy_targets_status_write_elapsed = 0.0
	var proxy: Dictionary = snapshot.get("proxy_targets", {})
	var status := {
		"ws_connected": _truthy(proxy.get("ws_connected", false)),
		"ws_subscribed": _truthy(proxy.get("ws_subscribed", false)),
		"ws_url": str(proxy.get("ws_url", "")),
		"anchor_mode": str(snapshot.get("anchor_mode", "manual")),
		"attachments": _integer_value(proxy.get("attachments", 0)),
		"card_target_id": str(proxy.get("card_target_id", "")),
		"proxy_target_count": _integer_value(proxy.get("proxy_target_count", 0)),
		"proxy_target_ids": proxy.get("proxy_target_ids", []),
		"last_proxy_position": _format_vec3(proxy.get("last_position", Vector3.ZERO)),
		"card_attach_target_id": str(proxy.get("card_target_id", "")),
		"card_resolved_position": _format_vec3_or_na(proxy.get("card_resolved_position")),
		"card_node_position": _format_vec3_or_na(proxy.get("card_node_position")),
		"card_apply_count": _integer_value(proxy.get("card_apply_count", 0)),
		"packets": _integer_value(proxy.get("packets", 0)),
		"parsed": _integer_value(proxy.get("parsed", 0)),
		"live": _integer_value(proxy.get("live", 0)),
		"sequence": _integer_value(proxy.get("sequence", -1)),
		"packet_bytes": _integer_value(proxy.get("packet_bytes", 0)),
		"packet_preview": str(proxy.get("packet_preview", "-")),
		"message_type": str(proxy.get("message_type", "-")),
		"source_coordinate": proxy.get("source_coordinate", {}),
		"source_coordinate_summary": _source_coordinate_summary(proxy.get("source_coordinate", {})),
		"world_from_head_applied": _truthy(proxy.get("world_from_head_applied", false)),
		"proxy_local_position": _format_vec3(proxy.get("local_position", Vector3.ZERO)),
		"proxy_runtime_local_position": _format_vec3(proxy.get("runtime_local_position", Vector3.ZERO)),
		"proxy_world_position": _format_vec3(proxy.get("world_position", Vector3.ZERO)),
		"proxy_head_z_mode": str(proxy.get("head_z_mode", "negative_z_forward")),
		"proxy_anchor_mode": str(proxy.get("anchor_mode", "dynamic")),
		"proxy_world_latched": _truthy(proxy.get("world_latched", false)),
		"proxy_world_latch_state": str(proxy.get("world_latch_state", "-")),
		"error": str(proxy.get("error", "-")),
		"last_command": str(snapshot.get("last_command", "none")),
	}
	var status_file := FileAccess.open(proxy_targets_status_path, FileAccess.WRITE)
	if status_file == null:
		return
	status_file.store_string(JSON.stringify(status))
	status_file.close()


func _write_passthrough_overlay_status_file(snapshot: Dictionary, delta: float) -> void:
	_passthrough_overlay_status_write_elapsed += delta
	if _passthrough_overlay_status_write_elapsed < STATUS_FILE_WRITE_INTERVAL_SECONDS:
		return
	_passthrough_overlay_status_write_elapsed = 0.0
	var overlay: Dictionary = snapshot.get("passthrough_overlay", {})
	var xr: Dictionary = snapshot.get("xr", {})
	var status := {
		"overlay_enabled": overlay.get("enabled", false),
		"xr_interface_found": _truthy(xr.get("interface_found", false)),
		"xr_initialize_ok": _truthy(xr.get("initialize_ok", false)),
		"xr_active": _truthy(xr.get("active", false)),
		"viewport_transparent_bg": _truthy(snapshot.get("viewport_transparent_bg", false)),
		"requested_blend_mode": str(overlay.get("requested_blend_mode", "alpha_blend")),
		"blend_request_ok": _truthy(overlay.get("blend_request_ok", false)),
		"layer_created": _truthy(overlay.get("layer_created", false)),
		"layer_visible": _truthy(overlay.get("layer_visible", false)),
		"layer_alpha_blend": _truthy(overlay.get("layer_alpha_blend", false)),
		"layer_position": _format_vec3_or_na(overlay.get("layer_position")),
		"status": "ready" if _truthy(overlay.get("enabled", false)) and _truthy(overlay.get("layer_created", false)) else "disabled",
	}
	var status_file := FileAccess.open(passthrough_overlay_status_path, FileAccess.WRITE)
	if status_file == null:
		return
	status_file.store_string(JSON.stringify(status))
	status_file.close()


func _format_xr_status_line(snapshot: Dictionary) -> String:
	var xr: Dictionary = snapshot.get("xr", {})
	var init_error := str(xr.get("init_error", ""))
	var err_str := init_error if not init_error.is_empty() else "-"
	return "XR: iface=%s init=%s active=%s use_xr=%s err=%s" % [
		str(_truthy(xr.get("interface_found", false))),
		str(_truthy(xr.get("initialize_ok", false))),
		str(_truthy(xr.get("active", false))),
		str(_truthy(snapshot.get("viewport_use_xr", false))),
		err_str,
	]


func _format_proxy_targets_status_line(proxy: Dictionary) -> String:
	return "ProxyWS: %s sub=%s packets=%d parsed=%d live=%d apply=%d seq=%d bytes=%d type=%s pos=%s card=%s src=%s err=%s mode=%s latch=%s state=%s" % [
		"connected" if _truthy(proxy.get("ws_connected", false)) else "waiting",
		str(_truthy(proxy.get("ws_subscribed", false))),
		_integer_value(proxy.get("packets", 0)),
		_integer_value(proxy.get("parsed", 0)),
		_integer_value(proxy.get("live", 0)),
		_integer_value(proxy.get("card_apply_count", 0)),
		_integer_value(proxy.get("sequence", -1)),
		_integer_value(proxy.get("packet_bytes", 0)),
		str(proxy.get("message_type", "-")),
		_format_vec3(proxy.get("last_position", Vector3.ZERO)),
		_format_vec3_or_na(proxy.get("card_node_position")),
		_source_coordinate_summary(proxy.get("source_coordinate", {})),
		str(proxy.get("error", "-")),
		str(proxy.get("anchor_mode", "dynamic")),
		str(_truthy(proxy.get("world_latched", false))),
		str(proxy.get("world_latch_state", "-")),
	]


func _format_vst_status_line(vst: Dictionary) -> String:
	var class_state := "registered" if _truthy(vst.get("class_registered", false)) else "missing"
	var init_state := "ok" if _truthy(vst.get("init_ok", false)) else "blocked"
	var first_box: PackedFloat32Array = vst.get("first_box", PackedFloat32Array())
	var box_str := "n/a"
	if first_box.size() >= 5:
		box_str = "%.2f %.2f %.2f %.2f %.2f" % [first_box[0], first_box[1], first_box[2], first_box[3], first_box[4]]
	var target_state_line := "target_state=lost"
	var target_state := str(vst.get("target_state", ""))
	if not target_state.is_empty():
		target_state_line = "target_state=" + target_state
	var last_error := str(vst.get("last_error", ""))
	var err_str := last_error if not last_error.is_empty() else "-"
	var image_size: Vector2 = vst.get("image_size", Vector2.ZERO)
	return "VST: cls=%s init=%s frames=%d boxes=%d latency=%.1fms img=%.0fx%.0f box0=%s %s err=%s\nAnchor: %s\n%s\n%s" % [
		class_state,
		init_state,
		_integer_value(vst.get("frames", 0)),
		_integer_value(vst.get("box_count", 0)),
		_number_value(vst.get("latency_ms", -1.0)),
		image_size.x,
		image_size.y,
		box_str,
		target_state_line,
		err_str,
		"eye2head" if _truthy(vst.get("uses_eye_to_head_anchor", false)) else "raw-fov",
		str(vst.get("eye_to_head_status", "eye2head: not queried")),
		str(vst.get("calibration_status", "cal: not queried")),
	]


func _source_coordinate_summary(source_coordinate) -> String:
	if typeof(source_coordinate) != TYPE_DICTIONARY or source_coordinate.is_empty():
		return "-"
	var space := str(source_coordinate.get("coordinate_space", "-"))
	var anchor := str(source_coordinate.get("anchor", "-"))
	var source_frame = source_coordinate.get("source_frame", {})
	var fov := "-"
	if typeof(source_frame) == TYPE_DICTIONARY:
		fov = "%.1fx%.1f" % [
			_number_value(source_frame.get("horizontal_fov_deg", 0.0)),
			_number_value(source_frame.get("vertical_fov_deg", 0.0)),
		]
	return "%s %s fov=%s eye2head=%s" % [
		space,
		anchor,
		fov,
		str(source_coordinate.get("uses_right_eye_to_head", false)),
	]


func _format_vec3(value) -> String:
	if value is Vector3:
		return "%.2f %.2f %.2f" % [value.x, value.y, value.z]
	return "n/a"


func _format_vec3_or_na(value) -> String:
	return _format_vec3(value)


func _truthy(value) -> bool:
	match typeof(value):
		TYPE_BOOL:
			return value
		TYPE_INT:
			return value != 0
		TYPE_FLOAT:
			return value != 0.0
		TYPE_STRING:
			var normalized := str(value).strip_edges().to_lower()
			return not normalized.is_empty() and normalized != "false" and normalized != "0"
		_:
			return value != null


func _integer_value(value, fallback: int = 0) -> int:
	match typeof(value):
		TYPE_INT:
			return value
		TYPE_FLOAT:
			return roundi(value)
		TYPE_BOOL:
			return 1 if value else 0
		TYPE_STRING:
			return value.to_int()
		_:
			return fallback


func _number_value(value, fallback: float = 0.0) -> float:
	match typeof(value):
		TYPE_FLOAT:
			return value
		TYPE_INT:
			return value
		TYPE_BOOL:
			return 1.0 if value else 0.0
		TYPE_STRING:
			return value.to_float()
		_:
			return fallback
