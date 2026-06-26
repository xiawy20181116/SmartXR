extends SceneTree


const STAGE_CONSUMER_LOAD := "consumer_load"
const STAGE_CONSUMER_INSTANCE := "consumer_instance"
const STAGE_ADAPTER_INSTANCE := "adapter_instance"
const STAGE_APPLY := "apply"


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
var _root := Node3D.new()
var _card_wrapper := HarnessCardWrapper.new()
var _consumer_script: Script = null
var _adapter_script: Script = null
var _consumer: Node = null
var _adapter: Node = null
var _ws_url := "ws://127.0.0.1:8766/proxy_targets"
var _status_res := "user://script_only_websocket_staged_probe_status.json"
var _stage := STAGE_APPLY
var _timeout_seconds := 5.0
var _elapsed := 0.0
var _connect_error := OK
var _setup_ok := false
var _subscribed := false
var _packets := 0
var _parsed := 0
var _live := 0
var _packet_bytes := 0
var _packet_preview := "-"
var _sequence := -1
var _error := "-"
var _last_depth_source := "-"
var _last_depth_confidence := "-"


func _initialize() -> void:
	_ws_url = _env_string("PROXY_TARGETS_WS_URL", _ws_url)
	_status_res = _env_string("PROXY_TARGETS_STAGE_STATUS_RES", _status_res)
	_stage = _env_string("PROXY_TARGETS_STAGE", _stage)
	_timeout_seconds = _env_float("PROXY_TARGETS_STAGE_TIMEOUT_SEC", _timeout_seconds)

	root.add_child(_root)
	_root.add_child(_card_wrapper)
	_setup_ok = _setup_stage()

	if _setup_ok:
		_connect_error = _ws.connect_to_url(_ws_url)
		if _connect_error != OK:
			_error = "connect_failed:%d" % _connect_error
	_write_status()


func _process(delta: float) -> bool:
	_elapsed += delta
	_ws.poll()
	_poll_ws_packets()
	_write_status()

	if _stage_target_met():
		quit(0)
		return true
	if _elapsed >= _timeout_seconds:
		if _error == "-":
			_error = "timeout"
		_write_status()
		quit(1)
		return true
	return false


func _setup_stage() -> bool:
	if _stage not in [STAGE_CONSUMER_LOAD, STAGE_CONSUMER_INSTANCE, STAGE_ADAPTER_INSTANCE, STAGE_APPLY]:
		_error = "unknown_stage:%s" % _stage
		return false

	_consumer_script = _load_script_from_env("PROXY_TARGETS_CONSUMER_SCRIPT", "res://scripts/proxy_targets_consumer.gd")
	if _consumer_script == null:
		return false
	if _stage == STAGE_CONSUMER_LOAD:
		return true

	_consumer = _consumer_script.new()
	_root.add_child(_consumer)
	if _stage == STAGE_CONSUMER_INSTANCE:
		return true

	_adapter_script = _load_script_from_env("PROXY_TARGETS_CARD_ADAPTER_SCRIPT", "res://scripts/proxy_targets_card_adapter.gd")
	if _adapter_script == null:
		return false
	_adapter = _adapter_script.new()
	_root.add_child(_adapter)
	_adapter.bind(_consumer, _card_wrapper)
	return true


func _poll_ws_packets() -> void:
	if not _setup_ok:
		return
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
	var parsed: Variant = JSON.parse_string(payload)
	if typeof(parsed) != TYPE_DICTIONARY:
		_error = "json_invalid"
		return

	_parsed += 1
	_sequence = int(parsed.get("sequence", _sequence))
	_error = "-"
	_update_depth_status(parsed)

	if _stage == STAGE_APPLY:
		if _adapter != null and _adapter.apply_proxy_targets_message(parsed):
			_live += 1
		else:
			_error = "apply_failed"


func _stage_target_met() -> bool:
	if not _setup_ok:
		return false
	if _stage == STAGE_APPLY:
		return _live > 0 and _card_wrapper.registered_targets.size() > 0 and _card_wrapper.attachments.size() > 0
	return _packets > 0


func _write_status() -> void:
	var status := {
		"harness": "script_only_websocket_staged_probe",
		"stage": _stage,
		"setup_ok": _setup_ok,
		"ws_url": _ws_url,
		"ws_state": _ws.get_ready_state(),
		"ws_connected": _ws.get_ready_state() == WebSocketPeer.STATE_OPEN,
		"ws_subscribed": _subscribed,
		"connect_error": _connect_error,
		"packets": _packets,
		"parsed": _parsed,
		"live": _live,
		"packet_bytes": _packet_bytes,
		"packet_preview": _packet_preview,
		"sequence": _sequence,
		"depth_source": _last_depth_source,
		"depth_confidence": _last_depth_confidence,
		"registered_targets": _card_wrapper.registered_targets.size(),
		"attachments": _card_wrapper.attachments.size(),
		"elapsed": _elapsed,
		"error": _error
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


func _sanitize_preview(value: String) -> String:
	var preview := value.replace("\r", " ").replace("\n", " ")
	if preview.length() > 180:
		return preview.substr(0, 180)
	return preview
