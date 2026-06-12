extends RefCounted
class_name WSTransport

## WebSocket transport subsystem (M3 step 3 of the YAN-73 encapsulation
## roadmap, extracted from AndroidMovingCard.gd).
##
## One instance owns one WebSocketPeer plus the shared connect/poll/retry
## behavior the card previously duplicated across its control and
## proxy_targets loops: connect_to(url), per-frame poll(delta), the 2.0 s
## retry-on-close loop, an optional subscribe-once-on-open text payload, and
## a per-packet Callable back into the card.
##
## State resolution stays in the card per ADR-4 (DECISIONS.md): the card
## resolves URLs and enable gates through SmartXROptions and passes them in
## (connect_to / set_url_provider), handles every packet payload itself
## (set_on_packet), and formats its own error strings (set_on_connect_error).
## This script only moves bytes. The url-provider Callable keeps reconnects
## byte-for-byte identical to the old loops, which re-resolved the URL
## through the card's _options on every retry.
##
## Keep this script dependency-free and loadable in no-project mode: no
## preloads, no env reads, no tree access, and never reference its own
## class_name inside this file (global class registration does not happen in
## script-only probes; see tools/run_godot_ws_transport_probe.ps1).

const RETRY_ON_CLOSE_SECONDS := 2.0

var _ws := WebSocketPeer.new()
var _url := ""
var _connected := false
var _subscribed := false
var _retry_seconds := 0.0
var _packets_seen := 0
var _last_packet_bytes := 0
var _subscribe_payload := ""
var _on_packet := Callable()
var _on_connect_error := Callable()
var _url_provider := Callable()


## Per-packet callback into the card: func(payload: String) -> void, invoked
## with each packet decoded via get_string_from_utf8(), matching both old
## loops.
func set_on_packet(on_packet: Callable) -> void:
	_on_packet = on_packet


## Optional text payload sent exactly once per connection, on the first
## OPEN poll, before draining packets (the old proxy_targets subscribe).
## Empty string means no subscribe step (the old control loop).
func set_subscribe_payload(payload: String) -> void:
	_subscribe_payload = payload


## Optional callback for connect_to_url failures: func(error: int) -> void.
## The card formats its own diagnostic string (e.g. _last_command).
func set_on_connect_error(on_connect_error: Callable) -> void:
	_on_connect_error = on_connect_error


## Optional URL resolver used by the retry loop: func() -> String. When set,
## every retry re-resolves the URL through the card (ADR-4), exactly like the
## old loops calling _control_ws_url()/_proxy_targets_ws_url() per reconnect.
## When unset, retries reuse the last connect_to(url) value.
func set_url_provider(url_provider: Callable) -> void:
	_url_provider = url_provider


func connect_to(url: String) -> int:
	_url = url
	_ws.close()
	var result := _ws.connect_to_url(url)
	_connected = false
	_subscribed = false
	_retry_seconds = 0.0
	if result != OK and _on_connect_error.is_valid():
		_on_connect_error.call(result)
	return result


func poll(delta: float) -> void:
	_ws.poll()
	var state := _ws.get_ready_state()
	_connected = state == WebSocketPeer.STATE_OPEN
	if state == WebSocketPeer.STATE_OPEN:
		_send_subscribe_once()
		while _ws.get_available_packet_count() > 0:
			var packet := _ws.get_packet()
			_packets_seen += 1
			_last_packet_bytes = packet.size()
			if _on_packet.is_valid():
				_on_packet.call(packet.get_string_from_utf8())
	elif state == WebSocketPeer.STATE_CLOSED:
		_subscribed = false
		_retry_seconds += delta
		if _retry_seconds >= RETRY_ON_CLOSE_SECONDS:
			_reconnect()


# Note: the pre-extraction card prefixed this send with a write-mode setter
# call that does not exist on Godot 4's WebSocketPeer, so the whole function
# errored at runtime on every open-state poll: the subscribe payload was
# never actually sent and ws_subscribed never flipped true (the publisher
# broadcasts regardless, which hid it).
# send_text() is the Godot 4 API for a TEXT frame and restores the documented
# subscribe-once-on-open behavior; this is the one deliberate fix in this
# extraction (verified by the runtime probe's live path).
func _send_subscribe_once() -> void:
	if _subscribe_payload.is_empty() or _subscribed:
		return
	_ws.send_text(_subscribe_payload)
	_subscribed = true


func _reconnect() -> void:
	var next_url := _url
	if _url_provider.is_valid():
		next_url = str(_url_provider.call())
	connect_to(next_url)


# Getters instead of public vars so the card-facing surface stays read-only.
# Named ws_* to avoid shadowing Object.is_connected().
func ws_connected() -> bool:
	return _connected


func ws_subscribed() -> bool:
	return _subscribed


func packets_seen() -> int:
	return _packets_seen


func last_packet_bytes() -> int:
	return _last_packet_bytes


func retry_seconds() -> float:
	return _retry_seconds


func current_url() -> String:
	return _url
