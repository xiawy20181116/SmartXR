extends SceneTree

## Script-only runtime probe for tracked_target_card_state.gd (D2 Phase C State
## seam). Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with:
##   SMARTXR_CARD_STATE_SCRIPT        abs path to tracked_target_card_state.gd
##   SMARTXR_STATUS_FRAGMENT_SCRIPT   abs path to proxy_targets_status_fragment.gd
##   SMARTXR_CARD_STATE_PROBE_STATUS_PATH  abs path for result JSON (optional)

const DEFAULT_STATUS_RES := "user://tracked_target_card_state_probe_status.json"

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
	var state_path := OS.get_environment("SMARTXR_CARD_STATE_SCRIPT")
	if state_path.is_empty():
		return "missing_env:SMARTXR_CARD_STATE_SCRIPT"
	var fragment_path := OS.get_environment("SMARTXR_STATUS_FRAGMENT_SCRIPT")
	if fragment_path.is_empty():
		return "missing_env:SMARTXR_STATUS_FRAGMENT_SCRIPT"

	var state_script = load(state_path)
	if state_script == null:
		return "load_failed:" + state_path
	var fragment_script = load(fragment_path)
	if fragment_script == null:
		return "load_failed:" + fragment_path
	_checks["scripts_load"] = true

	# Envelope validation (parse/validate role).
	var state = state_script.new()
	_checks["valid_envelope_ok"] = state.validate_envelope({"type": "proxy_targets", "targets": [], "cards": []}) == "-"
	_checks["non_dict_rejected"] = state.validate_envelope("nope") == "message_invalid"
	_checks["wrong_type_rejected"] = state.validate_envelope({"type": "control"}) == "type_invalid"
	_checks["bad_targets_rejected"] = state.validate_envelope({"type": "proxy_targets", "targets": {}}) == "targets_invalid"
	_checks["bad_cards_rejected"] = state.validate_envelope({"type": "proxy_targets", "cards": 5}) == "cards_invalid"

	# Counters before binding (pure data, no fragment needed).
	_checks["counters_start_zero"] = state.live_messages() == 0 and state.apply_count() == 0
	state.record_live_applied()
	state.record_live_applied()
	state.record_apply()
	_checks["counters_increment"] = state.live_messages() == 2 and state.apply_count() == 1

	# status_values injects the counters even with no fragment bound.
	var unbound_values: Dictionary = state.status_values({"packets": 7})
	_checks["unbound_status_passthrough"] = int(unbound_values.get("packets", 0)) == 7
	_checks["unbound_status_injects_counters"] = int(unbound_values.get("live", -1)) == 2 and int(unbound_values.get("card_apply_count", -1)) == 1

	# Bind a real fragment and verify delegation + the merged status layout.
	var fragment = fragment_script.new()
	state.bind(fragment)
	state.set_packet_preview("PREVIEW")
	state.set_error("json_invalid")
	state.set_message_type("invalid")
	state.record_parsed_message({
		"type": "proxy_targets",
		"sequence": 4,
		"targets": [{"transform": {"position": [1.0, 2.0, 3.0]}}],
	}, {})
	var bound_values: Dictionary = state.status_values({
		"ws_connected": true,
		"packets": 9,
	})
	_checks["bound_preview_delegates"] = str(bound_values.get("packet_preview", "")) == "PREVIEW"
	_checks["bound_message_type_delegates"] = str(bound_values.get("message_type", "")) == "proxy_targets"
	_checks["bound_error_delegates"] = str(bound_values.get("error", "")) == "json_invalid"
	_checks["bound_parsed_recorded"] = int(bound_values.get("parsed", 0)) == 1 and int(bound_values.get("sequence", 0)) == 4
	_checks["bound_position_recorded"] = bound_values.get("last_position", Vector3.ZERO) == Vector3(1.0, 2.0, 3.0)
	_checks["bound_counters_injected"] = int(bound_values.get("live", -1)) == 2 and int(bound_values.get("card_apply_count", -1)) == 1
	_checks["bound_runtime_passthrough"] = bool(bound_values.get("ws_connected", false)) and int(bound_values.get("packets", 0)) == 9
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
		"harness": "script_only_tracked_target_card_state_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_CARD_STATE_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("tracked_target_card_state_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
