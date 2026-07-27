extends RefCounted
class_name VSTDebugUI

## Scene-node UI subsystem for VST debug visualization.
##
## AndroidMovingCard owns VST capture, target updates, and status snapshots.
## This helper owns only the debug scene nodes: the world-space bbox frame,
## raw right-image Sprite3D, and raw-image bbox overlay. Keep it loadable in
## no-project script probes: never reference its own class_name here.

const VST_BBOX_FRAME_COLOR := Color(1.0, 0.88, 0.05, 1.0)
const VST_BBOX_FRAME_LINE_M := 0.018
const VST_BBOX_FRAME_Z_OFFSET_M := 0.04
const VST_RAW_DEBUG_PIXEL_SIZE_M := 0.00045
const VST_RAW_DEBUG_POSITION := Vector3(0.48, -0.28, -1.2)
const VST_RAW_DEBUG_FRAME_Z_OFFSET_M := 0.025

var _world_bbox_frame_anchor: Node3D = null
var _world_bbox_frame_parts: Array[MeshInstance3D] = []
var _raw_debug_anchor: Node3D = null
var _raw_right_sprite: Sprite3D = null
var _raw_debug_label: Label3D = null
var _raw_bbox_parts: Array[MeshInstance3D] = []


func build_world_bbox_frame(parent: Node3D) -> void:
	if parent == null:
		return
	_world_bbox_frame_anchor = Node3D.new()
	_world_bbox_frame_anchor.name = "VSTBBoxFrame"
	_world_bbox_frame_anchor.visible = false
	parent.add_child(_world_bbox_frame_anchor)

	var material := _make_frame_material()
	for part_name in ["Top", "Bottom", "Left", "Right"]:
		var part := _make_frame_part("VSTBBoxFrame" + part_name, material)
		_world_bbox_frame_anchor.add_child(part)
		_world_bbox_frame_parts.append(part)


func build_raw_debug_panel(camera: Node3D) -> void:
	if camera == null:
		return
	_raw_debug_anchor = Node3D.new()
	_raw_debug_anchor.name = "VSTRawDebugPanel"
	_raw_debug_anchor.position = VST_RAW_DEBUG_POSITION
	camera.add_child(_raw_debug_anchor)

	_raw_right_sprite = Sprite3D.new()
	_raw_right_sprite.name = "VSTRawRightImage"
	_raw_right_sprite.pixel_size = VST_RAW_DEBUG_PIXEL_SIZE_M
	_raw_right_sprite.no_depth_test = true
	_raw_right_sprite.modulate = Color(1.0, 1.0, 1.0, 0.72)
	_raw_debug_anchor.add_child(_raw_right_sprite)

	var material := _make_frame_material()
	for part_name in ["Top", "Bottom", "Left", "Right"]:
		var part := _make_frame_part("VSTRawBBox" + part_name, material)
		part.visible = false
		_raw_debug_anchor.add_child(part)
		_raw_bbox_parts.append(part)

	var label := Label3D.new()
	label.name = "VSTRawDebugLabel"
	label.text = _format_raw_debug_label(0, -1)
	label.font_size = 18
	label.no_depth_test = true
	label.modulate = VST_BBOX_FRAME_COLOR
	label.position = Vector3(0.0, 0.19, 0.02)
	_raw_debug_anchor.add_child(label)
	_raw_debug_label = label


func update_world_bbox_frame(anchor_position: Vector3, anchor_depth_m: float, angular_size_deg: Vector2, orient_to_camera: Callable) -> void:
	if _world_bbox_frame_anchor == null or _world_bbox_frame_parts.size() != 4:
		return
	if angular_size_deg.x <= 0.0 or angular_size_deg.y <= 0.0:
		set_world_bbox_visible(false)
		return
	set_world_bbox_visible(true)
	_world_bbox_frame_anchor.position = anchor_position
	if orient_to_camera.is_valid():
		orient_to_camera.call(_world_bbox_frame_anchor)

	var width_m := maxf(2.0 * anchor_depth_m * tan(deg_to_rad(angular_size_deg.x) * 0.5), VST_BBOX_FRAME_LINE_M * 3.0)
	var height_m := maxf(2.0 * anchor_depth_m * tan(deg_to_rad(angular_size_deg.y) * 0.5), VST_BBOX_FRAME_LINE_M * 3.0)
	_configure_frame_part(_world_bbox_frame_parts[0], Vector2(width_m, VST_BBOX_FRAME_LINE_M), Vector3(0.0, height_m * 0.5, VST_BBOX_FRAME_Z_OFFSET_M))
	_configure_frame_part(_world_bbox_frame_parts[1], Vector2(width_m, VST_BBOX_FRAME_LINE_M), Vector3(0.0, -height_m * 0.5, VST_BBOX_FRAME_Z_OFFSET_M))
	_configure_frame_part(_world_bbox_frame_parts[2], Vector2(VST_BBOX_FRAME_LINE_M, height_m), Vector3(-width_m * 0.5, 0.0, VST_BBOX_FRAME_Z_OFFSET_M))
	_configure_frame_part(_world_bbox_frame_parts[3], Vector2(VST_BBOX_FRAME_LINE_M, height_m), Vector3(width_m * 0.5, 0.0, VST_BBOX_FRAME_Z_OFFSET_M))


func update_raw_image(right_img: Image, image_size: Vector2) -> void:
	if _raw_right_sprite == null:
		return
	if image_size.x <= 0.0 or image_size.y <= 0.0:
		return
	_raw_right_sprite.texture = ImageTexture.create_from_image(right_img)


func update_raw_frame_metadata(frame_id: int, exposure_timestamp: int) -> void:
	if _raw_debug_label == null:
		return
	_raw_debug_label.text = _format_raw_debug_label(frame_id, exposure_timestamp)


func update_raw_bbox_overlay(boxes: PackedFloat32Array, image_size: Vector2) -> void:
	if _raw_bbox_parts.size() != 4 or image_size.x <= 0.0 or image_size.y <= 0.0:
		return
	if boxes.size() < 5:
		set_raw_bbox_visible(false)
		return
	var x := clampf(float(boxes[0]), 0.0, 1.0)
	var y := clampf(float(boxes[1]), 0.0, 1.0)
	var w := clampf(float(boxes[2]), 0.02, 1.0)
	var h := clampf(float(boxes[3]), 0.02, 1.0)
	var overlay_size := image_size * VST_RAW_DEBUG_PIXEL_SIZE_M
	var center := Vector3((x + w * 0.5 - 0.5) * overlay_size.x, (0.5 - y - h * 0.5) * overlay_size.y, VST_RAW_DEBUG_FRAME_Z_OFFSET_M)
	var width_m := w * overlay_size.x
	var height_m := h * overlay_size.y
	set_raw_bbox_visible(true)
	_configure_frame_part(_raw_bbox_parts[0], Vector2(width_m, VST_BBOX_FRAME_LINE_M), center + Vector3(0.0, height_m * 0.5, 0.0))
	_configure_frame_part(_raw_bbox_parts[1], Vector2(width_m, VST_BBOX_FRAME_LINE_M), center + Vector3(0.0, -height_m * 0.5, 0.0))
	_configure_frame_part(_raw_bbox_parts[2], Vector2(VST_BBOX_FRAME_LINE_M, height_m), center + Vector3(-width_m * 0.5, 0.0, 0.0))
	_configure_frame_part(_raw_bbox_parts[3], Vector2(VST_BBOX_FRAME_LINE_M, height_m), center + Vector3(width_m * 0.5, 0.0, 0.0))


func set_world_bbox_visible(visible: bool) -> void:
	if _world_bbox_frame_anchor != null:
		_world_bbox_frame_anchor.visible = visible


func set_raw_bbox_visible(visible: bool) -> void:
	for part in _raw_bbox_parts:
		part.visible = visible


func _make_frame_material() -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.albedo_color = VST_BBOX_FRAME_COLOR
	material.no_depth_test = true
	material.cull_mode = BaseMaterial3D.CULL_DISABLED
	return material


func _make_frame_part(part_name: String, material: StandardMaterial3D) -> MeshInstance3D:
	var part := MeshInstance3D.new()
	part.name = part_name
	part.mesh = QuadMesh.new()
	part.set_surface_override_material(0, material)
	return part


func _configure_frame_part(part: MeshInstance3D, size: Vector2, position: Vector3) -> void:
	var mesh := part.mesh as QuadMesh
	if mesh != null:
		mesh.size = size
	part.position = position


func _format_raw_debug_label(frame_id: int, exposure_timestamp: int) -> String:
	var exposure_text := str(exposure_timestamp) if exposure_timestamp >= 0 else "n/a"
	return "RAW VST\nframe_id=%d\nexposure_timestamp=%s" % [frame_id, exposure_text]
