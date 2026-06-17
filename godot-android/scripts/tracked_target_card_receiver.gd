extends RefCounted
class_name TrackedTargetCardReceiver

## Module-2 Receiver seam for the tracked-target card (D2 Phase C, §16). Mirrors
## the assistant trio's AssistantUpdatesReceiver: boundary glue that wires
## transport -> state -> card. It composes the existing proxy_targets pieces:
##   - ws_transport.gd                 (the proxy_targets WebSocketPeer loop)
##   - proxy_targets_consumer.gd       (transform -> Node3D proxies, head->world)
##   - proxy_targets_card_adapter.gd   (register proxies + attach card)
##   - target_source.gd ProxyTargetsTargetSource (json -> consumer/adapter)
##
## AndroidMovingCard still builds the consumer/adapter/target_source scene nodes
## (via validation_scene_builder, which needs res:// factories + the tree) and
## injects them here; the host also owns last_command, attachment lookup, and
## node positions. This seam owns the live-payload apply path that used to live
## inline in the card (_apply_proxy_targets_live_payload + the packet/connect
## error handlers) and records results into TrackedTargetCardState, emitting the
## host's last_command strings through an injected callback (ADR-4).
##
## Keep this script dependency-free and loadable in no-project mode: no preloads,
## no env reads, no tree access of its own, and never reference its own
## class_name inside this file (see tools/run_godot_tracked_target_card_receiver_probe.ps1).

const STREAM_NAME := "proxy_targets"

var _transport = null
var _consumer = null
var _adapter = null
var _target_source = null
var _card_state = null
var _on_command := Callable()
var _packet_sanitizer := Callable()


func bind(transport, card_state) -> void:
	_transport = transport
	_card_state = card_state


## Injected after the host builds the proxy_targets scene pipeline through
## validation_scene_builder. The target_source's parsed-message callback is
## wired here so head->world recording stays in this seam.
func set_proxy_pipeline(consumer, adapter, target_source) -> void:
	_consumer = consumer
	_adapter = adapter
	_target_source = target_source
	if _target_source != null and _target_source.has_method("set_on_message_parsed"):
		_target_source.set_on_message_parsed(_on_message_parsed)


## func(command: String) -> void; the host assigns its _last_command. Keeps
## last_command ownership on the host while the seam reports the exact strings.
func set_on_command(on_command: Callable) -> void:
	_on_command = on_command


## func(raw: String) -> String; the host injects StatusHud.sanitize_status_text.
## Defaults to identity so the seam stays loadable without the preload.
func set_packet_sanitizer(sanitizer: Callable) -> void:
	_packet_sanitizer = sanitizer


## Wires the transport callbacks. url_provider / on URL resolution stays on the
## host (it owns _options); the subscribe payload is this stream's concern.
func setup_transport(on_connect_error_extra: Callable, url_provider: Callable) -> void:
	if _transport == null:
		return
	_transport.set_on_packet(_on_ws_packet)
	_transport.set_subscribe_payload(JSON.stringify({"type": "subscribe", "stream": STREAM_NAME}))
	_transport.set_on_connect_error(func(result: int):
		_emit_command("proxy_ws_connect_err_" + str(result))
		if on_connect_error_extra.is_valid():
			on_connect_error_extra.call(result)
	)
	if url_provider.is_valid():
		_transport.set_url_provider(url_provider)


func connect_to(url: String) -> int:
	if _transport == null:
		return ERR_UNCONFIGURED
	return _transport.connect_to(url)


func poll(delta: float) -> void:
	if _transport != null:
		_transport.poll(delta)


## The live-payload apply path, moved verbatim from the card. Records into
## TrackedTargetCardState and emits the same last_command strings as before.
func apply_live_payload(payload: String) -> void:
	if _card_state != null:
		_card_state.set_packet_preview(_sanitize(payload))
	_apply_live_payload(payload)


func _on_ws_packet(payload: String) -> void:
	apply_live_payload(payload)


func _apply_live_payload(payload: String) -> void:
	if _target_source == null:
		if _card_state != null:
			_card_state.set_error("adapter_null")
		return
	var applied: bool = bool(_target_source.apply_proxy_targets_json(payload))
	var source_error := str(_target_source.last_error())
	if source_error == "json_invalid":
		if _card_state != null:
			_card_state.set_message_type("invalid")
			_card_state.set_error("json_invalid")
		_emit_command("proxy_live_invalid")
		return
	if applied:
		if _card_state != null:
			_card_state.record_live_applied()
			_card_state.set_error("-")
		_emit_command("proxy_live")
	else:
		if _card_state != null:
			_card_state.set_error(source_error)
		_emit_command("proxy_live_failed")


func _on_message_parsed(message: Dictionary) -> void:
	if _card_state != null:
		_card_state.record_parsed_message(message, head_to_world_info())


# --- Read-only accessors used by the host's status snapshot ---

func ws_connected() -> bool:
	return _transport != null and bool(_transport.ws_connected())


func ws_subscribed() -> bool:
	return _transport != null and bool(_transport.ws_subscribed())


func packets_seen() -> int:
	if _transport == null:
		return 0
	return int(_transport.packets_seen())


func last_packet_bytes() -> int:
	if _transport == null:
		return 0
	return int(_transport.last_packet_bytes())


func proxy_targets_dictionary():
	if _consumer == null or not _consumer.has_method("get_proxy_targets"):
		return {}
	return _consumer.get_proxy_targets()


func head_to_world_info() -> Dictionary:
	if _consumer == null or not _consumer.has_method("get_last_applied_target_info"):
		return {}
	var info = _consumer.get_last_applied_target_info()
	if typeof(info) != TYPE_DICTIONARY:
		return {}
	return info


func _emit_command(command: String) -> void:
	if _on_command.is_valid():
		_on_command.call(command)


func _sanitize(payload: String) -> String:
	if _packet_sanitizer.is_valid():
		return str(_packet_sanitizer.call(payload))
	return payload
