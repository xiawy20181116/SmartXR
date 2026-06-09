extends SceneTree


var _tcp := StreamPeerTCP.new()
var _host := "127.0.0.1"
var _port := 8766
var _status_res := "user://script_only_tcp_probe_status.json"
var _timeout_seconds := 5.0
var _elapsed := 0.0
var _connect_error := OK
var _error := "-"


func _initialize() -> void:
	_host = _env_string("PROXY_TARGETS_TCP_HOST", _host)
	_port = _env_int("PROXY_TARGETS_TCP_PORT", _port)
	_status_res = _env_string("PROXY_TARGETS_TCP_STATUS_RES", _status_res)
	_timeout_seconds = _env_float("PROXY_TARGETS_TCP_TIMEOUT_SEC", _timeout_seconds)

	_connect_error = _tcp.connect_to_host(_host, _port)
	if _connect_error != OK:
		_error = "connect_failed:%d" % _connect_error
	_write_status()


func _process(delta: float) -> bool:
	_elapsed += delta
	_tcp.poll()
	_write_status()

	if _tcp.get_status() == StreamPeerTCP.STATUS_CONNECTED:
		quit(0)
		return true
	if _tcp.get_status() == StreamPeerTCP.STATUS_ERROR:
		_error = "tcp_error"
		_write_status()
		quit(1)
		return true
	if _elapsed >= _timeout_seconds:
		if _error == "-":
			_error = "timeout"
		_write_status()
		quit(1)
		return true
	return false


func _write_status() -> void:
	var status := {
		"harness": "script_only_tcp_probe",
		"host": _host,
		"port": _port,
		"tcp_status": _tcp.get_status(),
		"connect_error": _connect_error,
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


func _env_int(name: String, fallback: int) -> int:
	var value := OS.get_environment(name)
	if value == "":
		return fallback
	return int(value)


func _env_float(name: String, fallback: float) -> float:
	var value := OS.get_environment(name)
	if value == "":
		return fallback
	return float(value)
