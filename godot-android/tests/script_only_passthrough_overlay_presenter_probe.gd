extends SceneTree

## Script-only runtime probe for passthrough_overlay_presenter.gd.
##
## Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with:
##   SMARTXR_PASSTHROUGH_OVERLAY_PRESENTER_SCRIPT            abs path to passthrough_overlay_presenter.gd
##   SMARTXR_PASSTHROUGH_OVERLAY_PRESENTER_PROBE_STATUS_PATH abs path for result JSON (optional)

const DEFAULT_STATUS_RES := "user://passthrough_overlay_presenter_probe_status.json"

var _checks := {}
var _error := "-"
var _exit_code := 1
var _ran := false


func _initialize() -> void:
	pass


func _process(_delta: float) -> bool:
	if _ran:
		quit(_exit_code)
		return true
	_ran = true
	var run_error := _run_checks()
	if run_error != "-":
		_error = run_error
	elif _all_passed():
		_exit_code = 0
	_write_status(_exit_code)
	return true


func _run_checks() -> String:
	var script_path := OS.get_environment("SMARTXR_PASSTHROUGH_OVERLAY_PRESENTER_SCRIPT")
	if script_path.is_empty():
		return "missing_env:SMARTXR_PASSTHROUGH_OVERLAY_PRESENTER_SCRIPT"
	var presenter_script = load(script_path)
	if presenter_script == null:
		return "load_failed:" + script_path
	_checks["presenter_script_loads"] = true

	var presenter = presenter_script.new({
		"viewport_size": Vector2i(512, 256),
		"quad_size_m": Vector2(0.42, 0.20),
		"depth_m": 1.5,
	})
	_checks["env_true_values"] = presenter.overlay_enabled_from_value("1") and presenter.overlay_enabled_from_value("true") and presenter.overlay_enabled_from_value("yes") and presenter.overlay_enabled_from_value("on")
	_checks["env_false_values"] = not presenter.overlay_enabled_from_value("") and not presenter.overlay_enabled_from_value("0") and not presenter.overlay_enabled_from_value("false")

	var root := Node3D.new()
	get_root().add_child(root)
	presenter.build_layer(root, false, true)
	_checks["inactive_xr_does_not_create_layer"] = presenter.layer() == null and presenter.viewport() == null and root.get_child_count() == 0
	presenter.build_layer(root, true, false)
	_checks["disabled_overlay_does_not_create_layer"] = presenter.layer() == null and presenter.viewport() == null and root.get_child_count() == 0

	presenter.build_layer(root, true, true)
	var viewport = presenter.viewport()
	var layer = presenter.layer()
	_checks["active_build_creates_viewport"] = viewport is SubViewport and viewport.name == "PassthroughOverlayViewport"
	_checks["active_build_creates_layer"] = layer is OpenXRCompositionLayerQuad and layer.name == "AntmanPassthroughOverlayLayer"
	_checks["viewport_config_matches_card"] = viewport != null and viewport.size == Vector2i(512, 256) and viewport.transparent_bg and viewport.disable_3d and viewport.render_target_update_mode == SubViewport.UPDATE_ALWAYS
	_checks["layer_config_matches_card"] = layer != null and layer.layer_viewport == viewport and layer.quad_size == Vector2(0.42, 0.20) and layer.visible and bool(layer.alpha_blend)
	var ui = viewport.get_node_or_null("PassthroughOverlayUI") if viewport != null else null
	var panel = ui.get_node_or_null("PassthroughOverlayPanel") if ui != null else null
	var label = ui.get_node_or_null("PassthroughOverlayLabel") if ui != null else null
	_checks["ui_nodes_created"] = ui is Control and panel is ColorRect and label is Label
	_checks["ui_label_text_matches_card"] = label != null and label.text == "PASSTHROUGH OVERLAY"

	var camera := Node3D.new()
	root.add_child(camera)
	camera.global_transform = Transform3D(Basis.IDENTITY, Vector3(1.0, 2.0, 3.0))
	presenter.update_layer(camera)
	_checks["update_places_layer_in_front_of_camera"] = layer != null and _vec3_close(layer.global_transform.origin, Vector3(1.0, 2.0, 1.5), 0.0001)
	_checks["alpha_blend_helper_matches_layer"] = presenter.layer_alpha_blend()
	_checks["position_helper_matches_layer"] = presenter.layer_position() == layer.global_transform.origin

	var status: Dictionary = presenter.status_values(true, "alpha_blend", true)
	_checks["status_values_match_card_keys"] = status == {
		"enabled": true,
		"requested_blend_mode": "alpha_blend",
		"blend_request_ok": true,
		"layer_created": true,
		"layer_visible": true,
		"layer_alpha_blend": true,
		"layer_position": layer.global_transform.origin,
	}

	root.free()
	return "-"


func _vec3_close(actual: Vector3, expected: Vector3, tolerance: float) -> bool:
	return actual.distance_to(expected) <= tolerance


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
		"harness": "script_only_passthrough_overlay_presenter_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_PASSTHROUGH_OVERLAY_PRESENTER_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("passthrough_overlay_presenter_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
