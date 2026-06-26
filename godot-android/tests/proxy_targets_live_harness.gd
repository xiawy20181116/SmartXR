extends SceneTree


class HarnessCardWrapper:
	extends Node

	var registered_targets := {}
	var attachments := {}

	func register_node3d_target(target_id: String, node_or_path) -> bool:
		registered_targets[target_id] = node_or_path
		return true

	func attach_to_target(card_id: String, target_id: String, offset_rule = {}) -> bool:
		attachments[card_id] = {
			"target_id": target_id,
			"offset_rule": offset_rule
		}
		return true


var _ws := WebSocketPeer.new()
var _harness_root := Node3D.new()
var _consumer_script: Script = null
var _adapter_script: Script = null
var _consumer: Node = null
var _adapter: Node = null
var _card_wrapper := HarnessCardWrapper.new()
var _ws_url := "ws://127.0.0.1:8766/proxy_targets"
var _require := "live"
var _status_res := "user://proxy_targets_live_status.json"
var _timeout_seconds := 10.0
var _elapsed := 0.0
var _connect_attempts := 0
var _last_connect_error := OK
var _subscribed := false
var _packets := 0
var _parsed := 0
var _live := 0
var _sequence := -1
var _packet_bytes := 0
var _packet_preview := "-"
var _message_type := "-"
var _error := "-"
var _last_depth_source := "-"
var _last_depth_confidence := "-"


func _initialize() -> void:
	_ws_url = _env_string("PROXY_TARGETS_WS_URL", _ws_url)
	_require = _env_string("PROXY_TARGETS_REQUIRE", _require)
	_status_res = _env_string("PROXY_TARGETS_STATUS_RES", _status_res)
	_timeout_seconds = _env_float("PROXY_TARGETS_TIMEOUT_SEC", _timeout_seconds)
	_write_status()

	root.add_child(_harness_root)
	_consumer_script = _load_script_from_env("PROXY_TARGETS_CONSUMER_SCRIPT", "res://scripts/proxy_targets_consumer.gd")
	_adapter_script = _load_script_from_env("PROXY_TARGETS_CARD_ADAPTER_SCRIPT", "res://scripts/proxy_targets_card_adapter.gd")
	if _consumer_script == null or _adapter_script == null:
		_write_status()
		quit(1)
		return

	_consumer = _consumer_script.new()
	_adapter = _adapter_script.new()
	_harness_root.add_child(_consumer)
	_harness_root.add_child(_adapter)
	_harness_root.add_child(_card_wrapper)
	_adapter.bind(_consumer, _card_wrapper)

	_connect_ws()
	_write_status()


func _process(delta: float) -> bool:
	_elapsed += delta
	_connect_ws()
	_ws.poll()
	_poll_ws_packets()
	_write_status()

	if _require_is_met():
		quit(0)
		return true
	if _elapsed >= _timeout_seconds:
		if _error == "-":
			_error = "timeout"
		_write_status()
		quit(1)
		return true
	return false


func _connect_ws() -> void:
	var state := _ws.get_ready_state()
	if state == WebSocketPeer.STATE_CONNECTING or state == WebSocketPeer.STATE_OPEN:
		return

	_connect_attempts += 1
	_subscribed = false
	_last_connect_error = _ws.connect_to_url(_ws_url)
	if _last_connect_error != OK:
		_error = "connect_failed:%d" % _last_connect_error


func _poll_ws_packets() -> void:
	if _ws.get_ready_state() == WebSocketPeer.STATE_OPEN and not _subscribed:
		_ws.send_text('{"type":"subscribe","stream":"proxy_targets"}')
		_subscribed = true

	while _ws.get_available_packet_count() > 0:
		var packet := _ws.get_packet()
		_packets += 1
		_packet_bytes = packet.size()
		var payload := packet.get_string_from_utf8()
		_packet_preview = _sanitize_preview(payload)
		_apply_payload(payload)


func _apply_payload(payload: String) -> void:
	var parsed = JSON.parse_string(payload)
	if typeof(parsed) != TYPE_DICTIONARY:
		_error = "json_invalid"
		return

	_parsed += 1
	_message_type = str(parsed.get("type", "-"))
	_sequence = int(parsed.get("sequence", _sequence))
	_error = "-"
	_update_depth_status(parsed)

	if _adapter.apply_proxy_targets_message(parsed):
		_live += 1
	else:
		_error = "apply_failed"


func _require_is_met() -> bool:
	if _require == "packets":
		return _packets > 0
	if _require == "parsed":
		return _parsed > 0
	return _live > 0 and _card_wrapper.registered_targets.size() > 0 and _card_wrapper.attachments.size() > 0


func _write_status() -> void:
	var status := {
		"harness": "proxy_targets_live",
		"ws_url": _ws_url,
		"ws_state": _ws.get_ready_state(),
		"ws_connected": _ws.get_ready_state() == WebSocketPeer.STATE_OPEN,
		"ws_subscribed": _subscribed,
		"connect_attempts": _connect_attempts,
		"last_connect_error": _last_connect_error,
		"require": _require,
		"packets": _packets,
		"parsed": _parsed,
		"live": _live,
		"sequence": _sequence,
		"packet_bytes": _packet_bytes,
		"packet_preview": _packet_preview,
		"message_type": _message_type,
		"depth_source": _last_depth_source,
		"depth_confidence": _last_depth_confidence,
		"error": _error,
		"registered_targets": _card_wrapper.registered_targets.size(),
		"attachments": _card_wrapper.attachments.size()
	}
	var file := FileAccess.open(_status_res, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))


func _update_depth_status(message: Dictionary) -> void:
	var targets = message.get("targets", [])
	if typeof(targets) != TYPE_ARRAY:
		return
	for target in targets:
		if typeof(target) != TYPE_DICTIONARY:
			continue
		_last_depth_source = str(target.get("depth_source", "-"))
		_last_depth_confidence = str(target.get("depth_confidence", "-"))
		return


func _env_string(name: String, fallback: String) -> String:
	var value := OS.get_environment(name)
	if value == "":
		return fallback
	return value


func _env_float(name: String, fallback: float) -> float:
	var value := OS.get_environment(name)
	if value == "":
		return fallback
	return float(value)


func _load_script_from_env(name: String, fallback: String) -> Script:
	var path := _env_string(name, fallback)
	if path.begins_with("res://") or path.begins_with("user://"):
		var resource := load(path)
		if resource is Script:
			return resource
		_error = "script_load_failed:%s" % name
		return null

	var source := FileAccess.get_file_as_string(path)
	if source == "":
		_error = "script_read_failed:%s" % name
		return null

	var script := GDScript.new()
	script.source_code = source
	var reload_error := script.reload()
	if reload_error != OK:
		_error = "script_compile_failed:%s:%d" % [name, reload_error]
		return null
	return script


func _sanitize_preview(value: String) -> String:
	var preview := value.replace("\r", " ").replace("\n", " ")
	if preview.length() > 180:
		return preview.substr(0, 180)
	return preview
