extends SceneTree

## Script-only runtime probe for the shared bbox->head math test vectors
## (M4-1, YAN-80).
##
## Drives the GDScript side of the duplicated bbox math in
## AndroidMovingCard.gd (_anchor_from_bbox,
## _convert_vst_camera_point_to_head_convention,
## _transform_right_vst_point_to_head, _target_position_from_bbox_anchor)
## against godot-android/fixtures/bbox_math_test_vectors.json — the same
## fixture tests/test_bbox_math_vectors.py runs through smartxr.geometry —
## so the two implementations are locked to one set of numbers.
##
## Runs in no-project mode:
##   godot --headless --script <abs path to this file>
## BUT the card preloads eight sibling scripts via res://scripts/*.gd, so the
## runner (tools/run_godot_bbox_math_probe.ps1) stages scripts/ into a temp
## working directory WITHOUT project.godot and launches Godot with that cwd
## (same trick as the compile gate; loading the real project hangs headless
## on the GXR/OpenXR boot). Env:
##   SMARTXR_BBOX_MATH_CARD_SCRIPT       abs path to the staged AndroidMovingCard.gd
##   SMARTXR_BBOX_MATH_FIXTURE_PATH      abs path to bbox_math_test_vectors.json
##   SMARTXR_BBOX_MATH_PROBE_STATUS_PATH abs path for the result JSON (optional)
##
## The card is instantiated WITHOUT entering the tree (no _ready, so no WS
## connects and no XR init); it is a Node3D, so it is freed explicitly. The
## projection-only cases in the fixture are Python-side vectors (the card has
## no bare projection method — projection is locked here through the
## full-chain cases). Comparison tolerance comes from the fixture's
## tolerances.gdscript_abs (Vector3 is float32).

const DEFAULT_STATUS_RES := "user://bbox_math_probe_status.json"
const DEFAULT_TOLERANCE := 0.0001

var _checks := {}
var _error := "-"
var _exit_code := 1
var _ran := false
var _tolerance := DEFAULT_TOLERANCE


# Checks run from the first main-loop iteration instead of _initialize, the
# same rule as the other script-only probes (quit() inside _initialize is not
# honored in script-only mode).
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


func _approx(a: float, b: float) -> bool:
	return absf(a - b) <= _tolerance


func _vec3_close(actual: Vector3, expected: Array) -> bool:
	if expected.size() != 3:
		return false
	return _approx(actual.x, float(expected[0])) \
		and _approx(actual.y, float(expected[1])) \
		and _approx(actual.z, float(expected[2]))


func _run_checks() -> String:
	var fixture_path := OS.get_environment("SMARTXR_BBOX_MATH_FIXTURE_PATH")
	if fixture_path.is_empty():
		return "missing_env:SMARTXR_BBOX_MATH_FIXTURE_PATH"
	var card_script_path := OS.get_environment("SMARTXR_BBOX_MATH_CARD_SCRIPT")
	if card_script_path.is_empty():
		return "missing_env:SMARTXR_BBOX_MATH_CARD_SCRIPT"

	var fixture_text := FileAccess.get_file_as_string(fixture_path)
	if fixture_text.is_empty():
		return "fixture_read_failed:" + fixture_path
	var fixture: Variant = JSON.parse_string(fixture_text)
	if typeof(fixture) != TYPE_DICTIONARY:
		return "fixture_parse_failed:" + fixture_path
	_checks["fixture_schema_version"] = int(fixture.get("schema_version", -1)) == 1
	var tolerances: Variant = fixture.get("tolerances", {})
	if typeof(tolerances) == TYPE_DICTIONARY:
		_tolerance = float(tolerances.get("gdscript_abs", DEFAULT_TOLERANCE))

	var card_script = load(card_script_path)
	if card_script == null:
		return "card_load_failed:" + card_script_path
	_checks["card_script_loads"] = true
	_checks["card_script_can_instantiate"] = card_script.can_instantiate()

	# The full-chain vectors are authored with the card's FOV consts; fail on
	# drift instead of silently comparing different projections.
	var card_hfov := float(card_script.BBOX_HORIZONTAL_FOV_DEG)
	var card_vfov := float(card_script.BBOX_VERTICAL_FOV_DEG)

	# Instantiate WITHOUT add_child: _ready must not run (it would connect
	# WebSockets and init XR). Member initializers only build RefCounted
	# subsystems and read options, which is side-effect free here.
	var card = card_script.new()

	# 1. Head conversion cases: the default [x, -y, -z] flip via
	# _convert_vst_camera_point_to_head_convention, the row-major matrix path
	# via _transform_right_vst_point_to_head (matrix injected directly into
	# _vst_right_eye_to_head_matrix), and the <16-element fallback.
	for case in fixture.get("head_conversion_cases", []):
		var name := str(case.get("name"))
		var case_input: Dictionary = case.get("input", {})
		var point_array: Array = case_input.get("point", [])
		var point := Vector3(float(point_array[0]), float(point_array[1]), float(point_array[2]))
		var matrix: Variant = case_input.get("right_eye_to_head")
		var actual: Vector3
		if matrix == null:
			actual = card._convert_vst_camera_point_to_head_convention(point)
		else:
			card._vst_right_eye_to_head_matrix = PackedFloat64Array(matrix)
			actual = card._transform_right_vst_point_to_head(point)
		_checks["head:" + name] = _vec3_close(actual, case.get("expected", {}).get("head_point", []))

	# 2. Full-chain cases: _anchor_from_bbox decomposition
	# (yaw/pitch/depth/angular size) and the final position from
	# _target_position_from_bbox_anchor, with the eye-to-head matrix path on
	# or off per case.
	for case in fixture.get("full_chain_cases", []):
		var name := str(case.get("name"))
		var case_input: Dictionary = case.get("input", {})
		var expected: Dictionary = case.get("expected", {})
		_checks["chain:" + name + ":fov_matches_card"] = \
			float(case_input.get("horizontal_fov_deg")) == card_hfov \
			and float(case_input.get("vertical_fov_deg")) == card_vfov
		var matrix: Variant = case_input.get("right_eye_to_head")
		card._vst_uses_eye_to_head_anchor = bool(case_input.get("uses_eye_to_head_anchor", false))
		if matrix == null:
			card._vst_right_eye_to_head_matrix = PackedFloat64Array()
		else:
			card._vst_right_eye_to_head_matrix = PackedFloat64Array(matrix)
		var anchor: Dictionary = card._anchor_from_bbox(
			Vector2(float(case_input.get("cx")), float(case_input.get("cy"))),
			Vector2(float(case_input.get("w")), float(case_input.get("h"))),
			Vector2(float(case_input.get("image_w")), float(case_input.get("image_h"))),
			float(case_input.get("depth_m"))
		)
		var angular_expected: Array = expected.get("angular_size_deg", [])
		var angular: Vector2 = anchor.get("angular_size_deg", Vector2.ZERO)
		_checks["chain:" + name + ":anchor"] = \
			_approx(float(anchor.get("yaw_deg")), float(expected.get("yaw_deg"))) \
			and _approx(float(anchor.get("pitch_deg")), float(expected.get("pitch_deg"))) \
			and _approx(float(anchor.get("depth_m")), float(expected.get("depth_m"))) \
			and angular_expected.size() == 2 \
			and _approx(angular.x, float(angular_expected[0])) \
			and _approx(angular.y, float(angular_expected[1]))
		var position: Vector3 = card._target_position_from_bbox_anchor(anchor)
		_checks["chain:" + name + ":position"] = _vec3_close(position, expected.get("position", []))

	card.free()
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
		"harness": "script_only_bbox_math_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_BBOX_MATH_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("bbox_math_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
