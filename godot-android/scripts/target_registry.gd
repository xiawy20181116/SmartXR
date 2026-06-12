extends RefCounted
class_name TargetRegistry

## Target registry subsystem (M3 step 2 of the YAN-73 encapsulation roadmap,
## extracted from AndroidMovingCard.gd).
##
## Pure id -> adapter bookkeeping plus the Node3D/NodePath adapter that
## resolves a registered target to a live Node3D. It owns no card state,
## resolves no configuration, and never touches the scene tree on its own
## (the card passes the lookup root into each adapter), so a script-only
## probe can exercise it headless
## (godot-android/tests/script_only_target_registry_probe.gd).
##
## TrackableTarget and VSTTargetAdapter belong to target_source.gd (M4), not
## the registry.
##
## Keep this script loadable in no-project mode: never reference its own
## class_name inside this file (global class registration does not happen in
## script-only probes). The inner class below is referenced by its
## script-scoped name, which is safe.


## Wraps either a direct Node3D reference or a NodePath/String resolved
## against a root node at lookup time. Freed nodes and dangling paths report
## is_available() == false and an IDENTITY transform.
class Node3DTargetAdapter:
	var _root: Node = null
	var _node: Node3D = null
	var _path := NodePath()
	var _uses_path := false

	func _init(root: Node, node_or_path) -> void:
		_root = root
		if node_or_path is Node3D:
			_node = node_or_path
			return
		if node_or_path is NodePath:
			_path = node_or_path
			_uses_path = true
			return
		if typeof(node_or_path) == TYPE_STRING:
			_path = NodePath(str(node_or_path))
			_uses_path = true

	func get_node3d() -> Node3D:
		if _uses_path:
			if _root == null or not is_instance_valid(_root):
				return null
			var resolved := _root.get_node_or_null(_path)
			return resolved as Node3D
		if _node == null or not is_instance_valid(_node):
			return null
		return _node

	func is_available() -> bool:
		return get_node3d() != null

	func get_global_transform() -> Transform3D:
		var target := get_node3d()
		if target == null:
			return Transform3D.IDENTITY
		return target.global_transform


var _targets := {}


func register(target_id: String, adapter: Node3DTargetAdapter) -> bool:
	if target_id.is_empty() or adapter == null:
		return false
	_targets[target_id] = adapter
	return true


func unregister(target_id: String) -> void:
	_targets.erase(target_id)


func resolve(target_id: String) -> Node3DTargetAdapter:
	var adapter = _targets.get(target_id)
	if adapter is Node3DTargetAdapter:
		return adapter
	return null
