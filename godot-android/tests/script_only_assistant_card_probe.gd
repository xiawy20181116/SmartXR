extends SceneTree

## Script-only runtime probe for the Godot MR assistant-card state/view loop.
##
## Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with scripts injected via env:
##   SMARTXR_ASSISTANT_CARD_STATE_SCRIPT
##   SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT
##   SMARTXR_ASSISTANT_CARD_PROBE_STATUS_PATH

const DEFAULT_STATUS_RES := "user://assistant_card_probe_status.json"

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
	var state_script_path := OS.get_environment("SMARTXR_ASSISTANT_CARD_STATE_SCRIPT")
	if state_script_path.is_empty():
		return "missing_env:SMARTXR_ASSISTANT_CARD_STATE_SCRIPT"
	var view_script_path := OS.get_environment("SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT")
	if view_script_path.is_empty():
		return "missing_env:SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT"

	var state_script = load(state_script_path)
	if state_script == null:
		return "load_failed:" + state_script_path
	var view_script = load(view_script_path)
	if view_script == null:
		return "load_failed:" + view_script_path
	_checks["scripts_load"] = true

	var state = state_script.new()
	var valid_payload := {
		"type": "assistant_card",
		"schema_version": 1,
		"card_id": "CardAnchor",
		"target_id": "person-ada",
		"assistant_state": "responding",
		"response_text": "Ada is working on XR-42.",
		"tool_summary": {
			"status_line": "Ada Lovelace | XR-42 | In Progress",
		},
		"person": {
			"id": "person-ada",
			"display_name": "Ada Lovelace",
		},
		"issue": {
			"key": "XR-42",
			"summary": "Prepare MR assistant demo",
		},
	}
	_checks["valid_payload_updates_snapshot"] = state.apply_assistant_card_message(valid_payload)
	var snapshot: Dictionary = state.snapshot()
	_checks["snapshot_card_id"] = str(snapshot.get("card_id", "")) == "CardAnchor"
	_checks["snapshot_target_id"] = str(snapshot.get("target_id", "")) == "person-ada"
	_checks["snapshot_response_text"] = str(snapshot.get("response_text", "")) == "Ada is working on XR-42."
	_checks["snapshot_tool_summary"] = str(snapshot.get("tool_summary", {}).get("status_line", "")) == "Ada Lovelace | XR-42 | In Progress"

	var invalid_payload := valid_payload.duplicate(true)
	invalid_payload["card_id"] = ""
	_checks["invalid_payload_sets_error"] = not state.apply_assistant_card_message(invalid_payload) and state.last_error() == "card_id_empty"

	var parent := Node3D.new()
	var view = view_script.new()
	var label = view.build_card_label(parent)
	view.update_from_snapshot(snapshot)
	var label_text := str(label.text)
	_checks["view_renders_response_text"] = label_text.contains("Ada is working on XR-42.")
	_checks["view_renders_status_line"] = label_text.contains("Ada Lovelace | XR-42 | In Progress")
	_checks["view_label_parented"] = label.get_parent() == parent

	parent.free()
	view.free()
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
		"harness": "script_only_assistant_card_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_ASSISTANT_CARD_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("assistant_card_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
