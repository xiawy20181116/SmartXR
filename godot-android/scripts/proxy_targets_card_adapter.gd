extends Node
class_name ProxyTargetsCardAdapter


var proxy_targets_consumer: Node = null
var card_wrapper: Node = null
var target_register_method_names := ["register_node3d_target", "register_target", "register_proxy_target"]
var attach_method_name := "attach_to_target"
var default_card_id := "CardAnchor"


func bind(consumer: Node, wrapper: Node) -> void:
	proxy_targets_consumer = consumer
	card_wrapper = wrapper


func apply_proxy_targets_json(payload: String) -> bool:
	var parsed = JSON.parse_string(payload)
	if typeof(parsed) != TYPE_DICTIONARY:
		return false
	return apply_proxy_targets_message(parsed)


func apply_proxy_targets_message(message: Dictionary) -> bool:
	if proxy_targets_consumer == null or card_wrapper == null:
		return false
	if not proxy_targets_consumer.apply_proxy_targets_message(message):
		return false
	return sync_card_wrapper()


func sync_card_wrapper() -> bool:
	if proxy_targets_consumer == null or card_wrapper == null:
		return false

	var registered_ok := false
	var attached_ok := false
	var proxy_targets: Dictionary = proxy_targets_consumer.get_proxy_targets()

	for target_id in proxy_targets.keys():
		if _register_proxy_target(str(target_id), proxy_targets_consumer.get_proxy_target(str(target_id))):
			registered_ok = true

	var card_bindings := _card_bindings_or_single_target_fallback(proxy_targets)
	for card_id in card_bindings.keys():
		var card: Variant = card_bindings[card_id]
		if typeof(card) == TYPE_DICTIONARY:
			if _attach_card_to_proxy_target(str(card_id), card):
				attached_ok = true

	return registered_ok and attached_ok


func _card_bindings_or_single_target_fallback(proxy_targets: Dictionary) -> Dictionary:
	var bindings: Dictionary = proxy_targets_consumer.get_card_bindings()
	if bindings.is_empty() and proxy_targets.size() == 1:
		var target_id := str(proxy_targets.keys()[0])
		bindings[default_card_id] = {
			"card_id": default_card_id,
			"target_id": target_id,
			"offset_rule": _default_offset_rule(),
		}
	return bindings


func _register_proxy_target(target_id: String, proxy: Node3D) -> bool:
	if proxy == null:
		return false
	for method_name in target_register_method_names:
		if card_wrapper.has_method(method_name):
			card_wrapper.call(method_name, target_id, proxy)
			return true
	return false


func _attach_card_to_proxy_target(card_id: String, card: Dictionary) -> bool:
	if not card.has("target_id"):
		return false
	if not card_wrapper.has_method(attach_method_name):
		return false
	var offset_rule = card.get("offset_rule", _default_offset_rule())
	return bool(card_wrapper.call(attach_method_name, card_id, str(card["target_id"]), offset_rule))


func _default_offset_rule() -> Dictionary:
	return {
		"mode": "right_top",
		"offset_space": "world",
		"right_m": 0.35,
		"up_m": 0.25,
		"fallback": "hold_last_pose"
	}
