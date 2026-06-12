extends RefCounted
class_name CardAttachment

## Card attachment subsystem (M3 step 4 of the YAN-73 encapsulation roadmap,
## extracted from AndroidMovingCard.gd).
##
## Owns the card_id -> attachment store (target id, normalized offset rule,
## fallback name, last applied transform), the per-frame attachment pass that
## drives the card anchor from a resolved target, the fallback state machine
## (hold_last_pose / detach / fade_out), and the offset-rule math (modes
## right_top / right / top / front / custom-xyz, offset_space world / target,
## defaults from DEFAULT_OFFSET_RULE).
##
## State resolution stays in the card per ADR-4 (DECISIONS.md): the card keeps
## its public API (attach_to_target / detach_card), resolves targets through
## TargetRegistry and passes the resolver in as a Callable (set_resolver), and
## keeps anchor-mode switching, card orientation, and the status snapshot.
## This script only does attachment bookkeeping and applies transforms to the
## anchor node the card hands it. The detach fallback routes back through the
## card (set_on_detach_card) so the card's anchor-mode flip stays where the
## state lives; on_applied lets the card keep its apply counter.
##
## Keep this script dependency-free and loadable in no-project mode: no
## preloads, no env reads, no tree access of its own, and never reference its
## own class_name inside this file (global class registration does not happen
## in script-only probes; see tools/run_godot_card_attachment_probe.ps1).

const TARGET_FALLBACK_HOLD_LAST_POSE := "hold_last_pose"
const TARGET_FALLBACK_DETACH := "detach"
const TARGET_FALLBACK_FADE_OUT := "fade_out"
const DEFAULT_OFFSET_RULE := {
	"mode": "front",
	"offset_space": "world",
	"distance_m": 0.35,
	"fallback": TARGET_FALLBACK_HOLD_LAST_POSE,
}

var _attachments := {}
var _resolver := Callable()
var _on_applied := Callable()
var _on_detach_card := Callable()


## Target resolver into the card's registry: func(target_id: String) -> adapter
## (an object with is_available() / get_global_transform(), e.g. the
## TargetRegistry Node3DTargetAdapter) or null when unknown. The card wires
## _target_registry.resolve here, so target lookup stays in target_registry.gd.
func set_resolver(resolver: Callable) -> void:
	_resolver = resolver


## Optional callback fired once per attachment pass that applied a resolved
## target transform to the anchor: func() -> void. The card keeps its
## card_apply_count status counter through this.
func set_on_applied(on_applied: Callable) -> void:
	_on_applied = on_applied


## Optional detach-fallback route back into the card:
## func(card_id: String) -> void. When set, the "detach" fallback calls the
## card's detach_card so the anchor-mode flip stays card-side (ADR-4); when
## unset, the store detaches locally (probe / standalone use).
func set_on_detach_card(on_detach_card: Callable) -> void:
	_on_detach_card = on_detach_card


## Attaches card_id to target_id with the given offset rule (Dictionary,
## bare mode String, or omitted for DEFAULT_OFFSET_RULE). Returns false when
## the resolver does not know the target. Seeds last_transform from the
## target's current transform so hold_last_pose has a pose from frame one.
func attach(card_id: String, target_id: String, offset_rule = {}) -> bool:
	var adapter = _resolve(target_id)
	if adapter == null:
		return false
	var normalized := normalize_offset_rule(offset_rule)
	_attachments[card_id] = {
		"target_id": target_id,
		"offset_rule": normalized,
		"fallback": str(normalized.get("fallback", TARGET_FALLBACK_HOLD_LAST_POSE)),
		"last_transform": offset_transform(adapter.get_global_transform(), normalized),
	}
	return true


func detach(card_id: String) -> void:
	_attachments.erase(card_id)


## Per-frame attachment pass. Picks the primary attachment (primary_card_id,
## or the single remaining attachment when the primary id is absent), applies
## the offset transform of an available target to the anchor, and runs the
## fallback otherwise. Returns true when an attachment was processed (applied
## or fallback) so the card knows to re-orient; false when there was nothing
## to do.
func update_attachments(card_anchor: Node3D, primary_card_id: String) -> bool:
	if card_anchor == null:
		return false
	var attachment = _attachments.get(primary_card_id)
	if typeof(attachment) != TYPE_DICTIONARY and _attachments.size() == 1:
		attachment = _attachments.values()[0]
	if typeof(attachment) != TYPE_DICTIONARY:
		return false
	var target_id := str(attachment.get("target_id", ""))
	var offset_rule = attachment.get("offset_rule", DEFAULT_OFFSET_RULE)
	var adapter = _resolve(target_id)
	if adapter != null and adapter.is_available():
		var next_transform := offset_transform(adapter.get_global_transform(), offset_rule)
		card_anchor.global_transform = next_transform
		attachment["last_transform"] = next_transform
		card_anchor.visible = true
		if _on_applied.is_valid():
			_on_applied.call()
	else:
		apply_fallback(attachment, card_anchor, primary_card_id)
	return true


## Fallback state machine for an unavailable target: detach routes through the
## card (or detaches locally when unwired), fade_out hides the anchor, and
## hold_last_pose (the default) restores the last applied transform. Also
## called directly by the card's VST lost-state path with a stored attachment.
func apply_fallback(attachment: Dictionary, card_anchor: Node3D, primary_card_id: String) -> void:
	var fallback := str(attachment.get("fallback", TARGET_FALLBACK_HOLD_LAST_POSE))
	match fallback:
		TARGET_FALLBACK_DETACH:
			if _on_detach_card.is_valid():
				_on_detach_card.call(primary_card_id)
			else:
				detach(primary_card_id)
		TARGET_FALLBACK_FADE_OUT:
			if card_anchor != null:
				card_anchor.visible = false
		_:
			if card_anchor == null:
				return
			var last_transform = attachment.get("last_transform", card_anchor.global_transform)
			if last_transform is Transform3D:
				card_anchor.global_transform = last_transform


func size() -> int:
	return _attachments.size()


func is_empty() -> bool:
	return _attachments.is_empty()


func has_attachment(card_id: String) -> bool:
	return _attachments.has(card_id)


## Untyped return: the stored attachment Dictionary, or null when card_id is
## not attached.
func get_attachment(card_id: String):
	var attachment = _attachments.get(card_id)
	if typeof(attachment) != TYPE_DICTIONARY:
		return null
	return attachment


func attached_target_id(card_id: String) -> String:
	var attachment = get_attachment(card_id)
	if attachment == null:
		return ""
	return str(attachment.get("target_id", ""))


## Untyped return: origin of the last applied transform (Vector3), or null
## when card_id is not attached. StatusHud renders null as "n/a".
func last_resolved_position(card_id: String):
	var attachment = get_attachment(card_id)
	if attachment == null:
		return null
	var last_transform = attachment.get("last_transform")
	if last_transform is Transform3D:
		return last_transform.origin
	return null


static func normalize_offset_rule(offset_rule) -> Dictionary:
	var normalized := DEFAULT_OFFSET_RULE.duplicate()
	if typeof(offset_rule) == TYPE_DICTIONARY:
		for key in offset_rule.keys():
			normalized[key] = offset_rule[key]
	elif typeof(offset_rule) == TYPE_STRING:
		normalized["mode"] = str(offset_rule)
	return normalized


static func offset_transform(target_transform: Transform3D, offset_rule) -> Transform3D:
	var rule := normalize_offset_rule(offset_rule)
	if str(rule.get("offset_space", "world")) == "target":
		return local_offset_transform(target_transform, rule)
	return world_offset_transform(target_transform, rule)


static func world_offset_transform(target_transform: Transform3D, offset_rule) -> Transform3D:
	var rule := normalize_offset_rule(offset_rule)
	var result := Transform3D.IDENTITY
	result.origin = target_transform.origin + offset_vector(rule)
	return result


static func local_offset_transform(target_transform: Transform3D, offset_rule) -> Transform3D:
	var rule := normalize_offset_rule(offset_rule)
	var result := target_transform
	result.origin = target_transform * offset_vector(rule)
	return result


static func offset_vector(offset_rule) -> Vector3:
	var rule := normalize_offset_rule(offset_rule)
	var mode := str(rule.get("mode", "front"))
	var distance := float(rule.get("distance_m", 0.35))
	var local_offset := Vector3.ZERO
	match mode:
		"right_top", "top_right":
			local_offset = Vector3(float(rule.get("right_m", 0.35)), float(rule.get("up_m", 0.35)), float(rule.get("forward_m", 0.0)))
		"right":
			local_offset = Vector3(distance, 0.0, 0.0)
		"top":
			local_offset = Vector3(0.0, distance, 0.0)
		"front":
			local_offset = Vector3(0.0, 0.0, -distance)
		_:
			local_offset = Vector3(
				float(rule.get("x_m", 0.0)),
				float(rule.get("y_m", 0.0)),
				float(rule.get("z_m", -distance))
			)
	return local_offset


func _resolve(target_id: String):
	if not _resolver.is_valid():
		return null
	return _resolver.call(target_id)
