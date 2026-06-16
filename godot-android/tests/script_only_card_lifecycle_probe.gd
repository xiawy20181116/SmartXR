extends SceneTree

## Script-only runtime probe for card_lifecycle.gd (the C3 state machine).
##
## Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with:
##   SMARTXR_CARD_LIFECYCLE_SCRIPT            abs path to card_lifecycle.gd
##   SMARTXR_CARD_LIFECYCLE_FIXTURE           abs path to a C3 sample json (optional)
##   SMARTXR_CARD_LIFECYCLE_PROBE_STATUS_PATH abs path for result JSON (optional)
##
## This is the runtime mirror of tests/test_card_lifecycle_payload_schema.py:
## it locks the canonical lifecycle round-trip plus illegal-transition and
## schema-coupling rejection, so the GDScript machine and the Python
## CardLifecycleConsumer stay in lock-step.

const DEFAULT_STATUS_RES := "user://card_lifecycle_probe_status.json"

var _checks := {}
var _error := "-"
var _exit_code := 1


func _initialize() -> void:
	var run_error := _run_checks()
	if run_error != "-":
		_error = run_error
	elif _all_passed():
		_exit_code = 0
	_write_status(_exit_code)


func _process(_delta: float) -> bool:
	quit(_exit_code)
	return true


func _run_checks() -> String:
	var script_path := OS.get_environment("SMARTXR_CARD_LIFECYCLE_SCRIPT")
	if script_path.is_empty():
		return "missing_env:SMARTXR_CARD_LIFECYCLE_SCRIPT"
	var lifecycle_script = load(script_path)
	if lifecycle_script == null:
		return "load_failed:" + script_path
	_checks["card_lifecycle_script_loads"] = true

	# Static contract surface.
	_checks["transition_table_has_8_edges"] = lifecycle_script.ALLOWED_TRANSITIONS.size() == 8
	_checks["default_durations_match_contract"] = (
		int(lifecycle_script.DEFAULT_ANIMATION_MS.get("appear", -1)) == 250
		and int(lifecycle_script.DEFAULT_ANIMATION_MS.get("expand", -1)) == 200
		and int(lifecycle_script.DEFAULT_ANIMATION_MS.get("contract", -1)) == 200
		and int(lifecycle_script.DEFAULT_ANIMATION_MS.get("disappear", -1)) == 300
	)

	# Canonical lifecycle round-trip: attach/appear -> expand -> contract ->
	# expand -> detach/disappear. Every edge is legal.
	var consumer = lifecycle_script.new()
	var card_id := "CardAnchor"
	var canonical := _canonical_message(card_id, "person-7")
	_checks["canonical_message_accepted"] = consumer.consume(canonical)
	_checks["canonical_accepts_five_commands"] = consumer.commands_accepted() == 5
	_checks["canonical_rejects_none"] = consumer.commands_rejected() == 0
	_checks["canonical_ends_detached"] = consumer.current_state(card_id) == lifecycle_script.DETACHED
	_checks["canonical_last_error_clear"] = consumer.last_error() == "-"
	_checks["can_reattach_after_disappear"] = consumer.consume(_message(card_id, "person-7", [
		["attach", "appear"],
	]))

	# Illegal transition: update/expand before any attach.
	var early = lifecycle_script.new()
	_checks["update_before_attach_rejected"] = not early.consume(_message("X", "t", [["update", "expand"]]))
	_checks["update_before_attach_counts"] = early.commands_rejected() == 1 and early.commands_accepted() == 0

	# Illegal transition that still passes schema coupling: appear -> contract.
	var jump = lifecycle_script.new()
	_checks["appear_to_contract_rejected"] = not jump.consume(_message("Y", "t", [
		["attach", "appear"],
		["update", "contract"],
	]))
	_checks["appear_to_contract_partial"] = jump.commands_accepted() == 1 and jump.commands_rejected() == 1

	# Schema coupling: attach paired with the wrong card_state is rejected at the
	# shape boundary (no transition is even attempted).
	var coupling = lifecycle_script.new()
	_checks["attach_expand_mismatch_rejected"] = not coupling.consume(_message("Z", "t", [["attach", "expand"]]))
	_checks["mismatch_counts_as_message_reject"] = coupling.messages_rejected() == 1 and coupling.commands_accepted() == 0

	# Unknown command / unknown card_state rejected at the shape boundary.
	var unknown = lifecycle_script.new()
	_checks["unknown_command_rejected"] = not unknown.consume(_message("Z", "t", [["wiggle", "appear"]]))

	# Bad envelope (wrong type) rejected.
	var bad = lifecycle_script.new()
	_checks["bad_type_rejected"] = not bad.consume({
		"type": "not_card_lifecycle",
		"schema_version": 1,
		"sequence": 0,
		"timestamp_ms": 0,
		"commands": [],
	})

	# JSON string entrypoint + invalid JSON handling.
	var json_consumer = lifecycle_script.new()
	_checks["consume_json_accepts_valid"] = json_consumer.consume_json(JSON.stringify(_canonical_message("J", "t")))
	_checks["consume_json_rejects_garbage"] = not json_consumer.consume_json("{not json")

	# Animation duration override resolution.
	var dur = lifecycle_script.new()
	_checks["resolve_default_duration"] = dur.resolve_duration_ms({"card_state": "appear"}) == 250
	_checks["resolve_override_duration"] = dur.resolve_duration_ms({
		"card_state": "appear",
		"animation": {"duration_ms": 90},
	}) == 90

	# Optional: validate a real C3 fixture if one is provided.
	var fixture_path := OS.get_environment("SMARTXR_CARD_LIFECYCLE_FIXTURE")
	if not fixture_path.is_empty():
		var fixture := _load_json_file(fixture_path)
		var fixture_consumer = lifecycle_script.new()
		_checks["fixture_shape_valid"] = fixture_consumer.validate_message(fixture).is_empty()

	return "-"


func _canonical_message(card_id: String, target_id: String) -> Dictionary:
	var message := _message(card_id, target_id, [
		["attach", "appear"],
		["update", "expand"],
		["update", "contract"],
		["update", "expand"],
		["detach", "disappear"],
	])
	# attach carries the offset rule, like the Python fake producer.
	message["commands"][0]["offset_rule"] = {
		"mode": "right_top",
		"offset_space": "world",
		"right_m": 0.35,
		"up_m": 0.25,
		"fallback": "hold_last_pose",
	}
	return message


func _message(card_id: String, target_id: String, steps: Array) -> Dictionary:
	var commands := []
	for step in steps:
		commands.append({
			"card_id": card_id,
			"target_id": target_id,
			"command": step[0],
			"card_state": step[1],
			"animation": {"duration_ms": 200, "easing": "ease_in_out"},
		})
	return {
		"type": "card_lifecycle",
		"schema_version": 1,
		"sequence": 0,
		"timestamp_ms": 0,
		"commands": commands,
	}


func _load_json_file(path: String):
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return null
	var text := file.get_as_text()
	file.close()
	return JSON.parse_string(text)


func _all_passed() -> bool:
	if _checks.is_empty():
		return false
	for key in _checks:
		if not _checks[key]:
			return false
	return true


func _write_status(exit_code: int) -> void:
	var failed := []
	for key in _checks:
		if not _checks[key]:
			failed.append(key)
	var status := {
		"harness": "script_only_card_lifecycle_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_CARD_LIFECYCLE_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("card_lifecycle_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
