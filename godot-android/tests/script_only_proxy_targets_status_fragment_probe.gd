extends SceneTree

## Script-only runtime probe for proxy_targets_status_fragment.gd.
##
## Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with:
##   SMARTXR_PROXY_TARGETS_STATUS_FRAGMENT_SCRIPT             abs path to proxy_targets_status_fragment.gd
##   SMARTXR_PROXY_TARGETS_STATUS_FRAGMENT_PROBE_STATUS_PATH  abs path for result JSON (optional)

const DEFAULT_STATUS_RES := "user://proxy_targets_status_fragment_probe_status.json"

var _checks := {}
var _error := "-"
var _exit_code := 1


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
	var script_path := OS.get_environment("SMARTXR_PROXY_TARGETS_STATUS_FRAGMENT_SCRIPT")
	if script_path.is_empty():
		return "missing_env:SMARTXR_PROXY_TARGETS_STATUS_FRAGMENT_SCRIPT"
	var fragment_script = load(script_path)
	if fragment_script == null:
		return "load_failed:" + script_path
	_checks["fragment_script_loads"] = true
	_checks["fragment_script_can_instantiate"] = fragment_script.can_instantiate()

	var fragment = fragment_script.new()
	var defaults: Dictionary = fragment.status_values({})
	_checks["defaults_match_card_initial_state"] = int(defaults.get("parsed")) == 0 \
		and int(defaults.get("sequence")) == -1 \
		and Vector3(defaults.get("last_position")).is_equal_approx(Vector3.ZERO) \
		and str(defaults.get("packet_preview")) == "-" \
		and str(defaults.get("message_type")) == "-" \
		and str(defaults.get("error")) == "-"

	fragment.set_packet_preview("probe_packet")
	fragment.set_error("probe_error")
	fragment.set_message_type("manual_type")
	var manual: Dictionary = fragment.status_values({})
	_checks["manual_setters_update_status"] = str(manual.get("packet_preview")) == "probe_packet" \
		and str(manual.get("error")) == "probe_error" \
		and str(manual.get("message_type")) == "manual_type"

	var source_coordinate := {"space": "head", "stream": "probe"}
	var message := {
		"type": "proxy_targets",
		"sequence": 42,
		"targets": [
			{
				"target_id": "target_a",
				"transform": {"position": [1.0, 2.0, 3.0]},
				"source_coordinate": source_coordinate,
			}
		],
	}
	fragment.record_parsed_message(message, {
		"world_from_head_applied": true,
		"local_position": [0.1, 0.2, 0.3],
		"runtime_local_position": [0.1, 0.2, -0.3],
		"world_position": [4.0, 5.0, 6.0],
		"head_z_mode": "positive_z_forward",
		"anchor_mode": "world_latched",
		"world_latched": true,
		"world_latch_state": "latched_fresh",
	})
	source_coordinate["space"] = "mutated"
	var recorded: Dictionary = fragment.status_values({})
	_checks["records_message_diagnostics"] = int(recorded.get("parsed")) == 1 \
		and str(recorded.get("message_type")) == "proxy_targets" \
		and int(recorded.get("sequence")) == 42 \
		and Vector3(recorded.get("last_position")).is_equal_approx(Vector3(1.0, 2.0, 3.0)) \
		and str(recorded.get("source_coordinate", {}).get("space")) == "head"
	_checks["records_head_to_world_info"] = bool(recorded.get("world_from_head_applied")) \
		and Vector3(recorded.get("local_position")).is_equal_approx(Vector3(0.1, 0.2, 0.3)) \
		and Vector3(recorded.get("runtime_local_position")).is_equal_approx(Vector3(0.1, 0.2, -0.3)) \
		and Vector3(recorded.get("world_position")).is_equal_approx(Vector3(4.0, 5.0, 6.0))
	_checks["records_head_z_mode"] = str(recorded.get("head_z_mode")) == "positive_z_forward"
	_checks["records_world_latch_info"] = str(recorded.get("anchor_mode")) == "world_latched" \
		and bool(recorded.get("world_latched")) \
		and str(recorded.get("world_latch_state")) == "latched_fresh"

	fragment.record_parsed_message({"type": "empty", "sequence": 43, "targets": []})
	var empty_record: Dictionary = fragment.status_values({})
	_checks["empty_targets_do_not_clear_last_position"] = int(empty_record.get("parsed")) == 2 \
		and int(empty_record.get("sequence")) == 43 \
		and Vector3(empty_record.get("last_position")).is_equal_approx(Vector3(1.0, 2.0, 3.0)) \
		and bool(empty_record.get("world_from_head_applied")) == true

	var no_head_info_message := {
		"type": "proxy_targets",
		"sequence": 44,
		"targets": [
			{
				"target_id": "target_a",
				"transform": {"position": [2.0, 3.0, 4.0]},
			}
		],
	}
	fragment.record_parsed_message(no_head_info_message)
	var no_head_info_record: Dictionary = fragment.status_values({})
	_checks["valid_target_without_head_info_resets_head_flag"] = int(no_head_info_record.get("parsed")) == 3 \
		and int(no_head_info_record.get("sequence")) == 44 \
		and Vector3(no_head_info_record.get("last_position")).is_equal_approx(Vector3(2.0, 3.0, 4.0)) \
		and bool(no_head_info_record.get("world_from_head_applied")) == false \
		and Vector3(no_head_info_record.get("local_position")).is_equal_approx(Vector3(0.1, 0.2, 0.3)) \
		and Vector3(no_head_info_record.get("runtime_local_position")).is_equal_approx(Vector3(0.1, 0.2, -0.3)) \
		and Vector3(no_head_info_record.get("world_position")).is_equal_approx(Vector3(4.0, 5.0, 6.0))

	var targets := {"b": {}, "a": {}, "c": {}}
	_checks["proxy_count_accepts_dictionary_only"] = fragment_script.proxy_target_count(targets) == 3 \
		and fragment_script.proxy_target_count([]) == 0
	_checks["proxy_ids_are_sorted"] = fragment_script.proxy_target_ids(targets) == ["a", "b", "c"] \
		and fragment_script.proxy_target_ids([]) == []

	_checks["vector3_from_status_array_uses_fallback"] = fragment_script.vector3_from_status_array([7.0, 8.0, 9.0], Vector3.ZERO).is_equal_approx(Vector3(7.0, 8.0, 9.0)) \
		and fragment_script.vector3_from_status_array([1.0], Vector3(2.0, 3.0, 4.0)).is_equal_approx(Vector3(2.0, 3.0, 4.0))

	var status: Dictionary = fragment.status_values({
		"ws_connected": true,
		"ws_subscribed": false,
		"ws_url": "ws://probe",
		"attachments": 2,
		"card_target_id": "CardAnchor",
		"proxy_target_count": 3,
		"proxy_target_ids": ["a", "b", "c"],
		"card_resolved_position": Vector3(10.0, 11.0, 12.0),
		"card_node_position": Vector3(13.0, 14.0, 15.0),
		"card_apply_count": 5,
		"packets": 8,
		"live": 13,
		"packet_bytes": 21,
	})
	_checks["status_values_preserve_contract"] = status.keys() == [
		"ws_connected",
		"ws_subscribed",
		"ws_url",
		"attachments",
		"card_target_id",
		"proxy_target_count",
		"proxy_target_ids",
		"last_position",
		"card_resolved_position",
		"card_node_position",
		"card_apply_count",
		"packets",
		"parsed",
		"live",
		"sequence",
		"packet_bytes",
		"packet_preview",
		"message_type",
		"source_coordinate",
		"world_from_head_applied",
		"local_position",
		"runtime_local_position",
		"world_position",
		"head_z_mode",
		"anchor_mode",
		"world_latched",
		"world_latch_state",
		"error",
	] and bool(status.get("ws_connected")) and int(status.get("packets")) == 8 \
		and int(status.get("parsed")) == 3 and int(status.get("live")) == 13

	return "-"


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
		"harness": "script_only_proxy_targets_status_fragment_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_PROXY_TARGETS_STATUS_FRAGMENT_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("proxy_targets_status_fragment_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
