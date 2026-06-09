extends SceneTree


var _ws := WebSocketPeer.new()
var _ws_url := "ws://127.0.0.1:8766/proxy_targets"
var _status_res := "user://script_only_websocket_probe_status.json"
var _timeout_seconds := 5.0
var _elapsed := 0.0
var _connect_error := OK
var _subscribed := false
var _packets := 0
var _packet_bytes := 0
var _packet_preview := "-"
var _error := "-"


func _initialize() -> void:
	_ws_url = _env_string("PROXY_TARGETS_WS_URL", _ws_url)
	_status_res = _env_string("PROXY_TARGETS_WS_STATUS_RES", _status_res)
	_timeout_seconds = _env_float("PROXY_TARGETS_WS_TIMEOUT_SEC", _timeout_seconds)

	_connect_error = _ws.connect_to_url(_ws_url)
	if _connect_error != OK:
		_error = "connect_failed:%d" % _connect_error
	_write_status()


func _process(delta: float) -> bool:
	_elapsed += delta
	_ws.poll()
	_poll_ws_packets()
	_write_status()

	if _packets > 0:
		quit(0)
		return true
	if _elapsed >= _timeout_seconds:
		if _error == "-":
			_error = "timeout"
		_write_status()
		quit(1)
		return true
	return false


func _poll_ws_packets() -> void:
	if _ws.get_ready_state() == WebSocketPeer.STATE_OPEN and not _subscribed:
		_ws.send_text('{"type":"subscribe","stream":"proxy_targets"}')
		_subscribed = true

	while _ws.get_available_packet_count() > 0:
		var packet := _ws.get_packet()
		_packets += 1
		_packet_bytes = packet.size()
		_packet_preview = _sanitize_preview(packet.get_string_from_utf8())
		_error = "-"


func _write_status() -> void:
	var status := {
		"harness": "script_only_websocket_probe",
		"ws_url": _ws_url,
		"ws_state": _ws.get_ready_state(),
		"ws_connected": _ws.get_ready_state() == WebSocketPeer.STATE_OPEN,
		"ws_subscribed": _subscribed,
		"connect_error": _connect_error,
		"packets": _packets,
		"packet_bytes": _packet_bytes,
		"packet_preview": _packet_preview,
		"elapsed": _elapsed,
		"error": _error
	}
	var file := FileAccess.open(_status_res, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))


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
