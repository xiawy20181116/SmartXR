extends RefCounted
class_name ValidationSceneBuilder

## Dependency-free builder for validation-only scene nodes.
##
## AndroidMovingCard owns enable gates, lifecycle state, public APIs, and live
## proxy_targets transport. This helper only constructs debug/validation nodes
## and applies the static proxy_targets sample through callbacks/factories
## provided by the card. Keep it no-project loadable: no preloads, no env reads,
## no tree access, and no self-reference to ValidationSceneBuilder.


func build_debug_target_marker(parent: Node, existing_marker, config: Dictionary, register_target: Callable, attach_card: Callable) -> Dictionary:
	if existing_marker != null and is_instance_valid(existing_marker):
		existing_marker.queue_free()
	var marker := MeshInstance3D.new()
	marker.name = str(config.get("marker_name", "MovingTargetMarker"))
	var mesh := BoxMesh.new()
	mesh.size = Vector3(config.get("size_m", Vector3.ONE))
	marker.mesh = mesh
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_color = Color(1.0, 0.92, 0.1, 1.0)
	material.no_depth_test = true
	material.cull_mode = BaseMaterial3D.CULL_DISABLED
	marker.set_surface_override_material(0, material)
	marker.position = Vector3(config.get("base_position", Vector3.ZERO))
	parent.add_child(marker)

	var target_id := str(config.get("target_id", "debug_marker"))
	var card_id := str(config.get("card_id", "CardAnchor"))
	var offset_rule = config.get("offset_rule", {})
	if typeof(offset_rule) != TYPE_DICTIONARY:
		offset_rule = {}
	register_target.call(target_id, marker)
	attach_card.call(card_id, target_id, offset_rule)
	return {
		"marker": marker,
		"elapsed_seconds": 0.0,
	}


func update_debug_target_marker(marker, elapsed_seconds: float, delta: float, config: Dictionary) -> float:
	if marker == null or not is_instance_valid(marker):
		return elapsed_seconds
	var next_elapsed := elapsed_seconds + delta
	var base_position := Vector3(config.get("base_position", Vector3.ZERO))
	var radius_m := float(config.get("radius_m", 0.0))
	marker.position = Vector3(
		base_position.x + sin(next_elapsed * 0.9) * radius_m,
		base_position.y + sin(next_elapsed * 1.7) * 0.08,
		base_position.z + cos(next_elapsed * 0.9) * 0.12
	)
	marker.rotation_degrees = Vector3(0.0, next_elapsed * 35.0, 0.0)
	return next_elapsed


func build_proxy_targets_validation(parent: Node, wrapper: Node, camera: Node, consumer_factory: Callable, adapter_factory: Callable, target_source_factory: Callable, sample_res: String) -> Dictionary:
	var consumer = consumer_factory.call()
	consumer.name = "ProxyTargetsConsumer"
	if camera != null and consumer.has_method("set_head_reference"):
		consumer.set_head_reference(camera)
	parent.add_child(consumer)

	var adapter = adapter_factory.call()
	adapter.name = "ProxyTargetsCardAdapter"
	parent.add_child(adapter)
	adapter.bind(consumer, wrapper)

	var target_source = target_source_factory.call(adapter)
	var sample_command := apply_proxy_targets_sample(target_source, sample_res)
	return {
		"consumer": consumer,
		"card_adapter": adapter,
		"target_source": target_source,
		"sample_command": sample_command,
	}


func apply_proxy_targets_sample(target_source, sample_res: String) -> String:
	if target_source == null:
		return ""
	if not FileAccess.file_exists(sample_res):
		return "proxy_sample_missing"
	var sample := FileAccess.get_file_as_string(sample_res)
	if sample.is_empty():
		return "proxy_sample_empty"
	var applied: bool = bool(target_source.apply_proxy_targets_json(sample))
	return "proxy_sample" if applied else "proxy_sample_failed"
