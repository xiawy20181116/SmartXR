extends SceneTree

## Script-only runtime probe for validation_scene_builder.gd.
##
## Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with:
##   SMARTXR_VALIDATION_SCENE_BUILDER_SCRIPT             abs path to validation_scene_builder.gd
##   SMARTXR_VALIDATION_SCENE_BUILDER_PROBE_STATUS_PATH  abs path for result JSON (optional)

const DEFAULT_STATUS_RES := "user://validation_scene_builder_probe_status.json"

var _checks := {}
var _error := "-"
var _exit_code := 1
var _registered := []
var _attached := []


class FakeConsumer:
	extends Node
	var head_reference: Node = null

	func set_head_reference(reference: Node) -> void:
		head_reference = reference


class FakeAdapter:
	extends Node
	var bound_consumer: Node = null
	var bound_wrapper: Node = null

	func bind(consumer: Node, wrapper: Node) -> void:
		bound_consumer = consumer
		bound_wrapper = wrapper


class FakeTargetSource:
	var adapter: Node = null
	var applied_payload := "-"

	func _init(adapter_node: Node) -> void:
		adapter = adapter_node

	func apply_proxy_targets_json(payload: String) -> bool:
		applied_payload = payload
		return payload.contains('"type"')


func _initialize() -> void:
	var run_error := _run_checks()
	if run_error != "-":
		_error = run_error
	elif _all_passed():
		_exit_code = 0
	_write_status(_exit_code)


func _process(_delta: float) -> bool:
	quit(_exit_code)
	return true


func _run_checks() -> String:
	var script_path := OS.get_environment("SMARTXR_VALIDATION_SCENE_BUILDER_SCRIPT")
	if script_path.is_empty():
		return "missing_env:SMARTXR_VALIDATION_SCENE_BUILDER_SCRIPT"
	var builder_script = load(script_path)
	if builder_script == null:
		return "load_failed:" + script_path
	_checks["builder_script_loads"] = true
	_checks["builder_script_can_instantiate"] = builder_script.can_instantiate()

	var builder = builder_script.new()
	var root := Node3D.new()
	var marker_result: Dictionary = builder.build_debug_target_marker(root, null, {
		"target_id": "debug_marker",
		"card_id": "CardAnchor",
		"marker_name": "MovingTargetMarker",
		"size_m": Vector3(0.12, 0.12, 0.12),
		"base_position": Vector3(0.0, 0.0, -1.15),
		"offset_rule": {"mode": "right_top", "offset_space": "world", "right_m": 0.35, "up_m": 0.25, "fallback": "hold_last_pose"},
	}, _register_target, _attach_card)
	var marker = marker_result.get("marker")
	_checks["build_debug_marker_invokes_public_hooks"] = marker is MeshInstance3D \
		and marker.name == "MovingTargetMarker" \
		and marker.get_parent() == root \
		and marker.position == Vector3(0.0, 0.0, -1.15) \
		and _registered == ["debug_marker"] \
		and _attached == ["CardAnchor:debug_marker"] \
		and float(marker_result.get("elapsed_seconds", -1.0)) == 0.0
	var mesh := marker.mesh as BoxMesh if marker != null else null
	var material := marker.get_surface_override_material(0) as StandardMaterial3D if marker != null else null
	_checks["debug_marker_visuals_match_card"] = mesh != null and mesh.size == Vector3(0.12, 0.12, 0.12) \
		and material != null \
		and material.shading_mode == BaseMaterial3D.SHADING_MODE_UNSHADED \
		and material.albedo_color == Color(1.0, 0.92, 0.1, 1.0) \
		and material.no_depth_test \
		and material.cull_mode == BaseMaterial3D.CULL_DISABLED
	var elapsed: float = builder.update_debug_target_marker(marker, 0.0, 1.0, {
		"base_position": Vector3(0.0, 0.0, -1.15),
		"radius_m": 0.28,
	})
	_checks["update_debug_marker_moves_marker"] = elapsed == 1.0 \
		and marker.position != Vector3(0.0, 0.0, -1.15) \
		and marker.rotation_degrees.is_equal_approx(Vector3(0.0, 35.0, 0.0))

	var sample_path := _sample_path()
	var file := FileAccess.open(sample_path, FileAccess.WRITE)
	if file == null:
		return "sample_open_failed:" + sample_path
	file.store_string('{"type":"proxy_targets","targets":[]}')
	file.close()
	var camera := Camera3D.new()
	root.add_child(camera)
	var validation: Dictionary = builder.build_proxy_targets_validation(
		root,
		root,
		camera,
		_new_consumer,
		_new_adapter,
		_new_target_source,
		sample_path
	)
	var consumer = validation.get("consumer")
	var adapter = validation.get("card_adapter")
	var target_source = validation.get("target_source")
	_checks["build_proxy_validation_wires_fake_nodes"] = consumer is FakeConsumer \
		and adapter is FakeAdapter \
		and target_source is FakeTargetSource \
		and consumer.name == "ProxyTargetsConsumer" \
		and adapter.name == "ProxyTargetsCardAdapter" \
		and consumer.get_parent() == root \
		and adapter.get_parent() == root \
		and consumer.head_reference == camera \
		and adapter.bound_consumer == consumer \
		and adapter.bound_wrapper == root \
		and target_source.adapter == adapter \
		and target_source.applied_payload.contains("proxy_targets") \
		and str(validation.get("sample_command")) == "proxy_sample"
	_checks["sample_missing_sets_command"] = builder.apply_proxy_targets_sample(target_source, "user://missing_validation_sample.json") == "proxy_sample_missing"

	root.free()
	return "-"


func _register_target(target_id: String, _target: Node3D) -> void:
	_registered.append(target_id)


func _attach_card(card_id: String, target_id: String, _rule: Dictionary) -> bool:
	_attached.append("%s:%s" % [card_id, target_id])
	return true


func _new_consumer():
	return FakeConsumer.new()


func _new_adapter():
	return FakeAdapter.new()


func _new_target_source(adapter: Node):
	return FakeTargetSource.new(adapter)


func _sample_path() -> String:
	var status_path := OS.get_environment("SMARTXR_VALIDATION_SCENE_BUILDER_PROBE_STATUS_PATH")
	if not status_path.is_empty():
		return status_path.get_base_dir().path_join("validation_scene_builder_sample.json")
	return OS.get_temp_dir().path_join("validation_scene_builder_sample.json")


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
		"harness": "script_only_validation_scene_builder_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_VALIDATION_SCENE_BUILDER_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("validation_scene_builder_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
