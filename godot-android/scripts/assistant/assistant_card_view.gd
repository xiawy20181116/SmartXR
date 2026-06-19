extends "../card_view_base.gd"
class_name AssistantCardView

## Minimal Label3D renderer for assistant-card snapshots.
##
## State parsing is intentionally kept in assistant_card_state.gd. This node
## only creates and updates the visible card label.

var _label: Label3D = null
const TITLE := "Assistant"


func build_card_label(parent: Node3D) -> Label3D:
	_label = build_label3d(parent, "AssistantCardLabel")
	return _label


func update_from_snapshot(snapshot: Dictionary) -> void:
	if _label == null:
		return
	var tool_summary: Dictionary = snapshot.get("tool_summary", {})
	var status_line := str(tool_summary.get("status_line", ""))
	var response_text := str(snapshot.get("response_text", ""))
	_label.text = format_snapshot_text(TITLE, {
		"assistant_state": str(snapshot.get("assistant_state", "idle")),
		"status_line": status_line if not status_line.is_empty() else "No tool summary",
		"response_text": response_text if not response_text.is_empty() else "No response yet",
	}, [
		{"label": "State", "key": "assistant_state", "fallback": "idle"},
		{"label": "", "key": "status_line", "fallback": "No tool summary"},
		{"label": "", "key": "response_text", "fallback": "No response yet"},
	])
