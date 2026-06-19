extends RefCounted
class_name CardStateBase

## Shared pure-data base for SmartXR card state objects.
##
## Source-specific states keep their C2/C6 parsing methods, then store the
## normalized card snapshot here so receivers and probes can use one pattern.

var _data_source := ""
var _snapshot := {}
var _last_error := "-"


func configure_card_state(data_source: String, initial_snapshot := {}) -> void:
	_data_source = data_source
	_snapshot = _dict_or_empty(initial_snapshot)
	_last_error = "-"


func data_source() -> String:
	return _data_source


func update_snapshot(values: Dictionary) -> void:
	if typeof(values) != TYPE_DICTIONARY:
		return
	for key in values:
		_snapshot[key] = _deep_copy_value(values[key])


func snapshot() -> Dictionary:
	return _snapshot.duplicate(true)


func last_error() -> String:
	return _last_error


func set_last_error(error: String) -> void:
	_last_error = error


func clear_last_error() -> void:
	_last_error = "-"


func _dict_or_empty(value) -> Dictionary:
	if typeof(value) == TYPE_DICTIONARY:
		return value.duplicate(true)
	return {}


func _dict_or_null(value):
	if typeof(value) == TYPE_DICTIONARY:
		return value.duplicate(true)
	return null


func _deep_copy_value(value):
	if typeof(value) == TYPE_DICTIONARY:
		return value.duplicate(true)
	if typeof(value) == TYPE_ARRAY:
		return value.duplicate(true)
	return value
