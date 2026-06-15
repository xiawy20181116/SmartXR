extends Node
class_name AssistantCardView

## Minimal Label3D renderer for assistant-card snapshots.
##
## State parsing is intentionally kept in assistant_card_state.gd. This node
## only creates and updates the visible card label.

var _label: Label3D = null
const TITLE := "Assistant"


func build_card_label(parent: Node3D) -> Label3D:
	_label = Label3D.new()
	_label.name = "AssistantCardLabel"
	_label.font_size = 28
	_label.outline_size = 8
	_label.no_depth_test = true
	_label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	_label.modulate = Color(0.92, 0.98, 1.0, 1.0)
	_label.position = Vector3(0.0, 0.0, 0.0)
	parent.add_child(_label)
	return _label


func update_from_snapshot(snapshot: Dictionary) -> void:
	if _label == null:
		return
	var tool_summary: Dictionary = snapshot.get("tool_summary", {})
	var status_line := str(tool_summary.get("status_line", ""))
	var response_text := str(snapshot.get("response_text", ""))
	_label.text = TITLE + "\nState: %s\n%s\n%s" % [
		str(snapshot.get("assistant_state", "idle")),
		status_line if not status_line.is_empty() else "No tool summary",
		response_text if not response_text.is_empty() else "No response yet",
	]
