extends RefCounted
class_name AssistantCardState

## Minimal assistant-card payload state for the Godot MR assistant.
##
## This script owns parsing and validation for assistant_card messages only.
## Rendering belongs to assistant_card_view.gd, and transport remains outside
## this file so it stays loadable in script-only probes.

const MESSAGE_TYPE := "assistant_card"
const SCHEMA_VERSION := 1

var _snapshot := {
	"type": MESSAGE_TYPE,
	"schema_version": SCHEMA_VERSION,
	"card_id": "",
	"target_id": "",
	"assistant_state": "idle",
	"response_text": "",
	"tool_summary": {},
	"person": null,
	"issue": null,
}
var _last_error := "-"


func apply_assistant_card_json(payload: String) -> bool:
	var parsed = JSON.parse_string(payload)
	if typeof(parsed) != TYPE_DICTIONARY:
		_last_error = "json_invalid"
		return false
	return apply_assistant_card_message(parsed)


func apply_assistant_card_message(message: Dictionary) -> bool:
	var error := _validate_message(message)
	if error != "-":
		_last_error = error
		return false
	_snapshot = {
		"type": MESSAGE_TYPE,
		"schema_version": SCHEMA_VERSION,
		"card_id": str(message.get("card_id", "")),
		"target_id": str(message.get("target_id", "")),
		"assistant_state": str(message.get("assistant_state", "idle")),
		"response_text": str(message.get("response_text", "")),
		"tool_summary": _dict_or_empty(message.get("tool_summary", {})),
		"person": _dict_or_null(message.get("person", null)),
		"issue": _dict_or_null(message.get("issue", null)),
	}
	_last_error = "-"
	return true


func snapshot() -> Dictionary:
	return _snapshot.duplicate(true)


func last_error() -> String:
	return _last_error


func _validate_message(message: Dictionary) -> String:
	if message.get("type", "") != MESSAGE_TYPE:
		return "type_invalid"
	if int(message.get("schema_version", -1)) != SCHEMA_VERSION:
		return "schema_version_invalid"
	if str(message.get("card_id", "")).is_empty():
		return "card_id_empty"
	if str(message.get("target_id", "")).is_empty():
		return "target_id_empty"
	if str(message.get("assistant_state", "")).is_empty():
		return "assistant_state_empty"
	if typeof(message.get("response_text", "")) != TYPE_STRING:
		return "response_text_invalid"
	if message.has("tool_summary") and typeof(message.get("tool_summary")) != TYPE_DICTIONARY:
		return "tool_summary_invalid"
	if message.has("person") and message.get("person") != null and typeof(message.get("person")) != TYPE_DICTIONARY:
		return "person_invalid"
	if message.has("issue") and message.get("issue") != null and typeof(message.get("issue")) != TYPE_DICTIONARY:
		return "issue_invalid"
	return "-"


func _dict_or_empty(value) -> Dictionary:
	if typeof(value) == TYPE_DICTIONARY:
		return value.duplicate(true)
	return {}


func _dict_or_null(value):
	if typeof(value) == TYPE_DICTIONARY:
		return value.duplicate(true)
	return null
