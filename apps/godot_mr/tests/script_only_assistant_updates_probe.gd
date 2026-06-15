extends SceneTree

## Script-only runtime probe for the Godot MR assistant_updates receive path.
##
## Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with scripts injected via env:
##   SMARTXR_ASSISTANT_UPDATES_RECEIVER_SCRIPT
##   SMARTXR_ASSISTANT_CARD_STATE_SCRIPT
##   SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT
##   SMARTXR_WS_TRANSPORT_SCRIPT
##   SMARTXR_ASSISTANT_UPDATES_LIVE_WS_URL
##   SMARTXR_ASSISTANT_UPDATES_PROBE_STATUS_PATH

const DEFAULT_STATUS_RES := "user://assistant_updates_probe_status.json"
const DEFAULT_TIMEOUT_SECONDS := 8.0

var _checks := {}
var _error := "-"
var _exit_code := 1
var _started := false
var _finished := false
var _elapsed := 0.0
var _timeout_seconds := DEFAULT_TIMEOUT_SECONDS

var _live_ws_url := ""
var _receiver = null
var _transport = null
var _state = null
var _view = null
var _label: Label3D = null
var _parent: Node3D = null
var _subscribed_seen := false


func _process(delta: float) -> bool:
	if _finished:
		return true
	if not _started:
		_started = true
		var setup_error := _setup()
		if setup_error != "-":
			_error = setup_error
			return _finish()
	_elapsed += delta
	_receiver.poll(delta)
	if _transport.ws_subscribed():
		_subscribed_seen = true
	if _receiver.packets_applied() >= 1:
		_record_final_checks()
		if _all_passed():
			_exit_code = 0
		return _finish()
	if _elapsed >= _timeout_seconds:
		_error = "timeout packets_applied=%d packets_received=%d" % [
			_receiver.packets_applied(),
			_receiver.packets_received(),
		]
		_record_final_checks()
		return _finish()
	return false


func _setup() -> String:
	var receiver_script_path := OS.get_environment("SMARTXR_ASSISTANT_UPDATES_RECEIVER_SCRIPT")
	if receiver_script_path.is_empty():
		return "missing_env:SMARTXR_ASSISTANT_UPDATES_RECEIVER_SCRIPT"
	var state_script_path := OS.get_environment("SMARTXR_ASSISTANT_CARD_STATE_SCRIPT")
	if state_script_path.is_empty():
		return "missing_env:SMARTXR_ASSISTANT_CARD_STATE_SCRIPT"
	var view_script_path := OS.get_environment("SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT")
	if view_script_path.is_empty():
		return "missing_env:SMARTXR_ASSISTANT_CARD_VIEW_SCRIPT"
	var transport_script_path := OS.get_environment("SMARTXR_WS_TRANSPORT_SCRIPT")
	if transport_script_path.is_empty():
		return "missing_env:SMARTXR_WS_TRANSPORT_SCRIPT"
	_live_ws_url = OS.get_environment("SMARTXR_ASSISTANT_UPDATES_LIVE_WS_URL")
	if _live_ws_url.is_empty():
		return "missing_env:SMARTXR_ASSISTANT_UPDATES_LIVE_WS_URL"
	var timeout_env := OS.get_environment("SMARTXR_ASSISTANT_UPDATES_TIMEOUT_SEC")
	if not timeout_env.is_empty():
		_timeout_seconds = float(timeout_env)

	var receiver_script = load(receiver_script_path)
	if receiver_script == null:
		return "load_failed:" + receiver_script_path
	var state_script = load(state_script_path)
	if state_script == null:
		return "load_failed:" + state_script_path
	var view_script = load(view_script_path)
	if view_script == null:
		return "load_failed:" + view_script_path
	var transport_script = load(transport_script_path)
	if transport_script == null:
		return "load_failed:" + transport_script_path
	_checks["scripts_load"] = true

	var invalid_state = state_script.new()
	var invalid_receiver = receiver_script.new()
	invalid_receiver.bind(invalid_state)
	_checks["invalid_payload_sets_error"] = not invalid_receiver.apply_packet(JSON.stringify({
		"type": "assistant_card",
		"schema_version": 1,
		"card_id": "",
		"target_id": "person-ada",
		"assistant_state": "responding",
		"response_text": "invalid",
	})) and invalid_receiver.last_error() == "card_id_empty"

	_state = state_script.new()
	_view = view_script.new()
	_parent = Node3D.new()
	_label = _view.build_card_label(_parent)
	_transport = transport_script.new()
	_receiver = receiver_script.new()
	_receiver.bind(_state, _view)
	_receiver.set_transport(_transport)
	var connect_result: int = _receiver.connect_to(_live_ws_url)
	_checks["live_connect_accepted"] = connect_result == OK
	_checks["receiver_initially_zero_applied"] = _receiver.packets_applied() == 0
	return "-"


func _record_final_checks() -> void:
	var snapshot: Dictionary = _state.snapshot()
	var label_text := str(_label.text)
	_checks["receiver_subscribed_once_open"] = _subscribed_seen
	_checks["receiver_packets_applied"] = _receiver.packets_applied() >= 1
	_checks["receiver_packets_received"] = _receiver.packets_received() >= _receiver.packets_applied()
	_checks["live_payload_updates_snapshot"] = str(snapshot.get("response_text", "")) == "Ada is working on XR-42."
	_checks["snapshot_card_id"] = str(snapshot.get("card_id", "")) == "CardAnchor"
	_checks["snapshot_target_id"] = str(snapshot.get("target_id", "")) == "person-ada"
	_checks["view_renders_live_response"] = label_text.contains("Ada is working on XR-42.")
	_checks["view_renders_live_status"] = label_text.contains("Ada Lovelace | XR-42 | In Progress")
	_checks["receiver_last_error_clear"] = _receiver.last_error() == "-"


func _all_passed() -> bool:
	if _checks.is_empty():
		return false
	for key in _checks:
		if not _checks[key]:
			return false
	return true


func _finish() -> bool:
	_finished = true
	_write_status(_exit_code)
	quit(_exit_code)
	return true


func _write_status(exit_code: int) -> void:
	var failed := []
	for key in _checks:
		if not _checks[key]:
			failed.append(key)
	var status := {
		"harness": "script_only_assistant_updates_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
		"live_ws_url": _live_ws_url,
		"packets_received": _receiver.packets_received() if _receiver != null else 0,
		"packets_applied": _receiver.packets_applied() if _receiver != null else 0,
		"elapsed": _elapsed,
	}
	var status_path := OS.get_environment("SMARTXR_ASSISTANT_UPDATES_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("assistant_updates_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
