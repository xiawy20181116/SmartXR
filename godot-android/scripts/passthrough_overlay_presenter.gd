extends RefCounted

## Scene-node presenter for the Antman passthrough overlay.
##
## AndroidMovingCard owns enablement state and XR lifecycle ordering. This
## helper owns only the overlay viewport/layer nodes, UI construction, layer
## transforms, and probe-visible status values.

const DEFAULT_VIEWPORT_SIZE := Vector2i(512, 256)
const DEFAULT_QUAD_SIZE_M := Vector2(0.42, 0.20)
const DEFAULT_DEPTH_M := 1.5

var _viewport_size := DEFAULT_VIEWPORT_SIZE
var _quad_size_m := DEFAULT_QUAD_SIZE_M
var _depth_m := DEFAULT_DEPTH_M
var _viewport: SubViewport = null
var _layer: OpenXRCompositionLayerQuad = null


func _init(options := {}) -> void:
	if typeof(options) != TYPE_DICTIONARY:
		return
	_viewport_size = options.get("viewport_size", _viewport_size)
	_quad_size_m = options.get("quad_size_m", _quad_size_m)
	_depth_m = float(options.get("depth_m", _depth_m))


func overlay_enabled_from_env(env_name: String) -> bool:
	return overlay_enabled_from_value(OS.get_environment(env_name))


func overlay_enabled_from_value(value: String) -> bool:
	return ["1", "true", "yes", "on"].has(value.strip_edges().to_lower())


func build_layer(parent: Node, xr_active: bool, enabled: bool) -> void:
	if not enabled:
		return
	if not xr_active:
		return
	if parent == null:
		return
	_viewport = SubViewport.new()
	_viewport.name = "PassthroughOverlayViewport"
	_viewport.size = _viewport_size
	_viewport.transparent_bg = true
	_viewport.disable_3d = true
	_viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	parent.add_child(_viewport)
	_viewport.add_child(_make_overlay_ui())

	_layer = OpenXRCompositionLayerQuad.new()
	_layer.name = "AntmanPassthroughOverlayLayer"
	_layer.layer_viewport = _viewport
	_layer.quad_size = _quad_size_m
	# Antman_Smart gotcha: default false makes transparent viewport areas compose as black.
	_layer.alpha_blend = true
	_layer.visible = true
	parent.add_child(_layer)


func update_layer(camera: Node3D) -> void:
	if _layer == null or camera == null:
		return
	var camera_transform := camera.global_transform
	var world_position: Vector3 = camera_transform * Vector3(0.0, 0.0, -_depth_m)
	_layer.global_transform = Transform3D(camera_transform.basis, world_position)
	_layer.force_update_transform()


func viewport() -> SubViewport:
	return _viewport


func layer() -> OpenXRCompositionLayerQuad:
	return _layer


func layer_alpha_blend() -> bool:
	if _layer == null:
		return false
	return bool(_layer.alpha_blend)


## Untyped return: Vector3 when the layer exists, null otherwise.
func layer_position():
	if _layer == null:
		return null
	return _layer.global_transform.origin


func status_values(enabled: bool, requested_blend_mode: String, blend_request_ok: bool) -> Dictionary:
	return {
		"enabled": enabled,
		"requested_blend_mode": requested_blend_mode,
		"blend_request_ok": blend_request_ok,
		"layer_created": _layer != null,
		"layer_visible": _layer.visible if _layer != null else false,
		"layer_alpha_blend": layer_alpha_blend(),
		"layer_position": layer_position(),
	}


func _make_overlay_ui() -> Control:
	var root := Control.new()
	root.name = "PassthroughOverlayUI"
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.size = Vector2(_viewport_size)

	var panel := ColorRect.new()
	panel.name = "PassthroughOverlayPanel"
	panel.set_anchors_preset(Control.PRESET_FULL_RECT)
	panel.color = Color(0.05, 1.0, 0.35, 0.58)
	root.add_child(panel)

	var label := Label.new()
	label.name = "PassthroughOverlayLabel"
	label.text = "PASSTHROUGH OVERLAY"
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.set_anchors_preset(Control.PRESET_FULL_RECT)
	label.add_theme_font_size_override("font_size", 34)
	label.add_theme_color_override("font_color", Color(0.0, 0.05, 0.02, 1.0))
	root.add_child(label)
	return root
