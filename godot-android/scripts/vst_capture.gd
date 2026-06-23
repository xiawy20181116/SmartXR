extends RefCounted
class_name VSTCapture

## VST capture + bbox math subsystem.
##
## Owns GXRDualVstCapture setup, ncnn tracker asset staging, right-frame
## polling, tracker boxes, eye-to-head calibration diagnostics, and bbox
## projection math. AndroidMovingCard keeps scene/UI side effects and target
## attachment: this script reports raw images, boxes, and anchor dictionaries
## through Callables, then exposes a plain status snapshot for ADR-4.
##
## Keep dependency-free and script-probe loadable: no preloads, no tree access,
## and no self class_name references inside this file.

const DEFAULT_NCNN_PARAM_RES := "res://ncnn/yolov8n_320.opt.ncnn.param"
const DEFAULT_NCNN_BIN_RES := "res://ncnn/yolov8n_320.opt.ncnn.bin"
const DEFAULT_NCNN_PARAM_USER := "user://ncnn/yolov8n_320.opt.ncnn.param"
const DEFAULT_NCNN_BIN_USER := "user://ncnn/yolov8n_320.opt.ncnn.bin"
const DEFAULT_RIGHT_TRACKER_ENABLED := true
const DEFAULT_RIGHT_TRACKER_FRAME_STRIDE := 5
const DEFAULT_HORIZONTAL_FOV_DEG := 70.0
const DEFAULT_VERTICAL_FOV_DEG := 43.0
const DEFAULT_MIN_DEPTH_M := 0.65
const DEFAULT_MAX_DEPTH_M := 4.0
const DEFAULT_START_DEPTH_M := 1.35
const GXR_CAL_CV_DEWARP_L := 0x00400060
const GXR_CAL_CV_DEWARP_R := 0x00400061
const GXR_CAL_CV_SLAM := 0x00400070

var _ncnn_param_res := DEFAULT_NCNN_PARAM_RES
var _ncnn_bin_res := DEFAULT_NCNN_BIN_RES
var _ncnn_param_user := DEFAULT_NCNN_PARAM_USER
var _ncnn_bin_user := DEFAULT_NCNN_BIN_USER
var _right_tracker_enabled := DEFAULT_RIGHT_TRACKER_ENABLED
var _right_tracker_frame_stride := DEFAULT_RIGHT_TRACKER_FRAME_STRIDE
var _horizontal_fov_deg := DEFAULT_HORIZONTAL_FOV_DEG
var _vertical_fov_deg := DEFAULT_VERTICAL_FOV_DEG
var _principal_point_px := Vector2(-1.0, -1.0)
var _focal_length_px := Vector2(-1.0, -1.0)
var _min_depth_m := DEFAULT_MIN_DEPTH_M
var _max_depth_m := DEFAULT_MAX_DEPTH_M
var _depth_m := DEFAULT_START_DEPTH_M

var _capture: Object = null
var _class_registered := false
var _init_ok := false
var _last_error := "not initialized"
var _right_image_size := Vector2.ZERO
var _right_frames := 0
var _first_box := PackedFloat32Array()
var _box_count := 0
var _tracker_latency_ms := -1.0
var _anchor_updates := 0
var _eye_to_head_status := "eye2head: not queried"
var _calibration_status := "cal: not queried"
var _right_eye_to_head_matrix := PackedFloat64Array()
var _uses_eye_to_head_anchor := false

var _on_raw_image := Callable()
var _on_boxes := Callable()
var _on_anchor := Callable()


func _init(config: Dictionary = {}) -> void:
	_ncnn_param_res = str(config.get("ncnn_param_res", _ncnn_param_res))
	_ncnn_bin_res = str(config.get("ncnn_bin_res", _ncnn_bin_res))
	_ncnn_param_user = str(config.get("ncnn_param_user", _ncnn_param_user))
	_ncnn_bin_user = str(config.get("ncnn_bin_user", _ncnn_bin_user))
	_right_tracker_enabled = bool(config.get("right_tracker_enabled", _right_tracker_enabled))
	_right_tracker_frame_stride = int(config.get("right_tracker_frame_stride", _right_tracker_frame_stride))
	_horizontal_fov_deg = float(config.get("horizontal_fov_deg", _horizontal_fov_deg))
	_vertical_fov_deg = float(config.get("vertical_fov_deg", _vertical_fov_deg))
	_principal_point_px = Vector2(config.get("principal_point_px", _principal_point_px))
	_focal_length_px = Vector2(config.get("focal_length_px", _focal_length_px))
	_min_depth_m = float(config.get("min_depth_m", _min_depth_m))
	_max_depth_m = float(config.get("max_depth_m", _max_depth_m))
	_depth_m = float(config.get("start_depth_m", _depth_m))


func set_raw_image_callback(on_raw_image: Callable) -> void:
	_on_raw_image = on_raw_image


func set_boxes_callback(on_boxes: Callable) -> void:
	_on_boxes = on_boxes


func set_anchor_callback(on_anchor: Callable) -> void:
	_on_anchor = on_anchor


func set_camera_calibration(horizontal_fov_deg: float, vertical_fov_deg: float, principal_point_px: Vector2 = Vector2(-1.0, -1.0), focal_length_px: Vector2 = Vector2(-1.0, -1.0)) -> void:
	_horizontal_fov_deg = clampf(horizontal_fov_deg, 1.0, 179.0)
	_vertical_fov_deg = clampf(vertical_fov_deg, 1.0, 179.0)
	_principal_point_px = principal_point_px
	_focal_length_px = focal_length_px


func setup_capture(xr_active: bool) -> void:
	if not xr_active:
		_last_error = "OpenXR inactive; VST disabled to avoid passthrough-only false success"
		print("VST init blocked: " + _last_error)
		return
	_class_registered = ClassDB.class_exists(&"GXRDualVstCapture")
	if not _class_registered:
		_last_error = "GXRDualVstCapture class not registered"
		return
	_capture = ClassDB.instantiate(&"GXRDualVstCapture")
	if _capture == null:
		_last_error = "instantiate GXRDualVstCapture failed"
		return
	if _right_tracker_enabled:
		_configure_vst_right_tracker_model()
	_init_ok = bool(_capture.initialize())
	if _init_ok:
		_last_error = ""
		_refresh_vst_calibration_diagnostics()
	else:
		_last_error = str(_capture.get_last_error()) if _capture.has_method(&"get_last_error") else "initialize returned false"


func poll() -> Dictionary:
	if _capture == null or not _init_ok:
		return status_snapshot()
	if _capture.has_method(&"has_new_frame_right") and bool(_capture.has_new_frame_right()):
		var right_img: Image = _capture.capture_frame_right() if _capture.has_method(&"capture_frame_right") else null
		if right_img != null:
			_right_image_size = Vector2(right_img.get_width(), right_img.get_height())
			_right_frames += 1
			if _on_raw_image.is_valid():
				_on_raw_image.call(right_img, _right_image_size, _right_frames)
	if _capture.has_method(&"get_right_tracker_boxes"):
		var boxes: PackedFloat32Array = _capture.get_right_tracker_boxes()
		_box_count = boxes.size() / 5
		if boxes.size() >= 5:
			_first_box = PackedFloat32Array()
			for i in range(5):
				_first_box.push_back(float(boxes[i]))
			if _on_boxes.is_valid():
				_on_boxes.call(boxes, _right_image_size)
			_apply_vst_tracker_anchor(boxes)
		else:
			_first_box = PackedFloat32Array()
			if _on_boxes.is_valid():
				_on_boxes.call(PackedFloat32Array(), _right_image_size)
	if _capture.has_method(&"get_right_tracker_total_latency_ms"):
		_tracker_latency_ms = float(_capture.get_right_tracker_total_latency_ms())
	return status_snapshot()


func shutdown() -> void:
	if _capture != null and _capture.has_method(&"shutdown"):
		_capture.shutdown()


func status_snapshot() -> Dictionary:
	return {
		"class_registered": _class_registered,
		"init_ok": _init_ok,
		"frames": _right_frames,
		"box_count": _box_count,
		"latency_ms": _tracker_latency_ms,
		"image_size": _right_image_size,
		"first_box": _first_box,
		"last_error": _last_error,
		"horizontal_fov_deg": _horizontal_fov_deg,
		"vertical_fov_deg": _vertical_fov_deg,
		"principal_point_px": _principal_point_px,
		"focal_length_px": _focal_length_px,
		"uses_eye_to_head_anchor": _uses_eye_to_head_anchor,
		"eye_to_head_status": _eye_to_head_status,
		"calibration_status": _calibration_status,
	}


func last_error() -> String:
	return _last_error


func set_depth_m(depth_m: float) -> void:
	_depth_m = clampf(depth_m, _min_depth_m, _max_depth_m)


func right_image_size() -> Vector2:
	return _right_image_size


func right_eye_to_head_matrix() -> PackedFloat64Array:
	return _right_eye_to_head_matrix


func uses_eye_to_head_anchor() -> bool:
	return _uses_eye_to_head_anchor


func anchor_from_bbox(center_px: Vector2, size_px: Vector2, image_size: Vector2, depth_m: float) -> Dictionary:
	var focal := _focal_lengths_for_image(image_size)
	var fx := focal.x
	var fy := focal.y
	var principal := _principal_point_for_image(image_size)
	var nx := (center_px.x - principal.x) / fx
	var ny := (center_px.y - principal.y) / fy
	# VST camera axes: +X right, +Y down, +Z forward.
	var point_vst := Vector3(nx, ny, 1.0).normalized() * depth_m
	var point_head := convert_vst_camera_point_to_head_convention(point_vst)
	if _uses_eye_to_head_anchor:
		point_head = transform_right_vst_point_to_head(point_vst)
	var yaw_deg := rad_to_deg(atan2(point_head.x, -point_head.z))
	var pitch_deg := rad_to_deg(atan2(point_head.y, sqrt(point_head.x * point_head.x + point_head.z * point_head.z)))
	var angular_w := rad_to_deg(2.0 * atan((size_px.x * 0.5) / fx))
	var angular_h := rad_to_deg(2.0 * atan((size_px.y * 0.5) / fy))
	return {
		"yaw_deg": yaw_deg,
		"pitch_deg": pitch_deg,
		"depth_m": point_head.length() if _uses_eye_to_head_anchor else depth_m,
		"angular_size_deg": Vector2(angular_w, angular_h),
	}


func target_position_from_bbox_anchor(anchor: Dictionary) -> Vector3:
	var depth_m := float(anchor.get("depth_m", DEFAULT_START_DEPTH_M))
	var yaw := deg_to_rad(float(anchor.get("yaw_deg", 0.0)))
	var pitch := deg_to_rad(float(anchor.get("pitch_deg", 0.0)))
	var horizontal_depth := depth_m * cos(pitch)
	return Vector3(
		horizontal_depth * sin(yaw),
		depth_m * sin(pitch),
		-horizontal_depth * cos(yaw)
	)


func convert_vst_camera_point_to_head_convention(point: Vector3) -> Vector3:
	return Vector3(point.x, -point.y, -point.z)


func _principal_point_for_image(image_size: Vector2) -> Vector2:
	if _principal_point_px.x >= 0.0 and _principal_point_px.y >= 0.0:
		return _principal_point_px
	return image_size * 0.5


func _focal_lengths_for_image(image_size: Vector2) -> Vector2:
	if _focal_length_px.x > 0.0 and _focal_length_px.y > 0.0:
		return _focal_length_px
	return Vector2(
		(image_size.x * 0.5) / tan(deg_to_rad(_horizontal_fov_deg) * 0.5),
		(image_size.y * 0.5) / tan(deg_to_rad(_vertical_fov_deg) * 0.5)
	)


func transform_right_vst_point_to_head(point: Vector3) -> Vector3:
	if _right_eye_to_head_matrix.size() < 16:
		return convert_vst_camera_point_to_head_convention(point)
	var m := _right_eye_to_head_matrix
	return Vector3(
		float(m[0]) * point.x + float(m[1]) * point.y + float(m[2]) * point.z + float(m[3]),
		float(m[4]) * point.x + float(m[5]) * point.y + float(m[6]) * point.z + float(m[7]),
		float(m[8]) * point.x + float(m[9]) * point.y + float(m[10]) * point.z + float(m[11])
	)


func tracker_box_to_target_transform(boxes: PackedFloat32Array, depth_m: float) -> Transform3D:
	if boxes.size() < 5 or _right_image_size.x <= 0.0 or _right_image_size.y <= 0.0:
		return Transform3D.IDENTITY
	var x := clampf(float(boxes[0]), 0.0, 1.0)
	var y := clampf(float(boxes[1]), 0.0, 1.0)
	var w := clampf(float(boxes[2]), 0.02, 1.0)
	var h := clampf(float(boxes[3]), 0.02, 1.0)
	var center_px := Vector2((x + w * 0.5) * _right_image_size.x, (y + h * 0.5) * _right_image_size.y)
	var size_px := Vector2(w * _right_image_size.x, h * _right_image_size.y)
	var anchor := anchor_from_bbox(center_px, size_px, _right_image_size, clampf(depth_m, _min_depth_m, _max_depth_m))
	var target_transform := Transform3D.IDENTITY
	target_transform.origin = target_position_from_bbox_anchor(anchor)
	return target_transform


func store_right_eye_to_head_matrix(eye_info: Dictionary) -> void:
	_right_eye_to_head_matrix = PackedFloat64Array()
	_uses_eye_to_head_anchor = false
	if int(eye_info.get("ret", -999)) != 0:
		return
	var right = eye_info.get("right", PackedFloat64Array())
	if not (right is PackedFloat64Array) or right.size() < 16:
		return
	for i in range(16):
		_right_eye_to_head_matrix.push_back(float(right[i]))
	_uses_eye_to_head_anchor = true


func _configure_vst_right_tracker_model() -> void:
	if _capture == null or not _capture.has_method(&"configure_right_tracker_model"):
		_last_error = "configure_right_tracker_model API unavailable"
		return
	var param_path := _stage_vst_tracker_asset(_ncnn_param_res, _ncnn_param_user)
	var bin_path := _stage_vst_tracker_asset(_ncnn_bin_res, _ncnn_bin_user)
	if param_path.is_empty() or bin_path.is_empty():
		_last_error = "ncnn asset staging failed"
		return
	var ok := bool(_capture.configure_right_tracker_model(param_path, bin_path))
	print("VST tracker model: ok=%s param=%s bin=%s" % [str(ok), param_path, bin_path])
	if _capture.has_method(&"set_right_tracker_enabled"):
		_capture.set_right_tracker_enabled(true)
	if _capture.has_method(&"set_right_tracker_frame_stride"):
		_capture.set_right_tracker_frame_stride(_right_tracker_frame_stride)
	if not ok:
		_last_error = "configure_right_tracker_model returned false"


func _stage_vst_tracker_asset(source_path: String, target_path: String) -> String:
	if not DirAccess.dir_exists_absolute("user://ncnn"):
		var err := DirAccess.make_dir_recursive_absolute("user://ncnn")
		if err != OK:
			return ""
	if FileAccess.file_exists(target_path):
		return ProjectSettings.globalize_path(target_path)
	var source := FileAccess.open(source_path, FileAccess.READ)
	if source == null:
		return ""
	var target := FileAccess.open(target_path, FileAccess.WRITE)
	if target == null:
		source.close()
		return ""
	target.store_buffer(source.get_buffer(source.get_length()))
	target.close()
	source.close()
	return ProjectSettings.globalize_path(target_path)


func _refresh_vst_calibration_diagnostics() -> void:
	if _capture == null:
		return
	if _capture.has_method(&"get_eye_to_head_matrices"):
		var eye_info = _capture.get_eye_to_head_matrices()
		if typeof(eye_info) == TYPE_DICTIONARY:
			store_right_eye_to_head_matrix(eye_info)
			_eye_to_head_status = _format_eye_to_head_status(eye_info)
		else:
			_eye_to_head_status = "eye2head: invalid response"
	else:
		_eye_to_head_status = "eye2head: API missing"

	if _capture.has_method(&"get_calibration_coeff_info"):
		var right_info = _capture.get_calibration_coeff_info(GXR_CAL_CV_DEWARP_R, 4096)
		var slam_info = _capture.get_calibration_coeff_info(GXR_CAL_CV_SLAM, 4096)
		var left_info = _capture.get_calibration_coeff_info(GXR_CAL_CV_DEWARP_L, 256)
		_calibration_status = "cal: L %s R %s SLAM %s" % [
			_format_calibration_probe(left_info),
			_format_calibration_probe(right_info),
			_format_calibration_probe(slam_info),
		]
	else:
		_calibration_status = "cal: API missing"
	print("VST calibration: %s | %s" % [_eye_to_head_status, _calibration_status])


func _format_eye_to_head_status(eye_info: Dictionary) -> String:
	var ret := int(eye_info.get("ret", -999))
	var right = eye_info.get("right", PackedFloat64Array())
	if right is PackedFloat64Array and right.size() >= 16:
		return "eye2head: ret=%d r03=%.4f r13=%.4f r23=%.4f" % [
			ret,
			float(right[3]),
			float(right[7]),
			float(right[11]),
		]
	return "eye2head: ret=%d no-matrix" % ret


func _format_calibration_probe(info) -> String:
	if typeof(info) != TYPE_DICTIONARY:
		return "invalid"
	var bytes_size := 0
	var bytes = info.get("bytes", PackedByteArray())
	if bytes is PackedByteArray:
		bytes_size = bytes.size()
	return "ret=%d size=%d bytes=%d" % [
		int(info.get("result", -999)),
		int(info.get("actual_size", 0)),
		bytes_size,
	]


func _apply_vst_tracker_anchor(boxes: PackedFloat32Array) -> void:
	if boxes.size() < 5 or _right_image_size.x <= 0.0 or _right_image_size.y <= 0.0:
		return
	var x := clampf(float(boxes[0]), 0.0, 1.0)
	var y := clampf(float(boxes[1]), 0.0, 1.0)
	var w := clampf(float(boxes[2]), 0.02, 1.0)
	var h := clampf(float(boxes[3]), 0.02, 1.0)
	var confidence := clampf(float(boxes[4]), 0.0, 1.0)
	var center_px := Vector2((x + w * 0.5) * _right_image_size.x, (y + h * 0.5) * _right_image_size.y)
	var size_px := Vector2(w * _right_image_size.x, h * _right_image_size.y)
	_depth_m = clampf(_depth_m, _min_depth_m, _max_depth_m)
	var anchor := anchor_from_bbox(center_px, size_px, _right_image_size, _depth_m)
	var target_transform := Transform3D.IDENTITY
	target_transform.origin = target_position_from_bbox_anchor(anchor)
	_anchor_updates += 1
	if _on_anchor.is_valid():
		_on_anchor.call({
			"boxes": boxes,
			"center_px": center_px,
			"size_px": size_px,
			"image_size": _right_image_size,
			"depth_m": _depth_m,
			"angular_size_deg": anchor.get("angular_size_deg", Vector2.ZERO),
			"target_transform": target_transform,
			"confidence": confidence,
			"anchor_updates": _anchor_updates,
		})
