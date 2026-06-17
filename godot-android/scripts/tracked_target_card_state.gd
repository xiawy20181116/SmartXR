extends RefCounted
class_name TrackedTargetCardState

## Module-2 State seam for the tracked-target (proxy_targets) card (D2 Phase C,
## §16). Mirrors the assistant trio's AssistantCardState: pure data that owns
## the validated diagnostic snapshot the card reports, plus the two card-owned
## counters (live applies / attachment applies).
##
## Parsing of the proxy_targets geometry (transforms -> Node3D proxies) stays in
## ProxyTargetsConsumer behind the Receiver seam; this script owns only the
## card-facing data: the injected ProxyTargetsStatusFragment, the live/apply
## counters, and lightweight envelope validation. AndroidMovingCard keeps the
## live WS transport, consumer calls, attachment lookup, and node positions and
## passes them in as runtime_values (ADR-4).
##
## Keep this script dependency-free and loadable in no-project mode: no
## preloads, no env reads, no tree access, and never reference its own
## class_name inside this file (global class registration does not happen in
## script-only probes; see tools/run_godot_tracked_target_card_state_probe.ps1).
## The status fragment is injected via bind() so this stays preload-free.

const MESSAGE_TYPE := "proxy_targets"

var _status_fragment = null
var _live_messages := 0
var _apply_count := 0


## Inject the ProxyTargetsStatusFragment instance the host already owns. Until
## bound, the delegating setters/getters are no-ops / empty so the seam stays
## script-only loadable on its own.
func bind(status_fragment) -> void:
	_status_fragment = status_fragment


## Envelope-level validation owned by State (parse/validate role). Geometry is
## validated downstream by the consumer; this only guards the message shape the
## card depends on. Returns "-" when valid, else a stable error code.
func validate_envelope(message) -> String:
	if typeof(message) != TYPE_DICTIONARY:
		return "message_invalid"
	if message.get("type", "") != MESSAGE_TYPE:
		return "type_invalid"
	if message.has("targets") and not (message.get("targets") is Array):
		return "targets_invalid"
	if message.has("cards") and not (message.get("cards") is Array):
		return "cards_invalid"
	return "-"


func record_live_applied() -> void:
	_live_messages += 1


func record_apply() -> void:
	_apply_count += 1


func live_messages() -> int:
	return _live_messages


func apply_count() -> int:
	return _apply_count


# --- Diagnostic snapshot delegation (no-ops until bound) ---

func set_packet_preview(preview: String) -> void:
	if _status_fragment != null:
		_status_fragment.set_packet_preview(preview)


func set_error(error: String) -> void:
	if _status_fragment != null:
		_status_fragment.set_error(error)


func set_message_type(message_type: String) -> void:
	if _status_fragment != null:
		_status_fragment.set_message_type(message_type)


func record_parsed_message(message: Dictionary, head_info: Dictionary = {}) -> void:
	if _status_fragment != null:
		_status_fragment.record_parsed_message(message, head_info)


## Builds the ordered status values Dictionary. The card-owned counters
## (live / card_apply_count) are injected here so the host no longer has to
## thread them through runtime_values; everything else comes from runtime_values
## and the injected fragment, preserving the existing snapshot layout.
func status_values(runtime_values: Dictionary) -> Dictionary:
	var merged := runtime_values.duplicate(true)
	merged["live"] = _live_messages
	merged["card_apply_count"] = _apply_count
	if _status_fragment == null:
		return merged
	return _status_fragment.status_values(merged)
