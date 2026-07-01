extends Node3D
class_name ProxyTargetsConsumer

const ANCHOR_MODE_DYNAMIC := "dynamic"
const ANCHOR_MODE_WORLD_LATCHED := "world_latched"
const HEAD_Z_MODE_NEGATIVE_FORWARD := "negative_z_forward"
const HEAD_Z_MODE_POSITIVE_FORWARD := "positive_z_forward"

var proxy_root: Node3D = null
var head_reference: Node3D = null
var proxy_anchor_mode := ANCHOR_MODE_DYNAMIC
var proxy_head_z_mode := HEAD_Z_MODE_NEGATIVE_FORWARD
var _proxies := {}
var _card_bindings := {}
var _last_applied_target_info := {}
var _world_latches := {}
var _world_latch_references := {}
var _world_latch_sizes := {}


func _ready() -> void:
	if proxy_root == null:
		proxy_root = Node3D.new()
		proxy_root.name = "ProxyTargets"
		add_child(proxy_root)


func apply_proxy_targets_json(payload: String) -> bool:
	var parsed = JSON.parse_string(payload)
	if typeof(parsed) != TYPE_DICTIONARY:
		return false
	return apply_proxy_targets_message(parsed)


func apply_proxy_targets_message(message: Dictionary) -> bool:
	if message.get("type", "") != "proxy_targets":
		return false
	if proxy_root == null:
		_ready()

	for target in message.get("targets", []):
		if typeof(target) == TYPE_DICTIONARY:
			_apply_target(target)

	_card_bindings.clear()
	for card in message.get("cards", []):
		if typeof(card) == TYPE_DICTIONARY and card.has("card_id") and card.has("target_id"):
			_card_bindings[str(card["card_id"])] = card.duplicate(true)

	return true


func get_proxy_target(target_id: String) -> Node3D:
	return _proxies.get(target_id, null)


func get_proxy_targets() -> Dictionary:
	return _proxies.duplicate()


func get_card_bindings() -> Dictionary:
	return _card_bindings.duplicate(true)


func set_head_reference(reference: Node3D) -> void:
	head_reference = reference


func set_proxy_head_z_mode(mode: String) -> void:
	proxy_head_z_mode = _normalize_proxy_head_z_mode(mode)


func set_proxy_anchor_mode(mode: String) -> void:
	var normalized := _normalize_proxy_anchor_mode(mode)
	if normalized == proxy_anchor_mode:
		return
	proxy_anchor_mode = normalized
	reset_world_latches()


func reset_world_latches() -> void:
	_world_latches.clear()
	_world_latch_references.clear()
	_world_latch_sizes.clear()
	for proxy_id in _proxies:
		var proxy: Node3D = _proxies.get(proxy_id, null)
		if proxy != null:
			proxy.set_meta("proxy_world_latched", false)
			proxy.set_meta("proxy_world_latch_state", "reset")


func get_last_applied_target_info() -> Dictionary:
	return _last_applied_target_info.duplicate(true)


func _apply_target(target: Dictionary) -> void:
	var target_id := str(target.get("target_id", ""))
	if target_id.is_empty():
		return
	if _target_is_lost(target):
		_world_latches.erase(target_id)
		_world_latch_references.erase(target_id)
		_world_latch_sizes.erase(target_id)

	var proxy: Node3D = _proxies.get(target_id, null)
	if proxy == null:
		proxy = Node3D.new()
		proxy.name = target_id
		proxy_root.add_child(proxy)
		_proxies[target_id] = proxy

	var transform_data: Variant = target.get("transform", {})
	if typeof(transform_data) == TYPE_DICTIONARY:
		var parsed_transform := _parse_transform(transform_data, proxy.global_transform)
		var target_size_m := _target_size_m(target)
		var local_position := parsed_transform.origin
		var runtime_transform := parsed_transform
		var runtime_local_position := local_position
		var coordinate_space := _target_coordinate_space(target)
		var world_from_head_applied := false
		var world_latched := false
		var world_latch_state := ANCHOR_MODE_DYNAMIC
		var offset_reference_transform := _head_reference_transform()
		if _is_head_coordinate_space(coordinate_space) and head_reference != null:
			runtime_transform = _head_transform_for_runtime(parsed_transform)
			runtime_local_position = runtime_transform.origin
			parsed_transform = _head_transform_to_world(runtime_transform)
			world_from_head_applied = true
		if proxy_anchor_mode == ANCHOR_MODE_DYNAMIC:
			var dynamic_result := _apply_dynamic_hold(target_id, target, parsed_transform, proxy.global_transform, offset_reference_transform, target_size_m)
			parsed_transform = dynamic_result.get("transform", parsed_transform)
			offset_reference_transform = dynamic_result.get("reference_transform", offset_reference_transform)
			target_size_m = dynamic_result.get("target_size_m", target_size_m)
			world_latched = bool(dynamic_result.get("world_latched", false))
			world_latch_state = str(dynamic_result.get("world_latch_state", ANCHOR_MODE_DYNAMIC))
		elif proxy_anchor_mode == ANCHOR_MODE_WORLD_LATCHED:
			var latch_result := _apply_world_latch(target_id, target, parsed_transform, proxy.global_transform, offset_reference_transform, target_size_m)
			parsed_transform = latch_result.get("transform", parsed_transform)
			offset_reference_transform = latch_result.get("reference_transform", offset_reference_transform)
			target_size_m = latch_result.get("target_size_m", target_size_m)
			world_latched = bool(latch_result.get("world_latched", false))
			world_latch_state = str(latch_result.get("world_latch_state", "-"))
		proxy.global_transform = parsed_transform
		proxy.set_meta("proxy_coordinate_space", coordinate_space)
		proxy.set_meta("proxy_world_from_head_applied", world_from_head_applied)
		proxy.set_meta("proxy_local_position", local_position)
		proxy.set_meta("proxy_runtime_local_position", runtime_local_position)
		proxy.set_meta("proxy_world_position", parsed_transform.origin)
		proxy.set_meta("proxy_target_size_m", target_size_m)
		proxy.set_meta("proxy_target_width_m", target_size_m.x)
		proxy.set_meta("proxy_head_z_mode", proxy_head_z_mode)
		proxy.set_meta("proxy_anchor_mode", proxy_anchor_mode)
		proxy.set_meta("proxy_world_latched", world_latched)
		proxy.set_meta("proxy_world_latch_state", world_latch_state)
		proxy.set_meta("proxy_world_latch_reference_transform", offset_reference_transform)
		_last_applied_target_info = {
			"target_id": target_id,
			"source": str(target.get("source", "")),
			"coordinate_space": coordinate_space,
			"world_from_head_applied": world_from_head_applied,
			"local_position": _vec3_to_array(local_position),
			"runtime_local_position": _vec3_to_array(runtime_local_position),
			"world_position": _vec3_to_array(parsed_transform.origin),
			"target_size_m": _vec3_to_array(target_size_m),
			"head_z_mode": proxy_head_z_mode,
			"anchor_mode": proxy_anchor_mode,
			"world_latched": world_latched,
			"world_latch_state": world_latch_state,
		}
	proxy.visible = str(target.get("state", "tracked")) != "lost"
	proxy.set_meta("proxy_target_id", target_id)
	proxy.set_meta("proxy_source", str(target.get("source", "")))
	proxy.set_meta("proxy_state", str(target.get("state", "tracked")))
	proxy.set_meta("proxy_confidence", float(target.get("confidence", 0.0)))
	proxy.set_meta("proxy_timestamp_ms", int(target.get("timestamp_ms", 0)))


func _parse_transform(transform_data: Dictionary, fallback: Transform3D) -> Transform3D:
	var result := fallback
	var position := _parse_vector3(transform_data.get("position", []), result.origin)
	var scale := _parse_vector3(transform_data.get("scale", [1.0, 1.0, 1.0]), result.basis.get_scale())
	var rotation := _parse_quaternion(transform_data.get("rotation_xyzw", []), result.basis.get_rotation_quaternion())
	result.basis = Basis(rotation).scaled(scale)
	result.origin = position
	return result


func _parse_vector3(value, fallback: Vector3) -> Vector3:
	if typeof(value) != TYPE_ARRAY or value.size() < 3:
		return fallback
	return Vector3(float(value[0]), float(value[1]), float(value[2]))


func _parse_quaternion(value, fallback: Quaternion) -> Quaternion:
	if typeof(value) != TYPE_ARRAY or value.size() < 4:
		return fallback
	return Quaternion(float(value[0]), float(value[1]), float(value[2]), float(value[3])).normalized()


func _target_size_m(target: Dictionary) -> Vector3:
	var size = target.get("target_size_m", {})
	if typeof(size) != TYPE_DICTIONARY:
		var source_coordinate = target.get("source_coordinate", {})
		if typeof(source_coordinate) == TYPE_DICTIONARY:
			size = source_coordinate.get("target_size_m", {})
	if typeof(size) != TYPE_DICTIONARY:
		return Vector3.ZERO
	return Vector3(
		maxf(float(size.get("width", 0.0)), 0.0),
		maxf(float(size.get("height", 0.0)), 0.0),
		maxf(float(size.get("depth", 0.0)), 0.0)
	)


func _target_coordinate_space(target: Dictionary) -> String:
	var transform_space := str(target.get("transform_space", "")).strip_edges().to_lower()
	if not transform_space.is_empty():
		return transform_space
	var coordinate_space := str(target.get("coordinate_space", "")).strip_edges().to_lower()
	if not coordinate_space.is_empty():
		return coordinate_space
	var source_coordinate = target.get("source_coordinate", {})
	if typeof(source_coordinate) == TYPE_DICTIONARY:
		var publisher_convention := str(source_coordinate.get("publisher_convention", "")).strip_edges().to_lower()
		if publisher_convention == "godot_head":
			return "head"
	var source := str(target.get("source", "")).strip_edges().to_lower()
	if source == "vst":
		return "head"
	return "world"


func _is_head_coordinate_space(coordinate_space: String) -> bool:
	return ["head", "godot_head", "camera", "xr_camera"].has(coordinate_space.strip_edges().to_lower())


func _apply_dynamic_hold(target_id: String, target: Dictionary, world_transform: Transform3D, current_world_transform: Transform3D, reference_transform: Transform3D, target_size_m: Vector3) -> Dictionary:
	if proxy_anchor_mode != ANCHOR_MODE_DYNAMIC:
		return {"transform": world_transform, "reference_transform": reference_transform, "target_size_m": target_size_m, "world_latched": false, "world_latch_state": ANCHOR_MODE_DYNAMIC}
	if _target_is_lost(target):
		_world_latches.erase(target_id)
		_world_latch_references.erase(target_id)
		_world_latch_sizes.erase(target_id)
		return {"transform": world_transform, "reference_transform": reference_transform, "target_size_m": target_size_m, "world_latched": false, "world_latch_state": "cleared_lost"}
	if _target_is_fresh(target):
		_world_latches[target_id] = world_transform
		_world_latch_references[target_id] = reference_transform
		_world_latch_sizes[target_id] = target_size_m
		return {"transform": world_transform, "reference_transform": reference_transform, "target_size_m": target_size_m, "world_latched": false, "world_latch_state": ANCHOR_MODE_DYNAMIC}
	if _world_latches.has(target_id):
		return {
			"transform": _world_latches[target_id],
			"reference_transform": _world_latch_references.get(target_id, reference_transform),
			"target_size_m": _world_latch_sizes.get(target_id, target_size_m),
			"world_latched": true,
			"world_latch_state": "dynamic_held"
		}
	return {"transform": current_world_transform, "reference_transform": reference_transform, "target_size_m": target_size_m, "world_latched": false, "world_latch_state": "dynamic_waiting_fresh"}


func _apply_world_latch(target_id: String, target: Dictionary, world_transform: Transform3D, current_world_transform: Transform3D, reference_transform: Transform3D, target_size_m: Vector3) -> Dictionary:
	if proxy_anchor_mode != ANCHOR_MODE_WORLD_LATCHED:
		return {"transform": world_transform, "world_latched": false, "world_latch_state": ANCHOR_MODE_DYNAMIC}
	if _target_is_lost(target):
		_world_latches.erase(target_id)
		_world_latch_references.erase(target_id)
		_world_latch_sizes.erase(target_id)
		return {"transform": world_transform, "reference_transform": reference_transform, "target_size_m": target_size_m, "world_latched": false, "world_latch_state": "cleared_lost"}
	if _world_latches.has(target_id):
		return {
			"transform": _world_latches[target_id],
			"reference_transform": _world_latch_references.get(target_id, reference_transform),
			"target_size_m": _world_latch_sizes.get(target_id, target_size_m),
			"world_latched": true,
			"world_latch_state": "latched_held"
		}
	if not _target_is_fresh(target):
		return {"transform": current_world_transform, "reference_transform": reference_transform, "target_size_m": target_size_m, "world_latched": false, "world_latch_state": "waiting_fresh"}
	_world_latches[target_id] = world_transform
	_world_latch_references[target_id] = reference_transform
	_world_latch_sizes[target_id] = target_size_m
	return {"transform": world_transform, "reference_transform": reference_transform, "target_size_m": target_size_m, "world_latched": true, "world_latch_state": "latched_fresh"}


func _target_is_fresh(target: Dictionary) -> bool:
	if _target_is_lost(target):
		return false
	if bool(target.get("held", false)):
		return false
	var freshness = target.get("freshness", {})
	if typeof(freshness) == TYPE_DICTIONARY:
		var freshness_state := str(freshness.get("state", "")).strip_edges().to_lower()
		if not freshness_state.is_empty():
			return freshness_state == "fresh"
	var tracking_confidence := str(target.get("tracking_confidence", "")).strip_edges().to_lower()
	if not tracking_confidence.is_empty():
		return tracking_confidence == "fresh"
	return true


func _target_is_lost(target: Dictionary) -> bool:
	return str(target.get("state", "tracked")).strip_edges().to_lower() == "lost"


func _normalize_proxy_anchor_mode(mode: String) -> String:
	var normalized := mode.strip_edges().to_lower()
	if normalized == ANCHOR_MODE_WORLD_LATCHED:
		return ANCHOR_MODE_WORLD_LATCHED
	return ANCHOR_MODE_DYNAMIC


func _normalize_proxy_head_z_mode(mode: String) -> String:
	var normalized := mode.strip_edges().to_lower()
	if normalized == HEAD_Z_MODE_POSITIVE_FORWARD:
		return HEAD_Z_MODE_POSITIVE_FORWARD
	return HEAD_Z_MODE_NEGATIVE_FORWARD


func _head_transform_for_runtime(head_transform: Transform3D) -> Transform3D:
	var runtime_transform := head_transform
	if proxy_head_z_mode == HEAD_Z_MODE_POSITIVE_FORWARD:
		runtime_transform.origin.z = -runtime_transform.origin.z
	return runtime_transform


func _head_transform_to_world(head_transform: Transform3D) -> Transform3D:
	if head_reference == null:
		return head_transform
	return head_reference.global_transform * head_transform


func _head_reference_transform() -> Transform3D:
	if head_reference == null:
		return Transform3D.IDENTITY
	return head_reference.global_transform


func _vec3_to_array(value: Vector3) -> Array:
	return [value.x, value.y, value.z]
