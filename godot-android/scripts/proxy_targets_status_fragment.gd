extends RefCounted
class_name ProxyTargetsStatusFragment

## Dependency-free proxy_targets diagnostics/status fragment.
##
## AndroidMovingCard owns live WebSocket transport, consumer calls, card
## attachment lookup, and node positions. This helper owns only pure
## diagnostics bookkeeping and the ordered values Dictionary passed into the
## status snapshot composer. Keep it no-project loadable: no preloads, no env
## reads, no tree access, and no self-reference to ProxyTargetsStatusFragment.

var _parsed_messages := 0
var _last_sequence := -1
var _last_position := Vector3.ZERO
var _last_packet_preview := "-"
var _last_message_type := "-"
var _last_error := "-"
var _last_source_coordinate := {}
var _last_world_from_head_applied := false
var _last_local_position := Vector3.ZERO
var _last_runtime_local_position := Vector3.ZERO
var _last_world_position := Vector3.ZERO
var _last_head_z_mode := "negative_z_forward"
var _last_anchor_mode := "dynamic"
var _last_world_latched := false
var _last_world_latch_state := "-"


func set_packet_preview(preview: String) -> void:
	_last_packet_preview = preview


func set_error(error: String) -> void:
	_last_error = error


func set_message_type(message_type: String) -> void:
	_last_message_type = message_type


func record_parsed_message(message: Dictionary, head_info: Dictionary = {}) -> void:
	_parsed_messages += 1
	_last_message_type = str(message.get("type", "-"))
	_last_sequence = int(message.get("sequence", _last_sequence))
	var targets = message.get("targets", [])
	if not (targets is Array) or targets.is_empty():
		return
	var target = targets[0]
	if typeof(target) != TYPE_DICTIONARY:
		return
	var transform = target.get("transform", {})
	if typeof(transform) != TYPE_DICTIONARY:
		return
	var position = transform.get("position", [])
	if not (position is Array) or position.size() < 3:
		return
	_last_position = Vector3(float(position[0]), float(position[1]), float(position[2]))
	var source_coordinate = target.get("source_coordinate", {})
	if typeof(source_coordinate) == TYPE_DICTIONARY:
		_last_source_coordinate = source_coordinate.duplicate(true)
	else:
		_last_source_coordinate = {}
	_record_head_to_world_info(head_info)


func status_values(runtime_values: Dictionary) -> Dictionary:
	return {
		"ws_connected": runtime_values.get("ws_connected"),
		"ws_subscribed": runtime_values.get("ws_subscribed"),
		"ws_url": runtime_values.get("ws_url"),
		"attachments": runtime_values.get("attachments"),
		"card_target_id": runtime_values.get("card_target_id"),
		"proxy_target_count": runtime_values.get("proxy_target_count"),
		"proxy_target_ids": runtime_values.get("proxy_target_ids"),
		"last_position": _last_position,
		"card_resolved_position": runtime_values.get("card_resolved_position"),
		"card_node_position": runtime_values.get("card_node_position"),
		"card_apply_count": runtime_values.get("card_apply_count"),
		"packets": runtime_values.get("packets"),
		"parsed": _parsed_messages,
		"live": runtime_values.get("live"),
		"sequence": _last_sequence,
		"packet_bytes": runtime_values.get("packet_bytes"),
		"packet_preview": _last_packet_preview,
		"message_type": _last_message_type,
		"source_coordinate": _last_source_coordinate,
		"world_from_head_applied": _last_world_from_head_applied,
		"local_position": _last_local_position,
		"runtime_local_position": _last_runtime_local_position,
		"world_position": _last_world_position,
		"head_z_mode": _last_head_z_mode,
		"anchor_mode": _last_anchor_mode,
		"world_latched": _last_world_latched,
		"world_latch_state": _last_world_latch_state,
		"error": _last_error,
	}


static func proxy_target_count(targets) -> int:
	if typeof(targets) != TYPE_DICTIONARY:
		return 0
	return targets.size()


static func proxy_target_ids(targets) -> Array:
	if typeof(targets) != TYPE_DICTIONARY:
		return []
	var ids := []
	for target_id in targets.keys():
		ids.append(str(target_id))
	ids.sort()
	return ids


static func vector3_from_status_array(value, fallback: Vector3) -> Vector3:
	if typeof(value) != TYPE_ARRAY or value.size() < 3:
		return fallback
	return Vector3(float(value[0]), float(value[1]), float(value[2]))


func _record_head_to_world_info(info: Dictionary) -> void:
	_last_world_from_head_applied = false
	if info.is_empty():
		return
	_last_world_from_head_applied = bool(info.get("world_from_head_applied", false))
	_last_local_position = vector3_from_status_array(info.get("local_position", []), _last_local_position)
	_last_runtime_local_position = vector3_from_status_array(info.get("runtime_local_position", []), _last_runtime_local_position)
	_last_world_position = vector3_from_status_array(info.get("world_position", []), _last_world_position)
	_last_head_z_mode = str(info.get("head_z_mode", _last_head_z_mode))
	_last_anchor_mode = str(info.get("anchor_mode", _last_anchor_mode))
	_last_world_latched = bool(info.get("world_latched", false))
	_last_world_latch_state = str(info.get("world_latch_state", _last_world_latch_state))
