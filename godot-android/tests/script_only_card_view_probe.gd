extends SceneTree

## Script-only runtime probe for card_view.gd.
##
## Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## with:
##   SMARTXR_CARD_VIEW_SCRIPT            abs path to card_view.gd
##   SMARTXR_CARD_VIEW_PROBE_STATUS_PATH abs path for result JSON (optional)

const DEFAULT_STATUS_RES := "user://card_view_probe_status.json"

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
	var script_path := OS.get_environment("SMARTXR_CARD_VIEW_SCRIPT")
	if script_path.is_empty():
		return "missing_env:SMARTXR_CARD_VIEW_SCRIPT"
	var card_view_script = load(script_path)
	if card_view_script == null:
		return "load_failed:" + script_path
	_checks["card_view_script_loads"] = true

	var view = card_view_script.new({
		"viewport_size": Vector2i(720, 1080),
		"card_size_m": Vector2(0.72, 1.08),
		"xr_probe_size_m": Vector2(0.18, 0.18),
	})
	var root := Node3D.new()
	view.build(root, "CardAnchor")

	var viewport = view.viewport()
	var anchor = view.anchor()
	var card_mesh = view.card_mesh()
	_checks["build_creates_viewport"] = viewport is SubViewport and viewport.name == "CardViewport" and viewport.get_parent() == root
	_checks["viewport_config_matches_card"] = viewport != null and viewport.size == Vector2i(720, 1080) and viewport.transparent_bg and viewport.disable_3d and viewport.render_target_update_mode == SubViewport.UPDATE_ALWAYS
	_checks["build_creates_anchor"] = anchor is Node3D and anchor.name == "CardAnchor" and anchor.get_parent() == root
	_checks["build_creates_card_panel"] = card_mesh is MeshInstance3D and card_mesh.name == "CardPanel" and card_mesh.get_parent() == anchor
	var mesh := card_mesh.mesh as QuadMesh if card_mesh != null else null
	_checks["card_mesh_size_matches_card"] = mesh != null and mesh.size == Vector2(0.72, 1.08)
	var material := card_mesh.get_surface_override_material(0) as StandardMaterial3D if card_mesh != null else null
	_checks["card_material_matches_card"] = material != null and material.albedo_texture == viewport.get_texture() and material.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA and material.shading_mode == BaseMaterial3D.SHADING_MODE_UNSHADED and not material.no_depth_test and material.cull_mode == BaseMaterial3D.CULL_DISABLED

	var ui = viewport.get_node_or_null("MovingCardUI") if viewport != null else null
	_checks["ui_root_created"] = ui is PanelContainer
	_checks["ui_panel_offsets_match_card"] = ui != null and ui.offset_left == 24 and ui.offset_top == 24 and ui.offset_right == -24 and ui.offset_bottom == -24
	_checks["ui_labels_match_card"] = _find_label_texts(ui) == [
		"安炫百  C17PROJ-90",
		"Jira issues: 1",
		"Matting 效果",
		"Status: New    Priority: Medium",
		"Updated: 2026-03-05",
	]

	var probe = view.build_xr_render_probe()
	_checks["xr_probe_created"] = probe is MeshInstance3D and probe.name == "XRRenderProbe" and probe.get_parent() == anchor
	var probe_mesh := probe.mesh as QuadMesh if probe != null else null
	_checks["xr_probe_size_position"] = probe_mesh != null and probe_mesh.size == Vector2(0.18, 0.18) and probe.position == Vector3(-0.56, 0.58, 0.025)
	var probe_material := probe.get_surface_override_material(0) as StandardMaterial3D if probe != null else null
	_checks["xr_probe_material_matches_card"] = probe_material != null and probe_material.albedo_color == Color(1.0, 0.05, 0.05, 1.0) and probe_material.no_depth_test and probe_material.cull_mode == BaseMaterial3D.CULL_DISABLED

	root.free()
	return "-"


func _find_label_texts(root: Node) -> Array:
	var texts := []
	_collect_label_texts(root, texts)
	return texts


func _collect_label_texts(node: Node, texts: Array) -> void:
	if node == null:
		return
	if node is Label:
		texts.append(node.text)
	for child in node.get_children():
		_collect_label_texts(child, texts)


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
		"harness": "script_only_card_view_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_CARD_VIEW_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("card_view_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
