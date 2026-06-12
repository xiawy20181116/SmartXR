extends SceneTree

## Script-only runtime probe for the target registry (M3 step 2, YAN-75).
##
## Runs in no-project mode like the other script-only probes (a project run
## would boot the full main scene, which never exits headless):
##   godot --headless --script <abs path to this file>
## with the registry script injected via env:
##   SMARTXR_TARGET_REGISTRY_SCRIPT            abs path to target_registry.gd
##   SMARTXR_TARGET_REGISTRY_PROBE_STATUS_PATH abs path for the probe result
##                                             JSON (optional)
##
## Verifies at runtime: register/unregister/resolve bookkeeping (including
## empty-id, null-adapter, unknown-id, and overwrite cases), the direct-Node3D
## and NodePath/String adapter modes, and is_available/get_global_transform
## behavior on live, freed, and missing nodes. Exits 0 only if every check
## passed.

const DEFAULT_STATUS_RES := "user://target_registry_probe_status.json"

var _checks := {}
var _error := "-"
var _exit_code := 1
var _ran := false


# Unlike the status-hud probe, the checks run from the first main-loop
# iteration instead of _initialize: get_global_transform errors with
# "!is_inside_tree()" until the root Window has entered the tree, which only
# happens once the main loop starts. quit() inside _initialize is not honored
# in script-only mode either, matching the other script-only probes.
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


func _run_checks() -> String:
	var registry_script_path := OS.get_environment("SMARTXR_TARGET_REGISTRY_SCRIPT")
	if registry_script_path.is_empty():
		return "missing_env:SMARTXR_TARGET_REGISTRY_SCRIPT"
	var registry_script = load(registry_script_path)
	if registry_script == null:
		return "load_failed:" + registry_script_path
	_checks["registry_script_loads"] = true
	_checks["registry_script_can_instantiate"] = registry_script.can_instantiate()

	var adapter_class = registry_script.Node3DTargetAdapter
	_checks["adapter_inner_class_exposed"] = adapter_class != null

	var registry = registry_script.new()

	# Scene-tree root for global_transform reads (the live harness does the
	# same; script-only mode still has a root Window).
	var stage := Node3D.new()
	stage.name = "ProbeStage"
	root.add_child(stage)

	# 1. Registry bookkeeping.
	var direct_node := Node3D.new()
	direct_node.name = "DirectTarget"
	stage.add_child(direct_node)
	direct_node.position = Vector3(1.0, 2.0, 3.0)
	var direct_adapter = adapter_class.new(stage, direct_node)

	_checks["register_returns_true"] = registry.register("direct", direct_adapter) == true
	_checks["register_empty_id_rejected"] = registry.register("", direct_adapter) == false
	_checks["register_null_adapter_rejected"] = registry.register("nope", null) == false
	_checks["resolve_returns_adapter"] = registry.resolve("direct") == direct_adapter
	_checks["resolve_unknown_returns_null"] = registry.resolve("unknown") == null
	_checks["resolve_never_registered_empty_id"] = registry.resolve("") == null

	var replacement_adapter = adapter_class.new(stage, direct_node)
	_checks["register_overwrites_same_id"] = registry.register("direct", replacement_adapter) == true \
		and registry.resolve("direct") == replacement_adapter

	registry.unregister("direct")
	_checks["unregister_removes"] = registry.resolve("direct") == null
	registry.unregister("never_registered")
	_checks["unregister_unknown_is_noop"] = registry.resolve("never_registered") == null

	# 2. Direct-Node3D adapter mode.
	_checks["direct_adapter_available"] = direct_adapter.is_available() == true
	_checks["direct_adapter_node_resolves"] = direct_adapter.get_node3d() == direct_node
	var direct_origin: Vector3 = direct_adapter.get_global_transform().origin
	_checks["direct_adapter_transform"] = direct_origin.is_equal_approx(Vector3(1.0, 2.0, 3.0))

	# 3. NodePath and String adapter modes (resolved against the root node at
	# lookup time, like the card passing `self`).
	var path_child := Node3D.new()
	path_child.name = "PathTarget"
	stage.add_child(path_child)
	path_child.position = Vector3(-4.0, 0.5, 9.0)

	var nodepath_adapter = adapter_class.new(stage, NodePath("PathTarget"))
	_checks["nodepath_adapter_available"] = nodepath_adapter.is_available() == true
	_checks["nodepath_adapter_node_resolves"] = nodepath_adapter.get_node3d() == path_child
	var nodepath_origin: Vector3 = nodepath_adapter.get_global_transform().origin
	_checks["nodepath_adapter_transform"] = nodepath_origin.is_equal_approx(Vector3(-4.0, 0.5, 9.0))

	var string_adapter = adapter_class.new(stage, "PathTarget")
	_checks["string_adapter_available"] = string_adapter.is_available() == true
	_checks["string_adapter_node_resolves"] = string_adapter.get_node3d() == path_child

	# Path adapters re-resolve every lookup, so they track node moves.
	path_child.position = Vector3(7.0, 7.0, 7.0)
	var moved_origin: Vector3 = nodepath_adapter.get_global_transform().origin
	_checks["nodepath_adapter_tracks_moves"] = moved_origin.is_equal_approx(Vector3(7.0, 7.0, 7.0))

	# 4. Missing-path behavior.
	var missing_adapter = adapter_class.new(stage, NodePath("NoSuchChild"))
	_checks["missing_path_unavailable"] = missing_adapter.is_available() == false
	_checks["missing_path_identity_transform"] = missing_adapter.get_global_transform() == Transform3D.IDENTITY

	# A non-Node3D resolution target (plain Node child) must not pass the cast.
	var plain_child := Node.new()
	plain_child.name = "PlainNode"
	stage.add_child(plain_child)
	var non_node3d_adapter = adapter_class.new(stage, NodePath("PlainNode"))
	_checks["non_node3d_path_unavailable"] = non_node3d_adapter.is_available() == false

	# Unsupported constructor input (neither Node3D nor path) stays empty.
	var unsupported_adapter = adapter_class.new(stage, 42)
	_checks["unsupported_input_unavailable"] = unsupported_adapter.is_available() == false
	_checks["unsupported_input_identity_transform"] = unsupported_adapter.get_global_transform() == Transform3D.IDENTITY

	# 5. Freed-node behavior.
	direct_node.free()
	_checks["freed_node_unavailable"] = direct_adapter.is_available() == false
	_checks["freed_node_identity_transform"] = direct_adapter.get_global_transform() == Transform3D.IDENTITY

	path_child.free()
	_checks["freed_path_target_unavailable"] = nodepath_adapter.is_available() == false

	# 6. Freed lookup root: path adapters lose resolution, registry itself
	# keeps working (it holds no node references of its own).
	registry.register("late", string_adapter)
	stage.free()
	_checks["freed_root_path_unavailable"] = string_adapter.is_available() == false
	_checks["freed_root_identity_transform"] = string_adapter.get_global_transform() == Transform3D.IDENTITY
	_checks["registry_survives_freed_root"] = registry.resolve("late") == string_adapter

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
		"harness": "script_only_target_registry_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_TARGET_REGISTRY_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("target_registry_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
