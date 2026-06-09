extends Node3D
class_name ProxyTargetsConsumer


var proxy_root: Node3D = null
var _proxies := {}
var _card_bindings := {}


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
		proxy.global_transform = _parse_transform(transform_data, proxy.global_transform)
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
