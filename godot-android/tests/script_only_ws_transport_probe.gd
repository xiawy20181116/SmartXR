extends SceneTree

## Script-only runtime probe for WSTransport (M3 step 3, YAN-76).
##
## Runs in no-project mode like the other script-only probes (a project run
## would boot the full main scene, which never exits headless):
##   godot --headless --script <abs path to this file>
## with the environment:
##   SMARTXR_WS_TRANSPORT_SCRIPT            abs path to ws_transport.gd
##   SMARTXR_WS_TRANSPORT_PROBE_STATUS_PATH abs path for the result JSON
##                                          (optional)
##   SMARTXR_WS_TRANSPORT_LIVE_WS_URL       URL of a live publisher (the
##                                          runner starts
##                                          fake_proxy_targets_publisher.py)
##   SMARTXR_WS_TRANSPORT_OFFLINE_WS_URL    URL of a TCP listener that closes
##                                          connections without completing
##                                          the WebSocket handshake (the
##                                          runner starts one; a plain closed
##                                          port does NOT work - Windows
##                                          loopback leaves the peer in
##                                          STATE_CONNECTING for seconds)
##   SMARTXR_WS_TRANSPORT_TIMEOUT_SEC       overall timeout (optional)
##
## Verifies at runtime: default state flags before any connect, the
## connect-error callback on an invalid URL, dropped-connection retry
## accumulation and the 2.0 s reconnect through the url-provider Callable
## (offline path), subscribe-once-on-open semantics (never-open transport
## stays unsubscribed; live transport flips connected+subscribed), and live
## packet delivery through the per-packet Callable with packets/bytes
## counters. Exits 0 only if every check passed.
##
## Like the target-registry probe, work starts from the first main-loop
## iteration (_process), not _initialize, and quit() is only called from
## _process (script-only mode does not honor quit() in _initialize).

const DEFAULT_STATUS_RES := "user://ws_transport_probe_status.json"
const DEFAULT_OFFLINE_WS_URL := "ws://127.0.0.1:8799/proxy_targets"
const DEFAULT_TIMEOUT_SECONDS := 8.0
# Synthetic delta fed to the offline transport so the 2.0 s retry-on-close
# threshold is crossed in a handful of frames instead of real seconds.
const SYNTHETIC_RETRY_DELTA := 0.5
const IDLE_SUBSCRIBE_POLLS := 5

var _checks := {}
var _error := "-"
var _exit_code := 1
var _started := false
var _finished := false
var _elapsed := 0.0
var _timeout_seconds := DEFAULT_TIMEOUT_SECONDS

var _live_ws_url := ""
var _offline_ws_url := DEFAULT_OFFLINE_WS_URL

var _offline = null
var _live = null
var _idle_subscribe = null
var _idle_polls := 0

var _offline_provider_calls := 0
var _offline_retry_accumulated := false
var _bad_connect_error_code := OK
var _live_payloads := 0
var _live_last_payload := ""
var _live_connected_seen := false
var _live_subscribed_seen := false


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
	_poll_transports(delta)
	if _offline_done() and _live_done():
		_record_final_checks()
		if _all_passed():
			_exit_code = 0
		return _finish()
	if _elapsed >= _timeout_seconds:
		_error = "timeout offline_done=%s live_done=%s" % [str(_offline_done()), str(_live_done())]
		_record_final_checks()
		return _finish()
	return false


func _setup() -> String:
	var transport_script_path := OS.get_environment("SMARTXR_WS_TRANSPORT_SCRIPT")
	if transport_script_path.is_empty():
		return "missing_env:SMARTXR_WS_TRANSPORT_SCRIPT"
	var transport_script = load(transport_script_path)
	if transport_script == null:
		return "load_failed:" + transport_script_path
	_checks["transport_script_loads"] = true
	_checks["transport_script_can_instantiate"] = transport_script.can_instantiate()

	_live_ws_url = OS.get_environment("SMARTXR_WS_TRANSPORT_LIVE_WS_URL")
	if _live_ws_url.is_empty():
		return "missing_env:SMARTXR_WS_TRANSPORT_LIVE_WS_URL"
	var offline_url := OS.get_environment("SMARTXR_WS_TRANSPORT_OFFLINE_WS_URL")
	if not offline_url.is_empty():
		_offline_ws_url = offline_url
	var timeout_env := OS.get_environment("SMARTXR_WS_TRANSPORT_TIMEOUT_SEC")
	if not timeout_env.is_empty():
		_timeout_seconds = float(timeout_env)

	# 1. Default state flags before any connect.
	var fresh = transport_script.new()
	_checks["default_not_connected"] = fresh.ws_connected() == false
	_checks["default_not_subscribed"] = fresh.ws_subscribed() == false
	_checks["default_zero_packets"] = fresh.packets_seen() == 0
	_checks["default_zero_packet_bytes"] = fresh.last_packet_bytes() == 0
	_checks["default_zero_retry_seconds"] = fresh.retry_seconds() == 0.0
	_checks["default_empty_url"] = fresh.current_url() == ""
	_checks["default_retry_interval_is_two_seconds"] = transport_script.RETRY_ON_CLOSE_SECONDS == 2.0

	# 2. Invalid URL: connect_to returns the error and reports it through the
	# connect-error callback (the card formats _last_command from it). The
	# scheme must be the invalid part: Godot 4.6 accepts "not a url" as a
	# host, but rejects non-ws/wss schemes synchronously.
	var bad = transport_script.new()
	bad.set_on_connect_error(_on_bad_connect_error)
	var bad_result: int = bad.connect_to("invalid://bad-scheme")
	_checks["invalid_url_returns_error"] = bad_result != OK
	_checks["invalid_url_error_callback_matches"] = _bad_connect_error_code == bad_result \
		and _bad_connect_error_code != OK
	_checks["invalid_url_not_connected"] = bad.ws_connected() == false

	# 3. Subscribe-once-on-open: a transport with a subscribe payload that
	# never reaches OPEN must never flip the subscribed flag (polled with
	# small deltas below, without crossing the retry threshold).
	_idle_subscribe = transport_script.new()
	_idle_subscribe.set_subscribe_payload(JSON.stringify({"type": "subscribe", "stream": "proxy_targets"}))

	# 4. Offline path: the runner's accept-then-close TCP listener fails the
	# WebSocket handshake, driving STATE_CLOSED -> retry accumulation -> the
	# url-provider-driven reconnect.
	_offline = transport_script.new()
	_offline.set_url_provider(_offline_url_provider)
	var offline_result: int = _offline.connect_to(_offline_ws_url)
	_checks["offline_connect_accepted"] = offline_result == OK
	_checks["offline_not_connected_before_open"] = _offline.ws_connected() == false

	# 5. Live path: subscribe payload + per-packet Callable against the fake
	# publisher started by the runner.
	_live = transport_script.new()
	_live.set_on_packet(_on_live_packet)
	_live.set_subscribe_payload(JSON.stringify({"type": "subscribe", "stream": "proxy_targets"}))
	var live_result: int = _live.connect_to(_live_ws_url)
	_checks["live_connect_accepted"] = live_result == OK
	_checks["live_not_connected_before_open"] = _live.ws_connected() == false
	return "-"


func _poll_transports(delta: float) -> void:
	_offline.poll(SYNTHETIC_RETRY_DELTA)
	if _offline.retry_seconds() > 0.0:
		_offline_retry_accumulated = true
	if _idle_polls < IDLE_SUBSCRIBE_POLLS:
		_idle_polls += 1
		_idle_subscribe.poll(0.1)
	_live.poll(delta)
	if _live.ws_connected():
		_live_connected_seen = true
	if _live.ws_subscribed():
		_live_subscribed_seen = true


func _offline_done() -> bool:
	return _offline_provider_calls >= 1


func _live_done() -> bool:
	return _live_payloads >= 1


func _record_final_checks() -> void:
	_checks["offline_retry_accumulates_while_closed"] = _offline_retry_accumulated
	_checks["offline_reconnect_uses_url_provider"] = _offline_provider_calls >= 1
	_checks["offline_retry_resets_after_reconnect"] = _offline.retry_seconds() < 2.0
	_checks["offline_never_connected"] = _offline.ws_connected() == false
	_checks["offline_no_packets"] = _offline.packets_seen() == 0
	_checks["offline_url_recorded"] = _offline.current_url() == _offline_ws_url
	_checks["idle_subscribe_stays_false_without_open"] = _idle_subscribe.ws_subscribed() == false
	_checks["live_connected_after_open"] = _live_connected_seen
	_checks["live_subscribed_once_open"] = _live_subscribed_seen
	_checks["live_packet_delivered_via_callable"] = _live_payloads >= 1
	_checks["live_packets_counter_matches_callbacks"] = _live.packets_seen() == _live_payloads
	_checks["live_last_packet_bytes_recorded"] = _live.last_packet_bytes() > 0
	_checks["live_payload_nonempty"] = not _live_last_payload.is_empty()
	_checks["live_url_recorded"] = _live.current_url() == _live_ws_url


func _offline_url_provider() -> String:
	_offline_provider_calls += 1
	return _offline_ws_url


func _on_bad_connect_error(code: int) -> void:
	_bad_connect_error_code = code


func _on_live_packet(payload: String) -> void:
	_live_payloads += 1
	_live_last_payload = payload


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
		"harness": "script_only_ws_transport_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
		"live_ws_url": _live_ws_url,
		"offline_ws_url": _offline_ws_url,
		"live_packets": _live_payloads,
		"offline_provider_calls": _offline_provider_calls,
		"elapsed": _elapsed,
	}
	var status_path := OS.get_environment("SMARTXR_WS_TRANSPORT_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("ws_transport_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
