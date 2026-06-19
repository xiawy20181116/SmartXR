extends RefCounted

## Pure tracked-card data state.
##
## AndroidMovingCard owns scene nodes and XR/VST lifecycle. This object owns the
## script-testable scalar/vector card snapshot used by command dispatch, bbox
## anchoring, and status assembly.

var _speed_deg_per_second := 0.0
var _anchor_yaw_deg := 0.0
var _anchor_pitch_deg := 0.0
var _anchor_depth_m := 1.35
var _anchor_mode := "manual"
var _bbox_center_px := Vector2(436.0, 326.0)
var _bbox_size_px := Vector2(180.0, 240.0)
var _bbox_image_size := Vector2(872.0, 652.0)
var _bbox_depth_m := 1.35
var _bbox_angular_size_deg := Vector2.ZERO
var _paused := false
var _last_command := "none"
var _min_depth_m := 0.65
var _max_depth_m := 4.0
var _card_start_yaw_deg := 0.0
var _card_end_yaw_deg := -32.0


func _init(options := {}) -> void:
	if typeof(options) != TYPE_DICTIONARY:
		return
	_speed_deg_per_second = float(options.get("speed_deg_per_second", _speed_deg_per_second))
	_anchor_yaw_deg = float(options.get("anchor_yaw_deg", _anchor_yaw_deg))
	_anchor_pitch_deg = float(options.get("anchor_pitch_deg", _anchor_pitch_deg))
	_anchor_depth_m = float(options.get("anchor_depth_m", _anchor_depth_m))
	_bbox_center_px = Vector2(options.get("bbox_center_px", _bbox_center_px))
	_bbox_size_px = Vector2(options.get("bbox_size_px", _bbox_size_px))
	_bbox_image_size = Vector2(options.get("bbox_image_size", _bbox_image_size))
	_bbox_depth_m = float(options.get("bbox_depth_m", _bbox_depth_m))
	_min_depth_m = float(options.get("min_depth_m", _min_depth_m))
	_max_depth_m = float(options.get("max_depth_m", _max_depth_m))
	_card_start_yaw_deg = float(options.get("card_start_yaw_deg", _card_start_yaw_deg))
	_card_end_yaw_deg = float(options.get("card_end_yaw_deg", _card_end_yaw_deg))


func command_state() -> Dictionary:
	return status_values()


func apply_command_state(next_state: Dictionary) -> void:
	if typeof(next_state) != TYPE_DICTIONARY:
		return
	_speed_deg_per_second = float(next_state.get("speed_deg_per_second", _speed_deg_per_second))
	_anchor_yaw_deg = float(next_state.get("anchor_yaw_deg", _anchor_yaw_deg))
	_anchor_pitch_deg = float(next_state.get("anchor_pitch_deg", _anchor_pitch_deg))
	_anchor_depth_m = float(next_state.get("anchor_depth_m", _anchor_depth_m))
	_anchor_mode = str(next_state.get("anchor_mode", _anchor_mode))
	_bbox_center_px = Vector2(next_state.get("bbox_center_px", _bbox_center_px))
	_bbox_size_px = Vector2(next_state.get("bbox_size_px", _bbox_size_px))
	_bbox_image_size = Vector2(next_state.get("bbox_image_size", _bbox_image_size))
	_bbox_depth_m = float(next_state.get("bbox_depth_m", _bbox_depth_m))
	_bbox_angular_size_deg = Vector2(next_state.get("bbox_angular_size_deg", _bbox_angular_size_deg))
	_paused = bool(next_state.get("paused", _paused))
	_last_command = str(next_state.get("last_command", _last_command))


func apply_bbox_payload(parsed: Dictionary) -> bool:
	if typeof(parsed) != TYPE_DICTIONARY:
		return false
	var bbox = parsed.get("bbox", {})
	var image = parsed.get("image", {})
	if typeof(bbox) != TYPE_DICTIONARY or typeof(image) != TYPE_DICTIONARY:
		return false
	_bbox_center_px = Vector2(float(bbox.get("cx", _bbox_center_px.x)), float(bbox.get("cy", _bbox_center_px.y)))
	_bbox_size_px = Vector2(float(bbox.get("w", _bbox_size_px.x)), float(bbox.get("h", _bbox_size_px.y)))
	_bbox_image_size = Vector2(float(image.get("w", _bbox_image_size.x)), float(image.get("h", _bbox_image_size.y)))
	_bbox_depth_m = clampf(float(parsed.get("depth_m", _bbox_depth_m)), _min_depth_m, _max_depth_m)
	_anchor_mode = "bbox"
	_last_command = "bbox_payload"
	return true


func apply_bbox_anchor(anchor: Dictionary) -> void:
	if typeof(anchor) != TYPE_DICTIONARY:
		return
	_anchor_yaw_deg = float(anchor.get("yaw_deg", _anchor_yaw_deg))
	_anchor_pitch_deg = float(anchor.get("pitch_deg", _anchor_pitch_deg))
	_anchor_depth_m = float(anchor.get("depth_m", _anchor_depth_m))
	_bbox_angular_size_deg = Vector2(anchor.get("angular_size_deg", _bbox_angular_size_deg))


func advance_manual(delta: float) -> void:
	if _paused or _anchor_mode != "manual":
		return
	_anchor_yaw_deg -= _speed_deg_per_second * delta
	if _anchor_yaw_deg < _card_end_yaw_deg:
		_anchor_yaw_deg = _card_start_yaw_deg


func mark_attached(target_id: String) -> void:
	_anchor_mode = "target"
	_last_command = "attach_target:" + target_id


func mark_detached(is_attachment_empty: bool) -> void:
	if is_attachment_empty and _anchor_mode == "target":
		_anchor_mode = "manual"


func set_last_command(command: String) -> void:
	_last_command = command


func set_anchor_mode(mode: String) -> void:
	_anchor_mode = mode


func status_values() -> Dictionary:
	return {
		"speed_deg_per_second": _speed_deg_per_second,
		"anchor_yaw_deg": _anchor_yaw_deg,
		"anchor_pitch_deg": _anchor_pitch_deg,
		"anchor_depth_m": _anchor_depth_m,
		"anchor_mode": _anchor_mode,
		"bbox_center_px": _bbox_center_px,
		"bbox_size_px": _bbox_size_px,
		"bbox_image_size": _bbox_image_size,
		"bbox_depth_m": _bbox_depth_m,
		"bbox_angular_size_deg": _bbox_angular_size_deg,
		"paused": _paused,
		"last_command": _last_command,
	}


func speed_deg_per_second() -> float:
	return _speed_deg_per_second


func anchor_yaw_deg() -> float:
	return _anchor_yaw_deg


func anchor_pitch_deg() -> float:
	return _anchor_pitch_deg


func anchor_depth_m() -> float:
	return _anchor_depth_m


func anchor_mode() -> String:
	return _anchor_mode


func bbox_center_px() -> Vector2:
	return _bbox_center_px


func bbox_size_px() -> Vector2:
	return _bbox_size_px


func bbox_image_size() -> Vector2:
	return _bbox_image_size


func bbox_depth_m() -> float:
	return _bbox_depth_m


func bbox_angular_size_deg() -> Vector2:
	return _bbox_angular_size_deg


func paused() -> bool:
	return _paused


func last_command() -> String:
	return _last_command
