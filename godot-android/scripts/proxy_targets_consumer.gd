extends Node3D
class_name ProxyTargetsConsumer


var proxy_root: Node3D = null
var head_reference: Node3D = null
var _proxies := {}
var _card_bindings := {}
var _last_applied_target_info := {}


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


func get_last_applied_target_info() -> Dictionary:
	return _last_applied_target_info.duplicate(true)


func _apply_target(target: Dictionary) -> void:
	var target_id := str(target.get("target_id", ""))
	if target_id.is_empty():
		return

	var proxy: Node3D = _proxies.get(target_id, null)
	if proxy == null:
		proxy = Node3D.new()
		proxy.name = target_id
		proxy_root.add_child(proxy)
		_proxies[target_id] = proxy

	var transform_data: Variant = target.get("transform", {})
	if typeof(transform_data) == TYPE_DICTIONARY:
		var parsed_transform := _parse_transform(transform_data, proxy.global_transform)
		var local_position := parsed_transform.origin
		var coordinate_space := _target_coordinate_space(target)
		var world_from_head_applied := false
		if _is_head_coordinate_space(coordinate_space) and head_reference != null:
			parsed_transform = _head_transform_to_world(parsed_transform)
			world_from_head_applied = true
		proxy.global_transform = parsed_transform
		proxy.set_meta("proxy_coordinate_space", coordinate_space)
		proxy.set_meta("proxy_world_from_head_applied", world_from_head_applied)
		proxy.set_meta("proxy_local_position", local_position)
		proxy.set_meta("proxy_world_position", parsed_transform.origin)
		_last_applied_target_info = {
			"target_id": target_id,
			"source": str(target.get("source", "")),
			"coordinate_space": coordinate_space,
			"world_from_head_applied": world_from_head_applied,
			"local_position": _vec3_to_array(local_position),
			"world_position": _vec3_to_array(parsed_transform.origin),
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


func _head_transform_to_world(head_transform: Transform3D) -> Transform3D:
	if head_reference == null:
		return head_transform
	return head_reference.global_transform * head_transform


func _vec3_to_array(value: Vector3) -> Array:
	return [value.x, value.y, value.z]
