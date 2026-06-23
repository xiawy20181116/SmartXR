extends "card_view_base.gd"

## Scene-node builder for the main SmartXR card view.
##
## AndroidMovingCard owns motion, orientation, target attachment, and status
## snapshots. This helper owns only the main card SubViewport/UI, panel mesh,
## material setup, and the small XR render probe.

const DEFAULT_VIEWPORT_SIZE := Vector2i(720, 1080)
const DEFAULT_CARD_SIZE_M := Vector2(0.72, 1.08)
const DEFAULT_XR_PROBE_SIZE_M := Vector2(0.18, 0.18)

var _viewport_size := DEFAULT_VIEWPORT_SIZE
var _card_size_m := DEFAULT_CARD_SIZE_M
var _xr_probe_size_m := DEFAULT_XR_PROBE_SIZE_M
var _viewport: SubViewport = null
var _anchor: Node3D = null
var _card_mesh: MeshInstance3D = null
var _xr_probe_mesh: MeshInstance3D = null


func _init(options := {}) -> void:
	if typeof(options) != TYPE_DICTIONARY:
		return
	_viewport_size = options.get("viewport_size", _viewport_size)
	_card_size_m = options.get("card_size_m", _card_size_m)
	_xr_probe_size_m = options.get("xr_probe_size_m", _xr_probe_size_m)


func build(parent: Node, anchor_name: String) -> void:
	if parent == null:
		return
	_viewport = SubViewport.new()
	_viewport.name = "CardViewport"
	_viewport.size = _viewport_size
	_viewport.transparent_bg = true
	_viewport.disable_3d = true
	_viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	parent.add_child(_viewport)
	_viewport.add_child(_make_card_ui())

	_anchor = Node3D.new()
	_anchor.name = anchor_name
	parent.add_child(_anchor)

	var mesh := QuadMesh.new()
	mesh.size = _card_size_m

	var material := StandardMaterial3D.new()
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_texture = _viewport.get_texture()
	material.albedo_color = Color(1.0, 1.0, 1.0, 1.0)
	material.no_depth_test = false
	material.cull_mode = BaseMaterial3D.CULL_DISABLED

	_card_mesh = MeshInstance3D.new()
	_card_mesh.name = "CardPanel"
	_card_mesh.mesh = mesh
	_card_mesh.set_surface_override_material(0, material)
	_anchor.add_child(_card_mesh)


func build_xr_render_probe():
	if _anchor == null:
		return null
	var mesh := QuadMesh.new()
	mesh.size = _xr_probe_size_m

	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_color = Color(1.0, 0.05, 0.05, 1.0)
	material.no_depth_test = true
	material.cull_mode = BaseMaterial3D.CULL_DISABLED

	_xr_probe_mesh = MeshInstance3D.new()
	_xr_probe_mesh.name = "XRRenderProbe"
	_xr_probe_mesh.mesh = mesh
	_xr_probe_mesh.position = Vector3(-0.56, 0.58, 0.025)
	_xr_probe_mesh.set_surface_override_material(0, material)
	_anchor.add_child(_xr_probe_mesh)
	return _xr_probe_mesh


func viewport() -> SubViewport:
	return _viewport


func anchor() -> Node3D:
	return _anchor


func card_mesh() -> MeshInstance3D:
	return _card_mesh


func xr_probe_mesh() -> MeshInstance3D:
	return _xr_probe_mesh


func _make_card_ui() -> Control:
	var panel := PanelContainer.new()
	panel.name = "MovingCardUI"
	panel.set_anchors_preset(Control.PRESET_FULL_RECT)
	panel.offset_left = 24
	panel.offset_top = 24
	panel.offset_right = -24
	panel.offset_bottom = -24
	panel.add_theme_stylebox_override("panel", _make_panel_style())

	var margin := MarginContainer.new()
	margin.set_anchors_preset(Control.PRESET_FULL_RECT)
	margin.add_theme_constant_override("margin_left", 48)
	margin.add_theme_constant_override("margin_top", 56)
	margin.add_theme_constant_override("margin_right", 48)
	margin.add_theme_constant_override("margin_bottom", 56)
	panel.add_child(margin)

	var body := VBoxContainer.new()
	body.alignment = BoxContainer.ALIGNMENT_CENTER
	body.add_theme_constant_override("separation", 18)
	margin.add_child(body)

	body.add_child(_make_label("安炫百  C17PROJ-90", 58, Color(0.95, 1.0, 0.35, 1.0)))
	body.add_child(_make_label("Jira issues: 1", 38, Color(0.72, 0.95, 1.0, 1.0)))
	body.add_child(_make_label("Matting 效果", 50, Color(0.92, 0.98, 1.0, 1.0)))
	body.add_child(_make_label("Status: New    Priority: Medium", 36, Color(0.72, 0.95, 1.0, 1.0)))
	body.add_child(_make_label("Updated: 2026-03-05", 30, Color(0.62, 0.82, 0.92, 1.0)))
	return panel


func _make_label(text: String, font_size: int, color: Color) -> Label:
	var label := Label.new()
	label.text = text
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	label.add_theme_color_override("font_outline_color", Color(0.0, 0.0, 0.0, 0.82))
	label.add_theme_constant_override("outline_size", 5)
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return label


func _make_panel_style() -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.06, 0.075, 0.09, 0.92)
	style.border_color = Color(0.18, 0.78, 0.86, 0.98)
	style.set_border_width_all(4)
	style.set_corner_radius_all(4)
	style.shadow_color = Color(0.0, 0.0, 0.0, 0.45)
	style.shadow_size = 24
	return style
