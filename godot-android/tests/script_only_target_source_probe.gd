extends SceneTree

## Script-only runtime probe for the VST target source subsystem (M4 step 2,
## YAN-84). Runs in no-project mode with target_source.gd injected via env:
##   SMARTXR_TARGET_SOURCE_SCRIPT             abs path to target_source.gd
##   SMARTXR_TARGET_SOURCE_PROBE_STATUS_PATH  abs path for result JSON

const DEFAULT_STATUS_RES := "user://target_source_probe_status.json"

var _checks := {}
var _error := "-"
var _exit_code := 1
var _ran := false
var _updated_count := 0
var _lost_ids := []
var _parsed_messages := []


class FakeProxyTargetsAdapter:
	var apply_count := 0
	var applied_messages := []
	var should_apply := true

	func apply_proxy_targets_message(message: Dictionary) -> bool:
		apply_count += 1
		applied_messages.append(message.duplicate(true))
		return should_apply


func _process(_delta: float) -> bool:
	if not _ran:
		_ran = true
		var run_error := _run_checks()
		if run_error != "-":
			_error = run_error
		elif _all_passed():
			_exit_code = 0
		_write_status(_exit_code)
	quit(_exit_code)
	return true


func _on_updated(_target_id: String, _transform: Transform3D) -> void:
	_updated_count += 1


func _on_lost(target_id: String) -> void:
	_lost_ids.append(target_id)


func _on_proxy_message_parsed(message: Dictionary) -> void:
	_parsed_messages.append(message.duplicate(true))


func _run_checks() -> String:
	var source_script_path := OS.get_environment("SMARTXR_TARGET_SOURCE_SCRIPT")
	if source_script_path.is_empty():
		return "missing_env:SMARTXR_TARGET_SOURCE_SCRIPT"
	var source_script = load(source_script_path)
	if source_script == null:
		return "load_failed:" + source_script_path
	_checks["target_source_script_loads"] = true
	_checks["target_source_script_can_instantiate"] = source_script.can_instantiate()

	var proxy := Node3D.new()
	root.add_child(proxy)
	var source = source_script.VSTTargetSource.new(
		"vst_right_target",
		proxy,
		0.45,
		180.0,
		650.0,
		1400.0,
		0.5
	)
	source.set_on_target_updated(_on_updated)
	source.set_on_target_lost(_on_lost)

	var rejected_transform := Transform3D.IDENTITY
	rejected_transform.origin = Vector3(1.0, 2.0, -3.0)
	_checks["low_confidence_rejected"] = not source.update_target("vst_right_target", rejected_transform, 0.1, 1000.0)
	_checks["empty_id_rejected"] = not source.update_target("", rejected_transform, 1.0, 1000.0)
	_checks["initial_state_lost"] = str(source.target_state()) == "lost"

	var first := Transform3D.IDENTITY
	first.origin = Vector3(0.0, 0.0, -1.0)
	_checks["first_update_tracks"] = source.update_target("vst_right_target", first, 0.9, 1000.0) \
		and str(source.target_state()) == "tracked" \
		and proxy.global_transform.origin.is_equal_approx(first.origin)
	_checks["first_update_callback"] = _updated_count == 1

	var second := Transform3D.IDENTITY
	second.origin = Vector3(2.0, 0.0, -1.0)
	source.update_target("vst_right_target", second, 0.9, 1100.0)
	var target = source.target()
	_checks["second_update_smooths_and_sets_velocity"] = target.transform.origin.is_equal_approx(Vector3(1.0, 0.0, -1.0)) \
		and target.velocity.is_equal_approx(Vector3(10.0, 0.0, 0.0)) \
		and str(target.state) == "tracked" \
		and _updated_count == 2

	source.advance(1300.0)
	_checks["advance_predicts"] = str(source.target_state()) == "predicted" \
		and source.target().transform.origin.x > 2.0
	source.advance(1800.0)
	_checks["advance_stales"] = str(source.target_state()) == "stale"
	source.advance(2600.0)
	_checks["advance_loses"] = str(source.target_state()) == "lost"
	_checks["lost_callback_fired"] = _lost_ids == ["vst_right_target"]

	var adapter := FakeProxyTargetsAdapter.new()
	var proxy_source = source_script.ProxyTargetsTargetSource.new(adapter)
	proxy_source.set_on_message_parsed(_on_proxy_message_parsed)
	_checks["proxy_source_rejects_invalid_json"] = not proxy_source.apply_proxy_targets_json("{not-json") \
		and str(proxy_source.last_error()) == "json_invalid" \
		and _parsed_messages.is_empty() \
		and adapter.apply_count == 0

	var payload := '{"type":"proxy_targets","schema_version":1,"sequence":7,"targets":[],"cards":[]}'
	_checks["proxy_source_applies_json_via_adapter"] = proxy_source.apply_proxy_targets_json(payload) \
		and str(proxy_source.last_error()) == "-" \
		and _parsed_messages.size() == 1 \
		and int(_parsed_messages[0].get("sequence", -1)) == 7 \
		and adapter.apply_count == 1 \
		and int(adapter.applied_messages[0].get("sequence", -1)) == 7

	adapter.should_apply = false
	_checks["proxy_source_reports_apply_failed"] = not proxy_source.apply_proxy_targets_message({
		"type": "proxy_targets",
		"schema_version": 1,
		"sequence": 8,
		"targets": [],
		"cards": [],
	}) \
		and str(proxy_source.last_error()) == "apply_failed" \
		and _parsed_messages.size() == 2 \
		and adapter.apply_count == 2

	return "-"


func _all_passed() -> bool:
	for key in _checks.keys():
		if not bool(_checks[key]):
			_error = "check_failed:" + str(key)
			return false
	return true


func _write_status(exit_code: int) -> void:
	var status_path := OS.get_environment("SMARTXR_TARGET_SOURCE_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file == null:
		return
	file.store_string(JSON.stringify({
		"harness": "script_only_target_source_probe",
		"exit_code": exit_code,
		"error": _error,
		"checks": _checks,
	}, "\t"))
	file.close()
