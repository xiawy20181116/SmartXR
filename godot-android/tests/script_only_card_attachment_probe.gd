extends SceneTree

## Script-only runtime probe for the card attachment subsystem (M3 step 4,
## YAN-78).
##
## Runs in no-project mode like the other script-only probes (a project run
## would boot the full main scene, which never exits headless):
##   godot --headless --script <abs path to this file>
## with the attachment script injected via env:
##   SMARTXR_CARD_ATTACHMENT_SCRIPT            abs path to card_attachment.gd
##   SMARTXR_CARD_ATTACHMENT_PROBE_STATUS_PATH abs path for the probe result
##                                             JSON (optional)
##
## Verifies at runtime: attach/detach bookkeeping (unknown-target rejection,
## the all-detached hook that drives the card's detach-to-manual transition),
## offset-rule normalization (string vs dictionary vs unsupported input,
## TARGET_DEFAULT_OFFSET_RULE merge), every offset mode
## (right_top/top_right/right/top/front/custom) and both offset spaces
## (world ignores target rotation, target rotates the offset), all three
## fallbacks (hold_last_pose / detach / fade_out) against a
## registered-then-freed and an unregistered target, last_transform tracking,
## the single-attachment fallback lookup (primary key first, else the only
## entry), and the snapshot-feeding getters. Exits 0 only if every check
## passed.

const DEFAULT_STATUS_RES := "user://card_attachment_probe_status.json"


## Minimal stand-in for the TargetRegistry Node3DTargetAdapter contract the
## subsystem consumes through the resolve Callable: is_available() +
## get_global_transform(). Freed nodes report unavailable + IDENTITY.
class ProbeTargetAdapter:
	var _node: Node3D = null

	func _init(node: Node3D) -> void:
		_node = node

	func is_available() -> bool:
		return _node != null and is_instance_valid(_node)

	func get_global_transform() -> Transform3D:
		if not is_available():
			return Transform3D.IDENTITY
		return _node.global_transform


var _checks := {}
var _error := "-"
var _exit_code := 1
var _ran := false

# Probe-side stand-ins for the card-owned state (ADR-4): the target lookup
# dict behind the resolve Callable, the card anchor behind the provider
# Callable, and the anchor-mode flag the hooks transition.
var _targets := {}
var _anchor: Node3D = null
var _mode := "manual"
var _updated_calls := 0
var _all_detached_calls := 0


func _resolve_target(target_id: String):
	return _targets.get(target_id)


func _get_anchor() -> Node3D:
	return _anchor


func _on_updated() -> void:
	_updated_calls += 1


# Mirrors the card's all-detached hook: "target" -> "manual" transition.
func _on_all_detached() -> void:
	_all_detached_calls += 1
	if _mode == "target":
		_mode = "manual"


# Checks run from the first main-loop iteration instead of _initialize:
# global_transform reads error with "!is_inside_tree()" until the root
# Window has entered the tree, and quit() inside _initialize is not honored
# in script-only mode (same as the target-registry probe).
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
	var attachment_script_path := OS.get_environment("SMARTXR_CARD_ATTACHMENT_SCRIPT")
	if attachment_script_path.is_empty():
		return "missing_env:SMARTXR_CARD_ATTACHMENT_SCRIPT"
	var attachment_script = load(attachment_script_path)
	if attachment_script == null:
		return "load_failed:" + attachment_script_path
	_checks["attachment_script_loads"] = true
	_checks["attachment_script_can_instantiate"] = attachment_script.can_instantiate()

	# 1. Constants keep the old card values (behavior parity).
	var default_rule = attachment_script.TARGET_DEFAULT_OFFSET_RULE
	_checks["default_rule_mode_front"] = str(default_rule.get("mode")) == "front"
	_checks["default_rule_world_space"] = str(default_rule.get("offset_space")) == "world"
	_checks["default_rule_distance"] = is_equal_approx(float(default_rule.get("distance_m")), 0.35)
	_checks["default_rule_fallback_hold"] = str(default_rule.get("fallback")) == "hold_last_pose"
	_checks["fallback_const_hold"] = str(attachment_script.TARGET_FALLBACK_HOLD_LAST_POSE) == "hold_last_pose"
	_checks["fallback_const_detach"] = str(attachment_script.TARGET_FALLBACK_DETACH) == "detach"
	_checks["fallback_const_fade_out"] = str(attachment_script.TARGET_FALLBACK_FADE_OUT) == "fade_out"

	var attachment = attachment_script.new()
	attachment.set_primary_card_id("CardAnchor")
	attachment.set_resolve_target(_resolve_target)
	attachment.set_card_anchor_provider(_get_anchor)
	attachment.set_on_attachments_updated(_on_updated)
	attachment.set_on_all_detached(_on_all_detached)

	# Scene-tree stage for global_transform reads.
	var stage := Node3D.new()
	stage.name = "ProbeStage"
	root.add_child(stage)
	_anchor = Node3D.new()
	_anchor.name = "CardAnchor"
	stage.add_child(_anchor)
	var target_node := Node3D.new()
	target_node.name = "TargetA"
	stage.add_child(target_node)
	target_node.position = Vector3(1.0, 2.0, 3.0)
	_targets["target_a"] = ProbeTargetAdapter.new(target_node)

	# 2. Offset-rule normalization.
	var norm_empty = attachment._normalize_target_offset_rule({})
	_checks["norm_empty_uses_defaults"] = str(norm_empty.get("mode")) == "front" \
		and str(norm_empty.get("offset_space")) == "world" \
		and is_equal_approx(float(norm_empty.get("distance_m")), 0.35) \
		and str(norm_empty.get("fallback")) == "hold_last_pose"
	var norm_string = attachment._normalize_target_offset_rule("right")
	_checks["norm_string_sets_mode_only"] = str(norm_string.get("mode")) == "right" \
		and str(norm_string.get("offset_space")) == "world" \
		and str(norm_string.get("fallback")) == "hold_last_pose"
	var norm_merged = attachment._normalize_target_offset_rule({"mode": "top", "fallback": "detach", "extra_key": 7})
	_checks["norm_dict_merges_over_defaults"] = str(norm_merged.get("mode")) == "top" \
		and str(norm_merged.get("fallback")) == "detach" \
		and is_equal_approx(float(norm_merged.get("distance_m")), 0.35) \
		and int(norm_merged.get("extra_key")) == 7
	_checks["norm_unsupported_type_uses_defaults"] = str(attachment._normalize_target_offset_rule(42).get("mode")) == "front"
	_checks["norm_does_not_mutate_default_rule"] = not attachment_script.TARGET_DEFAULT_OFFSET_RULE.has("extra_key")

	# 3. Every offset mode.
	var v_right_top: Vector3 = attachment._target_offset_vector({"mode": "right_top"})
	_checks["offset_right_top_defaults"] = v_right_top.is_equal_approx(Vector3(0.35, 0.35, 0.0))
	var v_top_right: Vector3 = attachment._target_offset_vector({"mode": "top_right", "right_m": 0.1, "up_m": 0.2, "forward_m": 0.3})
	_checks["offset_top_right_alias"] = v_top_right.is_equal_approx(Vector3(0.1, 0.2, 0.3))
	var v_right: Vector3 = attachment._target_offset_vector({"mode": "right", "distance_m": 0.5})
	_checks["offset_right_mode"] = v_right.is_equal_approx(Vector3(0.5, 0.0, 0.0))
	var v_top: Vector3 = attachment._target_offset_vector({"mode": "top", "distance_m": 0.5})
	_checks["offset_top_mode"] = v_top.is_equal_approx(Vector3(0.0, 0.5, 0.0))
	var v_front: Vector3 = attachment._target_offset_vector({"mode": "front", "distance_m": 0.5})
	_checks["offset_front_mode"] = v_front.is_equal_approx(Vector3(0.0, 0.0, -0.5))
	var v_custom: Vector3 = attachment._target_offset_vector({"mode": "custom", "x_m": 1.0, "y_m": 2.0})
	_checks["offset_custom_xyz_with_z_default"] = v_custom.is_equal_approx(Vector3(1.0, 2.0, -0.35))

	# 4. Both offset spaces against a rotated target transform.
	var rotated := Transform3D(Basis(Vector3.UP, PI * 0.5), Vector3(1.0, 2.0, 3.0))
	var world_result: Transform3D = attachment._target_offset_transform(rotated, {"mode": "right", "distance_m": 0.5, "offset_space": "world"})
	_checks["world_space_ignores_target_rotation"] = world_result.origin.is_equal_approx(Vector3(1.5, 2.0, 3.0))
	_checks["world_space_identity_basis"] = world_result.basis.is_equal_approx(Basis.IDENTITY)
	var local_result: Transform3D = attachment._target_offset_transform(rotated, {"mode": "right", "distance_m": 0.5, "offset_space": "target"})
	_checks["target_space_rotates_offset"] = local_result.origin.is_equal_approx(Vector3(1.0, 2.0, 2.5))
	_checks["target_space_keeps_target_basis"] = local_result.basis.is_equal_approx(rotated.basis)

	# 5. Attach bookkeeping + snapshot-feeding getters.
	_checks["attach_unknown_target_rejected"] = attachment.attach("CardAnchor", "missing", {}) == false
	_checks["unknown_target_not_recorded"] = attachment.attachment_count() == 0
	var attached: bool = attachment.attach("CardAnchor", "target_a", {"mode": "right", "distance_m": 0.5, "offset_space": "world", "fallback": "hold_last_pose"})
	_mode = "target"  # the card flips _anchor_mode after a true attach
	_checks["attach_known_target"] = attached == true
	_checks["attach_records_attachment"] = attachment.attachment_count() == 1 and attachment.has_attachment("CardAnchor")
	_checks["card_target_id_getter"] = attachment.card_target_id("CardAnchor") == "target_a"
	_checks["card_target_id_unknown_card_empty"] = attachment.card_target_id("Nope") == ""
	var resolved_position = attachment.card_resolved_position("CardAnchor")
	_checks["resolved_position_from_attach"] = resolved_position is Vector3 and resolved_position.is_equal_approx(Vector3(1.5, 2.0, 3.0))
	_checks["resolved_position_unknown_card_null"] = attachment.card_resolved_position("Nope") == null
	var entry = attachment.get_attachment("CardAnchor")
	_checks["get_attachment_returns_entry"] = typeof(entry) == TYPE_DICTIONARY and str(entry.get("fallback")) == "hold_last_pose"
	_checks["get_attachment_unknown_null"] = attachment.get_attachment("Nope") == null
	_checks["apply_count_starts_zero"] = attachment.apply_count() == 0

	# 6. update_attachments applies the offset transform + counters/hooks.
	_anchor.visible = false
	var updates_before := _updated_calls
	attachment.update_attachments()
	_checks["update_moves_anchor"] = _anchor.global_transform.origin.is_equal_approx(Vector3(1.5, 2.0, 3.0))
	_checks["update_shows_anchor"] = _anchor.visible == true
	_checks["update_counts_apply"] = attachment.apply_count() == 1
	_checks["update_fires_updated_hook"] = _updated_calls == updates_before + 1

	# 7. last_transform tracks target moves.
	target_node.position = Vector3(4.0, 5.0, 6.0)
	attachment.update_attachments()
	var moved_position = attachment.card_resolved_position("CardAnchor")
	_checks["last_transform_tracks_target"] = moved_position is Vector3 and moved_position.is_equal_approx(Vector3(4.5, 5.0, 6.0))
	_checks["anchor_tracks_target"] = _anchor.global_transform.origin.is_equal_approx(Vector3(4.5, 5.0, 6.0))

	# 8. hold_last_pose fallback against a registered-then-freed target.
	target_node.free()
	_anchor.global_transform = Transform3D(Basis.IDENTITY, Vector3(9.0, 9.0, 9.0))
	var applies_before: int = attachment.apply_count()
	attachment.update_attachments()
	_checks["hold_restores_last_transform"] = _anchor.global_transform.origin.is_equal_approx(Vector3(4.5, 5.0, 6.0))
	_checks["hold_keeps_attachment"] = attachment.has_attachment("CardAnchor")
	_checks["hold_does_not_count_apply"] = attachment.apply_count() == applies_before
	_checks["hold_keeps_mode_target"] = _mode == "target"

	# 9. The same fallback fires for an unregistered target id.
	_targets.erase("target_a")
	_anchor.global_transform = Transform3D(Basis.IDENTITY, Vector3(8.0, 8.0, 8.0))
	attachment.update_attachments()
	_checks["unregistered_target_falls_back"] = _anchor.global_transform.origin.is_equal_approx(Vector3(4.5, 5.0, 6.0))

	# 10. detach empties the bookkeeping and fires the all-detached hook
	# (the card's detach-to-manual transition).
	attachment.detach("CardAnchor")
	_checks["detach_removes_attachment"] = attachment.attachment_count() == 0
	_checks["detach_last_fires_all_detached"] = _all_detached_calls == 1
	_checks["detach_transitions_mode_to_manual"] = _mode == "manual"

	# 11. fade_out fallback hides the anchor but keeps the attachment.
	var fade_node := Node3D.new()
	fade_node.name = "FadeTarget"
	stage.add_child(fade_node)
	fade_node.position = Vector3(0.0, 1.0, 0.0)
	_targets["fade_target"] = ProbeTargetAdapter.new(fade_node)
	attachment.attach("CardAnchor", "fade_target", {"mode": "front", "fallback": "fade_out"})
	_mode = "target"
	attachment.update_attachments()
	var visible_while_tracked := _anchor.visible
	_targets.erase("fade_target")
	attachment.update_attachments()
	_checks["fade_out_hides_anchor"] = visible_while_tracked == true and _anchor.visible == false
	_checks["fade_out_keeps_attachment"] = attachment.has_attachment("CardAnchor")
	_checks["fade_out_keeps_mode_target"] = _mode == "target"
	attachment.detach("CardAnchor")

	# 12. detach fallback removes the attachment and transitions to manual.
	var detach_node := Node3D.new()
	detach_node.name = "DetachTarget"
	stage.add_child(detach_node)
	_targets["detach_target"] = ProbeTargetAdapter.new(detach_node)
	attachment.attach("CardAnchor", "detach_target", {"mode": "front", "fallback": "detach"})
	_mode = "target"
	_targets.erase("detach_target")
	var detached_calls_before := _all_detached_calls
	attachment.update_attachments()
	_checks["detach_fallback_removes_attachment"] = attachment.has_attachment("CardAnchor") == false and attachment.attachment_count() == 0
	_checks["detach_fallback_fires_all_detached"] = _all_detached_calls == detached_calls_before + 1
	_checks["detach_fallback_transitions_to_manual"] = _mode == "manual"

	# 13. Single-attachment fallback lookup: a lone non-primary entry drives
	# the anchor (the values()[0] path).
	var side_node := Node3D.new()
	side_node.name = "SideTarget"
	stage.add_child(side_node)
	side_node.position = Vector3(2.0, 0.0, 0.0)
	_targets["side_target"] = ProbeTargetAdapter.new(side_node)
	attachment.attach("OtherCard", "side_target", {"mode": "right", "distance_m": 0.25, "offset_space": "world"})
	_mode = "target"
	attachment.update_attachments()
	_checks["single_non_primary_attachment_drives_anchor"] = _anchor.global_transform.origin.is_equal_approx(Vector3(2.25, 0.0, 0.0))

	# 14. The primary card id wins once present alongside another entry.
	var primary_node := Node3D.new()
	primary_node.name = "PrimaryTarget"
	stage.add_child(primary_node)
	primary_node.position = Vector3(-3.0, 1.0, 0.0)
	_targets["primary_target"] = ProbeTargetAdapter.new(primary_node)
	attachment.attach("CardAnchor", "primary_target", {"mode": "top", "distance_m": 1.0, "offset_space": "world"})
	attachment.update_attachments()
	_checks["primary_attachment_wins"] = _anchor.global_transform.origin.is_equal_approx(Vector3(-3.0, 2.0, 0.0))
	_checks["attachment_count_two"] = attachment.attachment_count() == 2

	# 15. Detaching while entries remain keeps the all-detached hook silent.
	var hook_calls_before := _all_detached_calls
	attachment.detach("OtherCard")
	_checks["detach_with_remaining_keeps_hook_silent"] = _all_detached_calls == hook_calls_before and attachment.attachment_count() == 1
	attachment.detach("CardAnchor")
	_checks["detach_final_fires_hook_again"] = _all_detached_calls == hook_calls_before + 1

	# 16. Two attachments without the primary key skip the update pass
	# entirely (no hook, anchor untouched) - the old early-return behavior.
	attachment.attach("CardA", "side_target", "right")
	attachment.attach("CardB", "side_target", "right")
	var updates_before_ambiguous := _updated_calls
	var anchor_before_ambiguous := _anchor.global_transform
	attachment.update_attachments()
	_checks["ambiguous_attachments_skip_update"] = _updated_calls == updates_before_ambiguous \
		and _anchor.global_transform == anchor_before_ambiguous
	attachment.detach("CardA")
	attachment.detach("CardB")

	# 17. update with no attachments is a no-op (no hook).
	var updates_before_empty := _updated_calls
	attachment.update_attachments()
	_checks["update_without_attachments_is_noop"] = _updated_calls == updates_before_empty

	# 18. An unwired instance stays inert (no resolver -> attach rejected, no
	# anchor provider -> update returns, no hooks -> detach safe).
	var bare = attachment_script.new()
	_checks["unwired_attach_rejected"] = bare.attach("CardAnchor", "target_a", {}) == false
	bare.update_attachments()
	bare.detach("CardAnchor")
	_checks["unwired_update_and_detach_safe"] = bare.attachment_count() == 0

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
		"harness": "script_only_card_attachment_probe",
		"checks": _checks,
		"failed": failed,
		"error": _error,
		"exit_code": exit_code,
	}
	var status_path := OS.get_environment("SMARTXR_CARD_ATTACHMENT_PROBE_STATUS_PATH")
	if status_path.is_empty():
		status_path = DEFAULT_STATUS_RES
	var file := FileAccess.open(status_path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(status, "  "))
		file.close()
	print("card_attachment_probe: %s (failed=%s error=%s)" % [
		"PASS" if exit_code == 0 else "FAIL",
		",".join(PackedStringArray(failed)) if failed.size() > 0 else "-",
		_error,
	])
