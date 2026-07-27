extends SceneTree

## Script-only runtime probe for VSTDebugUI.
##
## Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with:
##   SMARTXR_VST_DEBUG_UI_SCRIPT            abs path to vst_debug_ui.gd
##   SMARTXR_VST_DEBUG_UI_PROBE_STATUS_PATH abs path for result JSON (optional)

const DEFAULT_STATUS_RES := "user://vst_debug_ui_probe_status.json"

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
	var script_path := OS.get_environment("SMARTXR_VST_DEBUG_UI_SCRIPT")
	if script_path.is_empty():
		return "missing_env:SMARTXR_VST_DEBUG_UI_SCRIPT"
	var ui_script = load(script_path)
	if ui_script == null:
		return "load_failed:" + script_path
	_checks["ui_script_loads"] = true

	var root := Node3D.new()
	var camera := Node3D.new()
	camera.name = "ProbeCamera"
	root.add_child(camera)
	var ui = ui_script.new()

	ui.build_raw_debug_panel(camera)
	ui.build_world_bbox_frame(root)
	var raw_panel := camera.get_node_or_null("VSTRawDebugPanel")
	var raw_sprite := raw_panel.get_node_or_null("VSTRawRightImage") if raw_panel != null else null
	var world_frame := root.get_node_or_null("VSTBBoxFrame")
	_checks["raw_panel_parented"] = raw_panel != null and raw_panel.get_parent() == camera
	_checks["raw_sprite_created"] = raw_sprite is Sprite3D
	_checks["world_frame_created"] = world_frame != null
	_checks["world_frame_initially_hidden"] = world_frame != null and not world_frame.visible

	var image := Image.create(8, 4, false, Image.FORMAT_RGBA8)
	image.fill(Color(0.1, 0.2, 0.3, 1.0))
	ui.update_raw_image(image, Vector2(8.0, 4.0))
	_checks["raw_image_texture_updates"] = raw_sprite != null and raw_sprite.texture != null
	var raw_label := raw_panel.get_node_or_null("VSTRawDebugLabel") if raw_panel != null else null
	ui.update_raw_frame_metadata(42, 123456789)
	_checks["raw_metadata_label_updates"] = raw_label != null \
		and str(raw_label.text).find("frame_id=42") >= 0 \
		and str(raw_label.text).find("exposure_timestamp=123456789") >= 0

	ui.update_raw_bbox_overlay(PackedFloat32Array([0.25, 0.25, 0.5, 0.5, 0.95]), Vector2(8.0, 4.0))
	_checks["raw_bbox_overlay_updates"] = _all_parts_visible(raw_panel, "VSTRawBBox")
	var raw_top = raw_panel.get_node_or_null("VSTRawBBoxTop") if raw_panel != null else null
	_checks["raw_bbox_top_sized"] = _quad_size(raw_top).x > 0.0 and _quad_size(raw_top).y > 0.0
	ui.update_raw_bbox_overlay(PackedFloat32Array(), Vector2(8.0, 4.0))
	_checks["raw_bbox_hides_without_box"] = not _any_part_visible(raw_panel, "VSTRawBBox")

	ui.update_world_bbox_frame(Vector3(0.0, 0.0, -1.35), 1.35, Vector2(10.0, 12.0), Callable())
	_checks["world_bbox_frame_updates"] = world_frame != null and world_frame.visible
	var world_top = world_frame.get_node_or_null("VSTBBoxFrameTop") if world_frame != null else null
	_checks["world_bbox_top_sized"] = _quad_size(world_top).x > 0.0 and _quad_size(world_top).y > 0.0
	ui.set_world_bbox_visible(false)
	_checks["world_bbox_visibility_control"] = world_frame != null and not world_frame.visible

	root.free()
	return "-"


func _all_parts_visible(parent: Node, prefix: String) -> bool:
	for suffix in ["Top", "Bottom", "Left", "Right"]:
		var part = parent.get_node_or_null(prefix + suffix) if parent != null else null
		if part == null or not part.visible:
			return false
	return true


func _any_part_visible(parent: Node, prefix: String) -> bool:
	for suffix in ["Top", "Bottom", "Left", "Right"]:
		var part = parent.get_node_or_null(prefix + suffix) if parent != null else null
		if part != null and part.visible:
			return true
	return false


func _quad_size(node: Node) -> Vector2:
	if not (node is MeshInstance3D):
		return Vector2.ZERO
	var mesh := node.mesh as QuadMesh
	if mesh == null:
		return Vector2.ZERO
	return mesh.size


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
		"harness": "script_only_vst_debug_ui_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_VST_DEBUG_UI_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("vst_debug_ui_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
