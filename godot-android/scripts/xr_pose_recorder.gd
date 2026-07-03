extends RefCounted

## Buffered JSONL recorder for XR head pose samples.

const SCHEMA_VERSION := 1

var _path := ""
var _status_path := ""
var _flush_every_samples := 30
var _buffer: Array = []
var _sample_index := 0
var _flush_drops := 0
var _failed := false


func setup(path: String, flush_every_samples := 30) -> void:
	_path = path.strip_edges()
	_status_path = _status_path_for(_path)
	_flush_every_samples = max(1, int(flush_every_samples))
	_buffer.clear()
	_sample_index = 0
	_flush_drops = 0
	_failed = false
	if _path.is_empty():
		return
	var file := FileAccess.open(_path, FileAccess.WRITE)
	if file == null:
		_failed = true
		_write_status_file()
		push_warning("XR pose recorder open failed: %s" % _path)
		return
	file.close()
	_write_status_file()


func sample(camera: Camera3D, xr_active: bool) -> void:
	if _path.is_empty() or _failed:
		return
	var godot_ticks_usec := Time.get_ticks_usec()
	var system_unix_time_usec := int(Time.get_unix_time_from_system() * 1000000.0)
	var world_from_head := Transform3D.IDENTITY
	if camera != null:
		world_from_head = camera.global_transform
	var row := {
		"schema_version": SCHEMA_VERSION,
		"timestamp_kind": "godot_sample_time",
		"pose_time_clock": "system_unix_time_usec",
		"pose_time_us": system_unix_time_usec,
		"godot_ticks_usec": godot_ticks_usec,
		"system_unix_time_usec": system_unix_time_usec,
		"sample_index": _sample_index,
		"xr_active": xr_active,
		"reference_space": "world",
		"camera_node": str(camera.get_path()) if camera != null else "",
		"world_from_head": _transform_to_matrix4(world_from_head),
		"head_position_m": _vec3_to_array(world_from_head.origin),
		"head_basis_rows": _basis_to_rows(world_from_head.basis),
		"tracking_valid": camera != null and xr_active,
		"flush_drops": _flush_drops,
	}
	_sample_index += 1
	_buffer.append(row)
	if _buffer.size() >= _flush_every_samples:
		flush()


func flush() -> void:
	if _buffer.is_empty():
		return
	if _path.is_empty() or _failed:
		_buffer.clear()
		_write_status_file()
		return
	var file := FileAccess.open(_path, FileAccess.READ_WRITE)
	if file == null:
		_failed = true
		_flush_drops += _buffer.size()
		_buffer.clear()
		_write_status_file()
		push_warning("XR pose recorder append failed: %s" % _path)
		return
	file.seek_end()
	for row in _buffer:
		file.store_line(JSON.stringify(row))
	file.close()
	_buffer.clear()
	_write_status_file()


func status() -> Dictionary:
	return {
		"path": _path,
		"status_path": _status_path,
		"failed": _failed,
		"sample_index": _sample_index,
		"buffered_samples": _buffer.size(),
		"flush_every_samples": _flush_every_samples,
		"flush_drops": _flush_drops,
	}


func _status_path_for(path: String) -> String:
	if path.is_empty():
		return ""
	if path.ends_with(".jsonl"):
		return path.substr(0, path.length() - ".jsonl".length()) + "_status.json"
	return path + ".status.json"


func _write_status_file() -> void:
	if _status_path.is_empty():
		return
	var file := FileAccess.open(_status_path, FileAccess.WRITE)
	if file == null:
		push_warning("XR pose recorder status write failed: %s" % _status_path)
		return
	file.store_string(JSON.stringify(status()))
	file.close()


func _transform_to_matrix4(transform: Transform3D) -> Array:
	var basis := transform.basis
	var origin := transform.origin
	return [
		[float(basis.x.x), float(basis.y.x), float(basis.z.x), float(origin.x)],
		[float(basis.x.y), float(basis.y.y), float(basis.z.y), float(origin.y)],
		[float(basis.x.z), float(basis.y.z), float(basis.z.z), float(origin.z)],
		[0.0, 0.0, 0.0, 1.0],
	]


func _basis_to_rows(basis: Basis) -> Array:
	return [
		[float(basis.x.x), float(basis.y.x), float(basis.z.x)],
		[float(basis.x.y), float(basis.y.y), float(basis.z.y)],
		[float(basis.x.z), float(basis.y.z), float(basis.z.z)],
	]


func _vec3_to_array(value: Vector3) -> Array:
	return [float(value.x), float(value.y), float(value.z)]
