extends Node
class_name AssistantUpdatesReceiver

## Minimal assistant_updates WebSocket receiver boundary.
##
## Transport stays injected and text-only. This node wires WSTransport packets
## into AssistantCardState and refreshes AssistantCardView from the resulting
## snapshot.

const STREAM_NAME := "assistant_updates"

var _state = null
var _view = null
var _transport = null
var _packets_received := 0
var _packets_applied := 0
var _last_error := "-"


func bind(assistant_state, assistant_view = null) -> void:
	_state = assistant_state
	_view = assistant_view


func set_transport(transport) -> void:
	_transport = transport
	if _transport == null:
		return
	_transport.set_on_packet(_on_packet)
	_transport.set_subscribe_payload(JSON.stringify({"type": "subscribe", "stream": STREAM_NAME}))


func connect_to(url: String) -> int:
	if _transport == null:
		_last_error = "transport_unbound"
		return ERR_UNCONFIGURED
	return _transport.connect_to(url)


func poll(delta: float) -> void:
	if _transport != null:
		_transport.poll(delta)


func apply_packet(payload: String) -> bool:
	return _on_packet(payload)


func packets_received() -> int:
	return _packets_received


func packets_applied() -> int:
	return _packets_applied


func last_error() -> String:
	return _last_error


func _on_packet(payload: String) -> bool:
	_packets_received += 1
	if _state == null or not _state.has_method("apply_assistant_card_json"):
		_last_error = "state_unbound"
		return false
	var applied := bool(_state.apply_assistant_card_json(payload))
	if not applied:
		_last_error = str(_state.last_error()) if _state.has_method("last_error") else "payload_invalid"
		return false
	_packets_applied += 1
	_last_error = "-"
	if _view != null and _view.has_method("update_from_snapshot") and _state.has_method("snapshot"):
		_view.update_from_snapshot(_state.snapshot())
	return true
