extends SceneTree

## Script-only runtime probe for tracked_target_card_view.gd (D2 Phase C View
## seam). Verifies the facade forwards to the composed card_view +
## passthrough_overlay_presenter helpers. Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with:
##   SMARTXR_CARD_VIEW_FACADE_SCRIPT       abs path to tracked_target_card_view.gd
##   SMARTXR_CARD_VIEW_SCRIPT              abs path to card_view.gd
##   SMARTXR_PASSTHROUGH_PRESENTER_SCRIPT  abs path to passthrough_overlay_presenter.gd
##   SMARTXR_CARD_VIEW_FACADE_PROBE_STATUS_PATH  abs path for result JSON (optional)

const DEFAULT_STATUS_RES := "user://tracked_target_card_view_probe_status.json"
const TEST_ENV := "SMARTXR_TRACKED_TARGET_VIEW_PROBE_OVERLAY"

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
	var facade_path := OS.get_environment("SMARTXR_CARD_VIEW_FACADE_SCRIPT")
	if facade_path.is_empty():
		return "missing_env:SMARTXR_CARD_VIEW_FACADE_SCRIPT"
	var card_view_path := OS.get_environment("SMARTXR_CARD_VIEW_SCRIPT")
	if card_view_path.is_empty():
		return "missing_env:SMARTXR_CARD_VIEW_SCRIPT"
	var presenter_path := OS.get_environment("SMARTXR_PASSTHROUGH_PRESENTER_SCRIPT")
	if presenter_path.is_empty():
		return "missing_env:SMARTXR_PASSTHROUGH_PRESENTER_SCRIPT"

	var facade_script = load(facade_path)
	var card_view_script = load(card_view_path)
	var presenter_script = load(presenter_path)
	if facade_script == null or card_view_script == null or presenter_script == null:
		return "load_failed"
	_checks["scripts_load"] = true

	# Unbound facade is safe (returns defaults / nulls).
	var unbound = facade_script.new()
	_checks["unbound_safe"] = (
		unbound.viewport() == null
		and unbound.build_xr_render_probe() == null
		and unbound.overlay_enabled_from_env(TEST_ENV) == false
		and unbound.overlay_layer_alpha_blend() == false
		and unbound.overlay_layer_position() == null
		and unbound.overlay_status_values(true, "alpha_blend", true).is_empty()
	)

	var facade = facade_script.new()
	var card_view = card_view_script.new({
		"viewport_size": Vector2i(720, 1080),
		"card_size_m": Vector2(0.72, 1.08),
		"xr_probe_size_m": Vector2(0.18, 0.18),
	})
	var presenter = presenter_script.new({
		"viewport_size": Vector2i(512, 256),
		"quad_size_m": Vector2(0.42, 0.20),
		"depth_m": 1.5,
	})
	facade.bind(card_view, presenter)

	# Main card view forwarding.
	var root := Node3D.new()
	facade.build_card(root, "CardAnchor")
	var viewport = facade.viewport()
	var anchor = facade.anchor()
	var card_mesh = facade.card_mesh()
	_checks["build_card_creates_viewport"] = viewport is SubViewport and viewport.get_parent() == root
	_checks["build_card_creates_anchor"] = anchor is Node3D and anchor.name == "CardAnchor" and anchor.get_parent() == root
	_checks["build_card_creates_panel"] = card_mesh is MeshInstance3D and card_mesh.get_parent() == anchor
	var probe = facade.build_xr_render_probe()
	_checks["build_xr_render_probe"] = probe is MeshInstance3D and probe.name == "XRRenderProbe" and probe.get_parent() == anchor

	# Overlay forwarding (env enable + status; layer is skipped while XR inactive).
	OS.set_environment(TEST_ENV, "1")
	_checks["overlay_enabled_from_env_true"] = facade.overlay_enabled_from_env(TEST_ENV) == true
	OS.set_environment(TEST_ENV, "off")
	_checks["overlay_enabled_from_env_false"] = facade.overlay_enabled_from_env(TEST_ENV) == false

	facade.build_overlay_layer(root, false, true)
	_checks["overlay_layer_skipped_without_xr"] = facade.overlay_layer_position() == null and facade.overlay_layer_alpha_blend() == false
	var overlay_status: Dictionary = facade.overlay_status_values(true, "alpha_blend", true)
	_checks["overlay_status_forwards"] = (
		bool(overlay_status.get("enabled", false))
		and str(overlay_status.get("requested_blend_mode", "")) == "alpha_blend"
		and bool(overlay_status.get("blend_request_ok", false))
		and overlay_status.get("layer_created", true) == false
	)
	# update_overlay_layer with a null camera must be a safe no-op.
	facade.update_overlay_layer(null)
	_checks["overlay_update_null_camera_safe"] = true

	root.free()
	return "-"


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
		"harness": "script_only_tracked_target_card_view_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_CARD_VIEW_FACADE_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("tracked_target_card_view_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
