extends RefCounted
class_name CardLifecycle

## C3 card-lifecycle state machine (runtime form of the C3 seam).
##
## This is the GDScript mirror of smartxr/card_lifecycle_schema.py +
## smartxr/card_lifecycle_fakes.py (CardLifecycleConsumer), and the runtime
## counterpart of docs/card_lifecycle_payload_contract.md. It owns:
##   * card_lifecycle message *shape* validation + command/card_state coupling,
##   * the per-card visual lifecycle state machine
##     (detached -> appear -> expand <-> contract, any -> disappear -> detached).
##
## It is pure data (extends RefCounted, no nodes, no transport, no OS access) so
## it stays loadable in script-only probes. Per the issue this lives in its own
## file and is NOT folded into card_attachment.gd. Animation playback / node
## mutation belongs to the view; this script only decides which transitions are
## legal and what duration each state defaults to.

const MESSAGE_TYPE := "card_lifecycle"
const SCHEMA_VERSION := 1

## Implicit null state before attach / after detach completes. Not carried on
## the wire as a card_state value.
const DETACHED := "detached"

const ALLOWED_COMMANDS := ["attach", "update", "detach"]
const ALLOWED_CARD_STATES := ["appear", "expand", "contract", "disappear"]

## Command -> the card_state(s) that command may carry (static coupling rule).
const COMMAND_CARD_STATES := {
	"attach": ["appear"],
	"update": ["expand", "contract"],
	"detach": ["disappear"],
}

## Legal card_state transitions including the implicit DETACHED null state,
## keyed as "from->to" for O(1) lookup.
const ALLOWED_TRANSITIONS := {
	"detached->appear": true,
	"appear->expand": true,
	"expand->contract": true,
	"contract->expand": true,
	"appear->disappear": true,
	"expand->disappear": true,
	"contract->disappear": true,
	"disappear->detached": true,
}

## Default per-state animation durations (ms); producers may override per
## command via animation.duration_ms.
const DEFAULT_ANIMATION_MS := {
	"appear": 250,
	"expand": 200,
	"contract": 200,
	"disappear": 300,
}

var _commands_accepted := 0
var _commands_rejected := 0
var _messages_rejected := 0
var _state_by_card := {}
var _errors := []
var _last_error := "-"


func current_state(card_id: String) -> String:
	return str(_state_by_card.get(card_id, DETACHED))


func duration_for(card_state: String) -> int:
	return int(DEFAULT_ANIMATION_MS.get(card_state, 0))


## Resolve the animation duration for a command, honouring an optional
## animation.duration_ms override and falling back to the per-state default.
func resolve_duration_ms(command: Dictionary) -> int:
	var card_state := str(command.get("card_state", ""))
	if command.has("animation") and typeof(command.get("animation")) == TYPE_DICTIONARY:
		var animation: Dictionary = command.get("animation")
		if animation.has("duration_ms"):
			var override = animation.get("duration_ms")
			if _is_number(override) and float(override) >= 0.0:
				return int(override)
	return duration_for(card_state)


func commands_accepted() -> int:
	return _commands_accepted


func commands_rejected() -> int:
	return _commands_rejected


func messages_rejected() -> int:
	return _messages_rejected


func errors() -> Array:
	return _errors.duplicate()


func last_error() -> String:
	return _last_error


func consume_json(payload: String) -> bool:
	var parsed = JSON.parse_string(payload)
	if typeof(parsed) != TYPE_DICTIONARY:
		_messages_rejected += 1
		_last_error = "json_invalid"
		_errors.append(_last_error)
		return false
	return consume(parsed)


## Validate the message shape, then apply each command in order. Returns true
## only if the message is well-formed AND every command is a legal transition.
## Illegal transitions are rejected, not applied; legal commands in the same
## message are still applied (per architecture section 12: never partially
## applied at the command level).
func consume(message) -> bool:
	var shape_errors := validate_message(message)
	if not shape_errors.is_empty():
		_messages_rejected += 1
		_errors.append_array(shape_errors)
		_last_error = str(shape_errors[0])
		return false

	var all_ok := true
	var commands: Array = message["commands"]
	for index in commands.size():
		var command: Dictionary = commands[index]
		var card_id := str(command.get("card_id", ""))
		var target := str(command.get("card_state", ""))
		var current := current_state(card_id)
		if not ALLOWED_TRANSITIONS.has(current + "->" + target):
			_commands_rejected += 1
			var msg := "$.commands[%d] illegal transition %s -> %s for card %s" % [
				index, current, target, card_id,
			]
			_errors.append(msg)
			_last_error = msg
			all_ok = false
			continue
		_commands_accepted += 1
		# After disappear the card is cleaned up back to DETACHED.
		_state_by_card[card_id] = DETACHED if target == "disappear" else target
	if all_ok:
		_last_error = "-"
	return all_ok


## Validate a canonical card_lifecycle message; returns a list of error strings
## (empty == valid). Mirrors smartxr.card_lifecycle_schema.validate_message.
func validate_message(message) -> Array:
	var errs := []
	if typeof(message) != TYPE_DICTIONARY:
		errs.append("$ must be an object")
		return errs

	if message.get("type", "") != MESSAGE_TYPE:
		errs.append("$.type must be " + MESSAGE_TYPE)
	if int(message.get("schema_version", -1)) != SCHEMA_VERSION:
		errs.append("$.schema_version must be %d" % SCHEMA_VERSION)
	if not _is_integral(message.get("sequence", null)):
		errs.append("$.sequence must be an integer")
	if not _is_number(message.get("timestamp_ms", null)):
		errs.append("$.timestamp_ms must be a number")

	var commands = message.get("commands", null)
	if typeof(commands) != TYPE_ARRAY or (commands as Array).is_empty():
		errs.append("$.commands must be a non-empty array")
	else:
		for index in (commands as Array).size():
			_validate_command(commands[index], index, errs)
	return errs


func _validate_command(command, index: int, errs: Array) -> void:
	var path := "$.commands[%d]" % index
	if typeof(command) != TYPE_DICTIONARY:
		errs.append(path + " must be an object")
		return

	if typeof(command.get("card_id", null)) != TYPE_STRING or str(command.get("card_id", "")).is_empty():
		errs.append(path + ".card_id must be a non-empty string")
	if typeof(command.get("target_id", null)) != TYPE_STRING or str(command.get("target_id", "")).is_empty():
		errs.append(path + ".target_id must be a non-empty string")

	var verb := str(command.get("command", ""))
	var card_state := str(command.get("card_state", ""))
	if not ALLOWED_COMMANDS.has(verb):
		errs.append(path + ".command must be one of " + str(ALLOWED_COMMANDS))
	if not ALLOWED_CARD_STATES.has(card_state):
		errs.append(path + ".card_state must be one of " + str(ALLOWED_CARD_STATES))
	if COMMAND_CARD_STATES.has(verb) and not (COMMAND_CARD_STATES[verb] as Array).has(card_state):
		errs.append(path + ".card_state must be one of " + str(COMMAND_CARD_STATES[verb]) + " for command '" + verb + "'")

	if command.has("offset_rule") and typeof(command.get("offset_rule")) != TYPE_DICTIONARY:
		errs.append(path + ".offset_rule must be an object when present")
	if command.has("animation"):
		_validate_animation(command.get("animation"), path + ".animation", errs)


func _validate_animation(animation, path: String, errs: Array) -> void:
	if typeof(animation) != TYPE_DICTIONARY:
		errs.append(path + " must be an object when present")
		return
	var duration = animation.get("duration_ms", null)
	if not _is_number(duration) or float(duration) < 0.0:
		errs.append(path + ".duration_ms must be a non-negative number")
	if animation.has("easing") and typeof(animation.get("easing")) != TYPE_STRING:
		errs.append(path + ".easing must be a string when present")


func _is_number(value) -> bool:
	return typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT


## True for an integer, including a float carrying an integral value (some JSON
## parsers widen integer literals to float on round-trip).
func _is_integral(value) -> bool:
	if typeof(value) == TYPE_INT:
		return true
	if typeof(value) == TYPE_FLOAT:
		return value == floor(value)
	return false
