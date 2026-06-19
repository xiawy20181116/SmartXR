extends RefCounted

## Receiver glue for the tracked-card proxy_targets path.
##
## Owns transport -> target source -> status fragment flow. The host injects
## URL/enable providers and scene callbacks so XR lifecycle stays host-side.

var _ws = null
var _status_fragment = null
var _target_source = null
var _ws_url_provider := Callable()
var _ws_enabled_provider := Callable()
var _last_command_callback := Callable()
var _head_info_provider := Callable()
var _messages_seen := 0


func setup(config: Dictionary) -> void:
	_ws = config.get("ws", null)
	_status_fragment = config.get("status_fragment", null)
	_target_source = config.get("target_source", null)
	_ws_url_provider = config.get("ws_url_provider", Callable())
	_ws_enabled_provider = config.get("ws_enabled_provider", Callable())
	_last_command_callback = config.get("last_command_callback", Callable())
	_head_info_provider = config.get("head_info_provider", Callable())
	if _ws != null:
		_ws.set_on_packet(_on_ws_packet)
		_ws.set_subscribe_payload(JSON.stringify({"type": "subscribe", "stream": "proxy_targets"}))
		_ws.set_on_connect_error(_on_ws_connect_error)
		_ws.set_url_provider(_ws_url)
	if _target_source != null:
		_target_source.set_on_message_parsed(_on_message_parsed)


func connect_if_enabled() -> void:
	if not _ws_enabled():
		return
	if _ws != null:
		_ws.connect_to(_ws_url())


func poll(delta: float) -> void:
	if not _ws_enabled():
		return
	if _ws != null:
		_ws.poll(delta)


func apply_live_payload(payload: String) -> bool:
	if _target_source == null:
		_set_error("adapter_null")
		return false
	var applied: bool = bool(_target_source.apply_proxy_targets_json(payload))
	var source_error := str(_target_source.last_error())
	if source_error == "json_invalid":
		if _status_fragment != null:
			_status_fragment.set_message_type("invalid")
		_set_error("json_invalid")
		_set_last_command("proxy_live_invalid")
		return false
	if applied:
		_messages_seen += 1
		_set_error("-")
		_set_last_command("proxy_live")
		return true
	_set_error(source_error)
	_set_last_command("proxy_live_failed")
	return false


func status_values(extra := {}) -> Dictionary:
	var base := {}
	if _status_fragment != null:
		base = _status_fragment.status_values({
			"ws_connected": _ws.ws_connected() if _ws != null else false,
			"ws_subscribed": _ws.ws_subscribed() if _ws != null else false,
			"ws_url": _ws_url(),
			"packets": _ws.packets_seen() if _ws != null else 0,
			"live": _messages_seen,
			"packet_bytes": _ws.last_packet_bytes() if _ws != null else 0,
		})
	if typeof(extra) == TYPE_DICTIONARY:
		for key in extra:
			base[key] = extra[key]
	return base


func target_source():
	return _target_source


func live_messages() -> int:
	return _messages_seen


func _on_ws_packet(payload: String) -> void:
	if _status_fragment != null:
		_status_fragment.set_packet_preview(_sanitize_status_text(payload))
	apply_live_payload(payload)


func _on_message_parsed(message: Dictionary) -> void:
	if _status_fragment == null:
		return
	var head_info := {}
	if _head_info_provider.is_valid():
		var provided = _head_info_provider.call()
		if typeof(provided) == TYPE_DICTIONARY:
			head_info = provided
	_status_fragment.record_parsed_message(message, head_info)


func _on_ws_connect_error(result: int) -> void:
	_set_last_command("proxy_ws_connect_err_" + str(result))


func _ws_enabled() -> bool:
	if _ws_enabled_provider.is_valid():
		return bool(_ws_enabled_provider.call())
	return true


func _ws_url() -> String:
	if _ws_url_provider.is_valid():
		return str(_ws_url_provider.call())
	return ""


func _set_error(error: String) -> void:
	if _status_fragment != null:
		_status_fragment.set_error(error)


func _set_last_command(command: String) -> void:
	if _last_command_callback.is_valid():
		_last_command_callback.call(command)


func _sanitize_status_text(text: String) -> String:
	return text.replace("\r", " ").replace("\n", " ").left(160)
