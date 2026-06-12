extends RefCounted
class_name CardAttachment

## Card attachment subsystem (M3 step 4 of the YAN-73 encapsulation roadmap,
## extracted from AndroidMovingCard.gd).
##
## Owns the card_id -> attachment bookkeeping (`_attachments`), the
## attach/detach/update/fallback state machine, and the offset-rule math
## (normalization, world vs target offset spaces, the right_top/right/top/
## front/custom offset modes), moved byte-for-byte from the card.
##
## State resolution stays in the card per ADR-4 (DECISIONS.md): the target
## registry stays card-owned and is reached only through the injected
## resolve Callable; the card anchor node arrives through a provider
## Callable (the card may rebuild it); `_anchor_mode` / `_last_command`
## transitions and the `_face_camera_enabled` orientation pass happen in the
## card via the two hook Callables (set_on_all_detached fires when the last
## attachment goes away — the old detach-to-manual transition — and
## set_on_attachments_updated fires after every update pass, where the card
## re-orients the anchor and refreshes the VST bbox frame). This mirrors the
## WSTransport wiring from M3 step 3.
##
## Keep this script dependency-free and loadable in no-project mode: no
## preloads, no env reads, no tree access, and never reference its own
## class_name inside this file (global class registration does not happen in
## script-only probes; see tools/run_godot_card_attachment_probe.ps1).

const TARGET_FALLBACK_HOLD_LAST_POSE := "hold_last_pose"
const TARGET_FALLBACK_DETACH := "detach"
const TARGET_FALLBACK_FADE_OUT := "fade_out"
const TARGET_DEFAULT_OFFSET_RULE := {
	"mode": "front",
	"offset_space": "world",
	"distance_m": 0.35,
	"fallback": TARGET_FALLBACK_HOLD_LAST_POSE,
}

var _attachments := {}
var _apply_count := 0
var _primary_card_id := ""
var _resolve_target := Callable()
var _card_anchor_provider := Callable()
var _on_attachments_updated := Callable()
var _on_all_detached := Callable()


## The card id update_attachments() looks up first, and the id the detach
## fallback detaches (the card passes CARD_ANCHOR_NAME, preserving the old
## hard-coded behavior).
func set_primary_card_id(card_id: String) -> void:
	_primary_card_id = card_id


## Registry lookup into the card: func(target_id: String) -> adapter or null.
## The adapter only needs is_available() and get_global_transform() (the
## TargetRegistry Node3DTargetAdapter contract). The registry itself stays
## card-owned per ADR-4.
func set_resolve_target(resolve_target: Callable) -> void:
	_resolve_target = resolve_target


## Card-anchor lookup: func() -> Node3D or null. A provider (not a node
## reference) so the card stays the owner and null-at-startup behaves like
## the old `if _card_anchor == null: return` guard.
func set_card_anchor_provider(card_anchor_provider: Callable) -> void:
	_card_anchor_provider = card_anchor_provider


## Post-update hook: func() -> void, invoked at the end of every
## update_attachments() pass that resolved an attachment (success or
## fallback). The card applies _face_camera_enabled orientation and the VST
## bbox frame refresh here, exactly like the old function tail.
func set_on_attachments_updated(on_attachments_updated: Callable) -> void:
	_on_attachments_updated = on_attachments_updated


## All-detached hook: func() -> void, invoked when detach() empties the
## bookkeeping. The card checks `_anchor_mode == "target"` and transitions
## back to "manual" + _apply_3dof_anchor_transform() there (ADR-4), exactly
## like the old detach_card body.
func set_on_all_detached(on_all_detached: Callable) -> void:
	_on_all_detached = on_all_detached


## Records the attachment when the target resolves; the card sets
## `_anchor_mode = "target"` / `_last_command` and calls update_attachments()
## on a true return, preserving the old attach_to_target sequence.
func attach(card_id: String, target_id: String, offset_rule = {}) -> bool:
	var adapter = _resolve(target_id)
	if adapter == null:
		return false
	var normalized_offset := _normalize_target_offset_rule(offset_rule)
	_attachments[card_id] = {
		"target_id": target_id,
		"offset_rule": normalized_offset,
		"fallback": str(normalized_offset.get("fallback", TARGET_FALLBACK_HOLD_LAST_POSE)),
		"last_transform": _target_offset_transform(adapter.get_global_transform(), normalized_offset),
	}
	return true


func detach(card_id: String) -> void:
	_attachments.erase(card_id)
	if _attachments.is_empty() and _on_all_detached.is_valid():
		_on_all_detached.call()


func update_attachments() -> void:
	var card_anchor := _anchor_node()
	if card_anchor == null:
		return
	var attachment = _attachments.get(_primary_card_id)
	if typeof(attachment) != TYPE_DICTIONARY and _attachments.size() == 1:
		attachment = _attachments.values()[0]
	if typeof(attachment) != TYPE_DICTIONARY:
		return
	var target_id := str(attachment.get("target_id", ""))
	var offset_rule = attachment.get("offset_rule", TARGET_DEFAULT_OFFSET_RULE)
	var adapter = _resolve(target_id)
	if adapter != null and adapter.is_available():
		var next_transform := _target_offset_transform(adapter.get_global_transform(), offset_rule)
		card_anchor.global_transform = next_transform
		attachment["last_transform"] = next_transform
		card_anchor.visible = true
		_apply_count += 1
	else:
		apply_fallback(attachment)
	if _on_attachments_updated.is_valid():
		_on_attachments_updated.call()


## Public (not underscore-private) because the card's VST-lost path calls it
## directly on the CardAnchor attachment, like the old
## _apply_vst_target_fallback -> _apply_target_fallback chain.
func apply_fallback(attachment: Dictionary) -> void:
	var fallback := str(attachment.get("fallback", TARGET_FALLBACK_HOLD_LAST_POSE))
	match fallback:
		TARGET_FALLBACK_DETACH:
			detach(_primary_card_id)
		TARGET_FALLBACK_FADE_OUT:
			var fade_anchor := _anchor_node()
			fade_anchor.visible = false
		_:
			var card_anchor := _anchor_node()
			var last_transform = attachment.get("last_transform", card_anchor.global_transform)
			if last_transform is Transform3D:
				card_anchor.global_transform = last_transform


# Snapshot-feeding getters: the card reads the status snapshot values
# (`attachments`, `card_target_id`, `card_resolved_position`,
# `card_apply_count`) through these instead of touching the dict.
func attachment_count() -> int:
	return _attachments.size()


func has_attachment(card_id: String) -> bool:
	return _attachments.has(card_id)


# Untyped return: the attachment Dictionary (live reference, so
# last_transform updates stay visible) or null when the card id is unknown.
func get_attachment(card_id: String):
	return _attachments.get(card_id)


func card_target_id(card_id: String) -> String:
	var attachment = _attachments.get(card_id)
	if typeof(attachment) != TYPE_DICTIONARY:
		return ""
	return str(attachment.get("target_id", ""))


# Untyped return: Vector3 (last_transform origin) when resolvable, null
# otherwise. StatusHud formats null as "n/a".
func card_resolved_position(card_id: String):
	var attachment = _attachments.get(card_id)
	if typeof(attachment) != TYPE_DICTIONARY:
		return null
	var last_transform = attachment.get("last_transform")
	if last_transform is Transform3D:
		return last_transform.origin
	return null


func apply_count() -> int:
	return _apply_count


func _normalize_target_offset_rule(offset_rule) -> Dictionary:
	var normalized := TARGET_DEFAULT_OFFSET_RULE.duplicate()
	if typeof(offset_rule) == TYPE_DICTIONARY:
		for key in offset_rule.keys():
			normalized[key] = offset_rule[key]
	elif typeof(offset_rule) == TYPE_STRING:
		normalized["mode"] = str(offset_rule)
	return normalized


func _target_offset_transform(target_transform: Transform3D, offset_rule) -> Transform3D:
	var rule := _normalize_target_offset_rule(offset_rule)
	if str(rule.get("offset_space", "world")) == "target":
		return _target_local_offset_transform(target_transform, rule)
	return _target_world_offset_transform(target_transform, rule)


func _target_world_offset_transform(target_transform: Transform3D, offset_rule) -> Transform3D:
	var rule := _normalize_target_offset_rule(offset_rule)
	var result := Transform3D.IDENTITY
	result.origin = target_transform.origin + _target_offset_vector(rule)
	return result


func _target_local_offset_transform(target_transform: Transform3D, offset_rule) -> Transform3D:
	var rule := _normalize_target_offset_rule(offset_rule)
	var result := target_transform
	result.origin = target_transform * _target_offset_vector(rule)
	return result


func _target_offset_vector(offset_rule) -> Vector3:
	var rule := _normalize_target_offset_rule(offset_rule)
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


# Untyped return: the resolved adapter or null (unknown id or no resolver
# wired), matching the old `_target_registry.resolve(target_id)` call sites.
func _resolve(target_id: String):
	if not _resolve_target.is_valid():
		return null
	return _resolve_target.call(target_id)


func _anchor_node() -> Node3D:
	if not _card_anchor_provider.is_valid():
		return null
	return _card_anchor_provider.call() as Node3D
