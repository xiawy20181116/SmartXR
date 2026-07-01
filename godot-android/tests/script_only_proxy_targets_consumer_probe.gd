extends SceneTree

## Script-only runtime probe for proxy_targets_consumer.gd.
##
## Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with:
##   PROXY_TARGETS_CONSUMER_SCRIPT  abs path to proxy_targets_consumer.gd
##   PROXY_TARGETS_CONSUMER_PROBE_STATUS_PATH  abs path for result JSON (optional)

const DEFAULT_STATUS_RES := "user://proxy_targets_consumer_probe_status.json"

var _checks := {}
var _error := "-"
var _exit_code := 1
var _started := false


func _initialize() -> void:
	pass


func _process(_delta: float) -> bool:
	if _started:
		return true
	_started = true
	var run_error := _run_checks()
	if run_error != "-":
		_error = run_error
	elif _all_passed():
		_exit_code = 0
	_write_status(_exit_code)
	quit(_exit_code)
	return true


func _run_checks() -> String:
	var script_path := OS.get_environment("PROXY_TARGETS_CONSUMER_SCRIPT")
	if script_path.is_empty():
		return "missing_env:PROXY_TARGETS_CONSUMER_SCRIPT"
	var consumer_script = load(script_path)
	if consumer_script == null:
		return "load_failed:" + script_path
	_checks["consumer_script_loads"] = true
	_checks["consumer_script_can_instantiate"] = consumer_script.can_instantiate()

	var scene_root := Node3D.new()
	root.add_child(scene_root)
	var head_reference := Node3D.new()
	scene_root.add_child(head_reference)
	var consumer = consumer_script.new()
	scene_root.add_child(consumer)
	consumer.set_head_reference(head_reference)
	consumer.set_proxy_anchor_mode("dynamic")

	head_reference.global_transform = Transform3D(Basis.IDENTITY, Vector3.ZERO)
	consumer.apply_proxy_targets_message(_proxy_message(1, "fresh", false, Vector3(0.0, 0.0, -1.0)))
	var proxy = consumer.get_proxy_target("person-a")
	if proxy == null:
		return "missing_proxy_after_fresh"
	var first_world: Vector3 = proxy.global_transform.origin
	_checks["fresh_target_sets_initial_world_position"] = first_world.is_equal_approx(Vector3(0.0, 0.0, -1.0))

	head_reference.global_transform = Transform3D(Basis.IDENTITY, Vector3(5.0, 0.0, 0.0))
	consumer.apply_proxy_targets_message(_proxy_message(2, "stale", true, Vector3(0.0, 0.0, -1.0)))
	var stale_world: Vector3 = proxy.global_transform.origin
	_checks["dynamic_stale_holds_previous_world_position"] = stale_world.is_equal_approx(first_world)
	_checks["dynamic_stale_reports_held_state"] = str(proxy.get_meta("proxy_world_latch_state", "")) == "dynamic_held" \
		and bool(proxy.get_meta("proxy_world_latched", false))

	consumer.apply_proxy_targets_message(_proxy_message(3, "fresh", false, Vector3(0.0, 0.0, -1.0)))
	var refreshed_world: Vector3 = proxy.global_transform.origin
	_checks["fresh_after_stale_updates_to_current_head_pose"] = refreshed_world.is_equal_approx(Vector3(5.0, 0.0, -1.0))
	_checks["fresh_after_stale_reports_dynamic_state"] = str(proxy.get_meta("proxy_world_latch_state", "")) == "dynamic" \
		and not bool(proxy.get_meta("proxy_world_latched", true))
	return "-"


func _proxy_message(sequence: int, freshness_state: String, held: bool, head_position: Vector3) -> Dictionary:
	return {
		"type": "proxy_targets",
		"schema_version": 1,
		"sequence": sequence,
		"targets": [
			{
				"target_id": "person-a",
				"source": "vst_stereo",
				"coordinate_space": "head",
				"transform_space": "head",
				"state": "tracked",
				"confidence": 0.96,
				"timestamp_ms": 1000 + sequence,
				"freshness": {"state": freshness_state},
				"held": held,
				"transform": {
					"position": [head_position.x, head_position.y, head_position.z],
					"rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
					"scale": [1.0, 1.0, 1.0],
				},
			}
		],
		"cards": [],
	}


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
		"harness": "script_only_proxy_targets_consumer_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("PROXY_TARGETS_CONSUMER_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("proxy_targets_consumer_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
