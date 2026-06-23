extends RefCounted
class_name CardViewBase

## Shared presentation helpers for SmartXR card views.
##
## Concrete views decide whether they render a SubViewport panel or a Label3D,
## but use this base for stable label construction and snapshot-to-text mapping.


func build_label3d(parent: Node3D, label_name: String, options := {}) -> Label3D:
	if parent == null:
		return null
	var label := Label3D.new()
	label.name = label_name
	label.font_size = int(options.get("font_size", 28))
	label.outline_size = int(options.get("outline_size", 8))
	label.no_depth_test = bool(options.get("no_depth_test", true))
	label.billboard = int(options.get("billboard", BaseMaterial3D.BILLBOARD_ENABLED))
	label.modulate = options.get("modulate", Color(0.92, 0.98, 1.0, 1.0))
	label.position = options.get("position", Vector3.ZERO)
	parent.add_child(label)
	return label


func format_snapshot_text(title: String, snapshot: Dictionary, fields: Array) -> String:
	var lines := [title]
	for field in fields:
		if typeof(field) != TYPE_DICTIONARY:
			continue
		var label := str(field.get("label", ""))
		var key := str(field.get("key", ""))
		var fallback := str(field.get("fallback", ""))
		var value := str(snapshot.get(key, fallback))
		if label.is_empty():
			lines.append(value)
		else:
			lines.append("%s: %s" % [label, value])
	return "\n".join(PackedStringArray(lines))
