extends SceneTree

## Script-only runtime probe for tracked_target_card_receiver.gd (D2 Phase C
## Receiver seam). Drives the live-payload apply path through the seam into a
## real TrackedTargetCardState + ProxyTargetsStatusFragment, using fakes for the
## proxy_targets scene pipeline (consumer/adapter/target_source) and a real
## WSTransport for the transport accessors. Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with:
##   SMARTXR_CARD_RECEIVER_SCRIPT     abs path to tracked_target_card_receiver.gd
##   SMARTXR_CARD_STATE_SCRIPT        abs path to tracked_target_card_state.gd
##   SMARTXR_STATUS_FRAGMENT_SCRIPT   abs path to proxy_targets_status_fragment.gd
##   SMARTXR_WS_TRANSPORT_SCRIPT      abs path to ws_transport.gd
##   SMARTXR_CARD_RECEIVER_PROBE_STATUS_PATH  abs path for result JSON (optional)

const DEFAULT_STATUS_RES := "user://tracked_target_card_receiver_probe_status.json"

var _checks := {}
var _error := "-"
var _exit_code := 1
var _commands := []


# Fake ProxyTargetsTargetSource: mimics target_source.gd's ProxyTargetsTargetSource
# (calls on_message_parsed first, then reports a configurable apply result/error).
class FakeTargetSource:
	var applied := true
	var error := "-"
	var last_message := {}
	var _on_message_parsed := Callable()

	func set_on_message_parsed(cb: Callable) -> void:
		_on_message_parsed = cb

	func apply_proxy_targets_json(payload: String) -> bool:
		# A realistic envelope: a non-empty targets array with a transform so the
		# status fragment records position + head->world info (it skips both for
		# empty targets). raw kept for traceability.
		last_message = {
			"type": "proxy_targets",
			"sequence": 1,
			"targets": [{"transform": {"position": [1.0, 2.0, 3.0]}}],
			"raw": payload,
		}
		if _on_message_parsed.is_valid():
			_on_message_parsed.call(last_message)
		return applied

	func last_error() -> String:
		return error


# Fake ProxyTargetsConsumer: only the two read methods the receiver touches.
class FakeConsumer:
	var proxies := {}
	var applied_info := {}

	func get_proxy_targets() -> Dictionary:
		return proxies

	func get_last_applied_target_info() -> Dictionary:
		return applied_info


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


func _record_command(command: String) -> void:
	_commands.append(command)


func _sanitize(payload: String) -> String:
	return "S:" + payload


func _run_checks() -> String:
	var receiver_path := OS.get_environment("SMARTXR_CARD_RECEIVER_SCRIPT")
	if receiver_path.is_empty():
		return "missing_env:SMARTXR_CARD_RECEIVER_SCRIPT"
	var state_path := OS.get_environment("SMARTXR_CARD_STATE_SCRIPT")
	if state_path.is_empty():
		return "missing_env:SMARTXR_CARD_STATE_SCRIPT"
	var fragment_path := OS.get_environment("SMARTXR_STATUS_FRAGMENT_SCRIPT")
	if fragment_path.is_empty():
		return "missing_env:SMARTXR_STATUS_FRAGMENT_SCRIPT"
	var transport_path := OS.get_environment("SMARTXR_WS_TRANSPORT_SCRIPT")
	if transport_path.is_empty():
		return "missing_env:SMARTXR_WS_TRANSPORT_SCRIPT"

	var receiver_script = load(receiver_path)
	var state_script = load(state_path)
	var fragment_script = load(fragment_path)
	var transport_script = load(transport_path)
	if receiver_script == null or state_script == null or fragment_script == null or transport_script == null:
		return "load_failed"
	_checks["scripts_load"] = true

	var state = state_script.new()
	state.bind(fragment_script.new())
	var transport = transport_script.new()

	var receiver = receiver_script.new()
	receiver.bind(transport, state)
	receiver.set_on_command(_record_command)
	receiver.set_packet_sanitizer(_sanitize)

	# Transport accessors default to safe values before any connection.
	_checks["ws_accessors_default"] = (
		receiver.ws_connected() == false
		and receiver.ws_subscribed() == false
		and receiver.packets_seen() == 0
		and receiver.last_packet_bytes() == 0
	)

	# Without a pipeline, apply records the adapter_null error and emits no command.
	receiver.apply_live_payload("{}")
	var no_pipeline_values: Dictionary = state.status_values({})
	_checks["adapter_null_error"] = str(no_pipeline_values.get("error", "")) == "adapter_null"
	_checks["adapter_null_no_command"] = _commands.is_empty()

	# Wire the fake pipeline; the receiver also wires on_message_parsed back.
	var consumer := FakeConsumer.new()
	consumer.proxies = {"t1": null, "t2": null}
	consumer.applied_info = {"target_id": "t1", "world_from_head_applied": true}
	var target_source := FakeTargetSource.new()
	receiver.set_proxy_pipeline(consumer, null, target_source)

	# Read accessors forward to the consumer.
	_checks["proxy_dictionary_forwards"] = receiver.proxy_targets_dictionary().size() == 2
	_checks["head_info_forwards"] = str(receiver.head_to_world_info().get("target_id", "")) == "t1"

	# Happy path: applied=true -> live counter, "-" error, "proxy_live", parsed recorded.
	target_source.applied = true
	target_source.error = "-"
	receiver.apply_live_payload("{\"type\":\"proxy_targets\"}")
	var live_values: Dictionary = state.status_values({})
	_checks["live_preview_sanitized"] = str(live_values.get("packet_preview", "")) == "S:{\"type\":\"proxy_targets\"}"
	_checks["live_counter_incremented"] = int(live_values.get("live", 0)) == 1
	_checks["live_error_cleared"] = str(live_values.get("error", "")) == "-"
	_checks["live_command"] = _commands.size() == 1 and _commands[-1] == "proxy_live"
	_checks["live_message_parsed"] = int(live_values.get("parsed", 0)) == 1
	_checks["live_head_recorded"] = bool(live_values.get("world_from_head_applied", false))

	# json_invalid: message_type "invalid", error json_invalid, command proxy_live_invalid.
	target_source.applied = false
	target_source.error = "json_invalid"
	receiver.apply_live_payload("not-json")
	var invalid_values: Dictionary = state.status_values({})
	_checks["invalid_message_type"] = str(invalid_values.get("message_type", "")) == "invalid"
	_checks["invalid_error"] = str(invalid_values.get("error", "")) == "json_invalid"
	_checks["invalid_command"] = _commands[-1] == "proxy_live_invalid"
	_checks["invalid_no_live_increment"] = int(invalid_values.get("live", 0)) == 1

	# apply failed (non-json error): error passthrough, command proxy_live_failed.
	target_source.applied = false
	target_source.error = "apply_failed"
	receiver.apply_live_payload("{\"type\":\"proxy_targets\"}")
	var failed_values: Dictionary = state.status_values({})
	_checks["failed_error"] = str(failed_values.get("error", "")) == "apply_failed"
	_checks["failed_command"] = _commands[-1] == "proxy_live_failed"

	# setup_transport must not crash and leaves the transport unsubscribed.
	receiver.setup_transport(Callable(), func(): return "ws://127.0.0.1:8766/proxy_targets")
	_checks["setup_transport_safe"] = receiver.ws_subscribed() == false
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
		"harness": "script_only_tracked_target_card_receiver_probe",
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
	print("tracked_target_card_receiver_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
