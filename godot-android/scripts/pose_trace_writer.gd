extends RefCounted

## Writes per-frame proxy/card pose diagnostics to JSONL.
##
## AndroidMovingCard owns the live nodes and produces the status snapshot;
## this helper keeps trace serialization out of the main scene script.

var _path := ""
var _failed := false


func setup(path: String) -> void:
	_path = path.strip_edges()
	_failed = false
	if _path.is_empty():
		return
	var file := FileAccess.open(_path, FileAccess.WRITE)
	if file == null:
		_failed = true
		push_warning("Proxy targets pose trace open failed: %s" % _path)
		return
	file.close()
	print("Proxy targets pose trace: %s" % _path)


func write(delta: float, snapshot: Dictionary) -> void:
	if _path.is_empty() or _failed:
		return
	var proxy: Dictionary = snapshot.get("proxy_targets", {})
	var event := {
		"timestamp_ms": int(Time.get_ticks_msec()),
		"delta_s": float(delta),
		"head_pose": _head_pose(snapshot),
		"proxy_world": _proxy_world(proxy),
		"card_world": _card_world(snapshot, proxy),
		"anchor_state": _anchor_state(snapshot, proxy),
	}
	var file := FileAccess.open(_path, FileAccess.READ_WRITE)
	if file == null:
		_failed = true
		push_warning("Proxy targets pose trace append failed: %s" % _path)
		return
	file.seek_end()
	file.store_line(JSON.stringify(event))
	file.close()


func _vec3(value):
	if typeof(value) == TYPE_VECTOR3:
		return [float(value.x), float(value.y), float(value.z)]
	if typeof(value) == TYPE_ARRAY and value.size() >= 3:
		return [float(value[0]), float(value[1]), float(value[2])]
	return null


func _head_pose(snapshot: Dictionary) -> Dictionary:
	return {
		"position": _vec3(snapshot.get("camera_position", null)),
		"rotation_degrees": _vec3(snapshot.get("camera_rotation_degrees", null)),
		"xr_origin_position": _vec3(snapshot.get("xr_origin_position", null)),
	}


func _proxy_world(proxy: Dictionary) -> Dictionary:
	return {
		"target_id": str(proxy.get("card_target_id", "")),
		"proxy_count": int(proxy.get("proxy_target_count", 0)),
		"local_position": _vec3(proxy.get("local_position", null)),
		"runtime_local_position": _vec3(proxy.get("runtime_local_position", null)),
		"world_position": _vec3(proxy.get("world_position", null)),
		"head_z_mode": str(proxy.get("head_z_mode", "negative_z_forward")),
		"world_from_head_applied": bool(proxy.get("world_from_head_applied", false)),
	}


func _card_world(snapshot: Dictionary, proxy: Dictionary) -> Dictionary:
	return {
		"card_id": "CardAnchor",
		"target_id": str(proxy.get("card_target_id", "")),
		"resolved_position": _vec3(proxy.get("card_resolved_position", null)),
		"node_position": _vec3(proxy.get("card_node_position", null)),
		"rotation_degrees": _vec3(snapshot.get("card_rotation_degrees", null)),
		"apply_count": int(proxy.get("card_apply_count", 0)),
	}


func _anchor_state(snapshot: Dictionary, proxy: Dictionary) -> Dictionary:
	return {
		"anchor_mode": str(snapshot.get("anchor_mode", "")),
		"proxy_anchor_mode": str(proxy.get("anchor_mode", "dynamic")),
		"world_latched": bool(proxy.get("world_latched", false)),
		"world_latch_state": str(proxy.get("world_latch_state", "-")),
		"card_reacquire_state": str(proxy.get("card_reacquire_state", "idle")),
		"head_z_mode": str(proxy.get("head_z_mode", "negative_z_forward")),
		"card_attachment_count": int(proxy.get("attachments", 0)),
		"last_command": str(snapshot.get("last_command", "")),
		"paused": bool(snapshot.get("paused", false)),
	}
