extends SceneTree

## Script-only runtime probe for card_receiver.gd.

const DEFAULT_STATUS_RES := "user://card_receiver_probe_status.json"

class FakeWS:
	extends RefCounted
	var on_packet := Callable()
	var on_connect_error := Callable()
	var url_provider := Callable()
	var subscribe_payload := ""
	var connected_url := ""
	var poll_count := 0

	func set_on_packet(callback: Callable) -> void:
		on_packet = callback

	func set_subscribe_payload(payload: String) -> void:
		subscribe_payload = payload

	func set_on_connect_error(callback: Callable) -> void:
		on_connect_error = callback

	func set_url_provider(callback: Callable) -> void:
		url_provider = callback

	func connect_to(url: String) -> void:
		connected_url = url

	func poll(_delta: float) -> void:
		poll_count += 1

	func ws_connected() -> bool:
		return not connected_url.is_empty()

	func ws_subscribed() -> bool:
		return not subscribe_payload.is_empty()

	func packets_seen() -> int:
		return 3

	func last_packet_bytes() -> int:
		return 42


class FakeStatusFragment:
	extends RefCounted
	var packet_preview := "-"
	var error := "-"
	var message_type := "-"
	var parsed_head_info := {}

	func set_packet_preview(preview: String) -> void:
		packet_preview = preview

	func set_error(next_error: String) -> void:
		error = next_error

	func set_message_type(next_message_type: String) -> void:
		message_type = next_message_type

	func record_parsed_message(_message: Dictionary, head_info: Dictionary = {}) -> void:
		parsed_head_info = head_info.duplicate(true)

	func status_values(runtime_values: Dictionary) -> Dictionary:
		var status := runtime_values.duplicate(true)
		status["packet_preview"] = packet_preview
		status["error"] = error
		status["message_type"] = message_type
		return status


class FakeTargetSource:
	extends RefCounted
	var on_parsed := Callable()
	var next_error := "-"

	func set_on_message_parsed(callback: Callable) -> void:
		on_parsed = callback

	func apply_proxy_targets_json(_payload: String) -> bool:
		if next_error != "-":
			return false
		if on_parsed.is_valid():
			on_parsed.call({"type": "proxy_targets", "sequence": 7})
		return true

	func last_error() -> String:
		return next_error


var _checks := {}
var _error := "-"
var _exit_code := 1
var _last_command := "-"


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
	var script_path := OS.get_environment("SMARTXR_CARD_RECEIVER_SCRIPT")
	if script_path.is_empty():
		return "missing_env:SMARTXR_CARD_RECEIVER_SCRIPT"
	var receiver_script = load(script_path)
	if receiver_script == null:
		return "load_failed:" + script_path
	_checks["card_receiver_script_loads"] = true

	var ws := FakeWS.new()
	var fragment := FakeStatusFragment.new()
	var source := FakeTargetSource.new()
	var receiver = receiver_script.new()
	receiver.setup({
		"ws": ws,
		"status_fragment": fragment,
		"target_source": source,
		"ws_url_provider": _receiver_ws_url,
		"ws_enabled_provider": _receiver_ws_enabled,
		"last_command_callback": _record_last_command,
		"head_info_provider": _receiver_head_info,
	})
	_checks["setup_wires_transport"] = ws.on_packet.is_valid() and ws.on_connect_error.is_valid() and ws.url_provider.is_valid() and ws.subscribe_payload.contains("proxy_targets")
	receiver.connect_if_enabled()
	receiver.poll(0.1)
	_checks["connect_and_poll_use_injected_ws"] = ws.connected_url == "ws://127.0.0.1:8766/proxy_targets" and ws.poll_count == 1

	_checks["valid_payload_updates_status"] = receiver.apply_live_payload("{\"type\":\"proxy_targets\"}")
	var status: Dictionary = receiver.status_values({"attachments": 1})
	_checks["status_values_preserve_runtime_and_scene_values"] = status.get("live", 0) == 1 and status.get("attachments", 0) == 1 and status.get("packets", 0) == 3 and status.get("packet_bytes", 0) == 42
	_checks["valid_payload_records_head_info_and_command"] = fragment.parsed_head_info.get("target_id", "") == "head-target" and _last_command == "proxy_live"

	source.next_error = "json_invalid"
	_checks["invalid_payload_sets_invalid_status"] = not receiver.apply_live_payload("not json") and fragment.message_type == "invalid" and fragment.error == "json_invalid" and _last_command == "proxy_live_invalid"
	return "-"


func _receiver_ws_url() -> String:
	return "ws://127.0.0.1:8766/proxy_targets"


func _receiver_ws_enabled() -> bool:
	return true


func _receiver_head_info() -> Dictionary:
	return {"target_id": "head-target"}


func _record_last_command(command: String) -> void:
	_last_command = command


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
		"harness": "script_only_card_receiver_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_CARD_RECEIVER_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("card_receiver_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
