extends SceneTree

## Script-only runtime probe for the card attachment subsystem (M3 step 4,
## YAN-77).
##
## Runs in no-project mode like the other script-only probes (a project run
## would boot the full main scene, which never exits headless):
##   godot --headless --script <abs path to this file>
## with the subsystem script injected via env:
##   SMARTXR_CARD_ATTACHMENT_SCRIPT             abs path to card_attachment.gd
##   SMARTXR_CARD_ATTACHMENT_PROBE_STATUS_PATH  abs path for the probe result
##                                              JSON (optional)
##
## Verifies at runtime: the offset-rule math (normalize defaults/merge/string
## form, every offset mode, world vs target offset_space), the attach/detach
## lifecycle (resolver rejection, record shape, default rule when omitted,
## primary-attachment selection), the per-frame pass applying a live target
## to the anchor, and each fallback mode (hold_last_pose / detach / fade_out)
## against an unavailable or resolver-missing target. Exits 0 only if every
## check passed.

const DEFAULT_STATUS_RES := "user://card_attachment_probe_status.json"

var _checks := {}
var _error := "-"
var _exit_code := 1
var _ran := false

var _adapters := {}
var _applied_count := 0
var _detached_ids := []
var _attachment_for_detach = null


## Stand-in for the TargetRegistry Node3DTargetAdapter: the subsystem only
## needs is_available() / get_global_transform(), so the probe can flip
## availability and move the target without a scene node.
class FakeTargetAdapter:
	var transform := Transform3D.IDENTITY
	var available := true

	func is_available() -> bool:
		return available

	func get_global_transform() -> Transform3D:
		return transform


# Checks run from the first main-loop iteration instead of _initialize: the
# anchor's global_transform errors with "!is_inside_tree()" until the root
# Window has entered the tree, and quit() inside _initialize is not honored
# in script-only mode (same rule as the other script-only probes).
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


func _resolve_adapter(target_id: String):
	return _adapters.get(target_id)


func _on_applied() -> void:
	_applied_count += 1


func _on_detach(card_id: String) -> void:
	_detached_ids.append(card_id)
	if _attachment_for_detach != null:
		_attachment_for_detach.detach(card_id)


func _run_checks() -> String:
	var attachment_script_path := OS.get_environment("SMARTXR_CARD_ATTACHMENT_SCRIPT")
	if attachment_script_path.is_empty():
		return "missing_env:SMARTXR_CARD_ATTACHMENT_SCRIPT"
	var attachment_script = load(attachment_script_path)
	if attachment_script == null:
		return "load_failed:" + attachment_script_path
	_checks["attachment_script_loads"] = true
	_checks["attachment_script_can_instantiate"] = attachment_script.can_instantiate()

	# 1. Offset-rule normalization (static, called on the script).
	var defaults: Dictionary = attachment_script.normalize_offset_rule({})
	_checks["normalize_default_mode_front"] = str(defaults.get("mode")) == "front"
	_checks["normalize_default_space_world"] = str(defaults.get("offset_space")) == "world"
	_checks["normalize_default_fallback_hold"] = str(defaults.get("fallback")) == "hold_last_pose"
	var string_rule: Dictionary = attachment_script.normalize_offset_rule("right")
	_checks["normalize_string_sets_mode"] = str(string_rule.get("mode")) == "right" \
		and str(string_rule.get("offset_space")) == "world"
	var merged: Dictionary = attachment_script.normalize_offset_rule({"mode": "right_top", "right_m": 0.5, "fallback": "detach"})
	_checks["normalize_merges_custom_keys"] = str(merged.get("mode")) == "right_top" \
		and float(merged.get("right_m")) == 0.5 \
		and str(merged.get("fallback")) == "detach" \
		and str(merged.get("offset_space")) == "world"
	defaults["mode"] = "mutated"
	_checks["normalize_does_not_mutate_defaults"] = str(attachment_script.normalize_offset_rule({}).get("mode")) == "front"

	# 2. Offset vectors, every mode.
	_checks["offset_vector_front_default"] = Vector3(attachment_script.offset_vector({})).is_equal_approx(Vector3(0.0, 0.0, -0.35))
	_checks["offset_vector_front_distance"] = Vector3(attachment_script.offset_vector({"mode": "front", "distance_m": 1.0})).is_equal_approx(Vector3(0.0, 0.0, -1.0))
	_checks["offset_vector_right"] = Vector3(attachment_script.offset_vector("right")).is_equal_approx(Vector3(0.35, 0.0, 0.0))
	_checks["offset_vector_top"] = Vector3(attachment_script.offset_vector({"mode": "top", "distance_m": 0.2})).is_equal_approx(Vector3(0.0, 0.2, 0.0))
	_checks["offset_vector_right_top"] = Vector3(attachment_script.offset_vector({"mode": "right_top", "right_m": 0.4, "up_m": 0.25, "forward_m": 0.1})).is_equal_approx(Vector3(0.4, 0.25, 0.1))
	_checks["offset_vector_top_right_alias"] = Vector3(attachment_script.offset_vector({"mode": "top_right"})).is_equal_approx(Vector3(0.35, 0.35, 0.0))
	_checks["offset_vector_custom_xyz"] = Vector3(attachment_script.offset_vector({"mode": "custom", "x_m": 1.0, "y_m": 2.0, "z_m": 3.0})).is_equal_approx(Vector3(1.0, 2.0, 3.0))
	_checks["offset_vector_custom_default_z"] = Vector3(attachment_script.offset_vector({"mode": "custom"})).is_equal_approx(Vector3(0.0, 0.0, -0.35))

	# 3. Offset transforms: world space ignores target rotation, target space
	# follows it.
	var rotated := Transform3D(Basis(Vector3.UP, PI / 2.0), Vector3(1.0, 2.0, 3.0))
	var front_half := {"mode": "front", "distance_m": 0.5}
	var world_transform: Transform3D = attachment_script.world_offset_transform(rotated, front_half)
	_checks["world_offset_ignores_rotation"] = world_transform.origin.is_equal_approx(Vector3(1.0, 2.0, 2.5)) \
		and world_transform.basis.is_equal_approx(Basis())
	var local_transform: Transform3D = attachment_script.local_offset_transform(rotated, front_half)
	_checks["local_offset_follows_rotation"] = local_transform.origin.is_equal_approx(Vector3(0.5, 2.0, 3.0)) \
		and local_transform.basis.is_equal_approx(rotated.basis)
	var dispatched_world: Transform3D = attachment_script.offset_transform(rotated, front_half)
	_checks["offset_transform_world_by_default"] = dispatched_world.origin.is_equal_approx(world_transform.origin) \
		and dispatched_world.basis.is_equal_approx(Basis())
	var target_space_rule := {"mode": "front", "distance_m": 0.5, "offset_space": "target"}
	var dispatched_local: Transform3D = attachment_script.offset_transform(rotated, target_space_rule)
	_checks["offset_transform_target_space_local"] = dispatched_local.origin.is_equal_approx(local_transform.origin) \
		and dispatched_local.basis.is_equal_approx(rotated.basis)

	# Scene-tree stage for anchor global_transform reads/writes.
	var stage := Node3D.new()
	stage.name = "ProbeStage"
	root.add_child(stage)
	var anchor := Node3D.new()
	anchor.name = "CardAnchorProbe"
	stage.add_child(anchor)

	# 4. Attach/detach lifecycle.
	var unwired = attachment_script.new()
	_checks["attach_without_resolver_rejected"] = unwired.attach("CardAnchor", "t1") == false and unwired.is_empty()

	var attachment = attachment_script.new()
	attachment.set_resolver(_resolve_adapter)
	attachment.set_on_applied(_on_applied)

	var target := FakeTargetAdapter.new()
	target.transform = Transform3D(Basis(), Vector3(1.0, 2.0, 3.0))
	_adapters["t1"] = target

	_checks["attach_unknown_target_rejected"] = attachment.attach("CardAnchor", "nope") == false and attachment.is_empty()
	_checks["attach_known_target"] = attachment.attach("CardAnchor", "t1", front_half) == true \
		and attachment.size() == 1 and attachment.has_attachment("CardAnchor")
	_checks["attached_target_id_reports"] = attachment.attached_target_id("CardAnchor") == "t1" \
		and attachment.attached_target_id("missing") == ""
	var seeded = attachment.last_resolved_position("CardAnchor")
	_checks["attach_seeds_last_transform"] = seeded is Vector3 and Vector3(seeded).is_equal_approx(Vector3(1.0, 2.0, 2.5))
	_checks["last_resolved_position_null_when_missing"] = attachment.last_resolved_position("missing") == null
	var record = attachment.get_attachment("CardAnchor")
	_checks["get_attachment_records_rule"] = typeof(record) == TYPE_DICTIONARY \
		and str(record.get("fallback")) == "hold_last_pose" \
		and str(record.get("offset_rule", {}).get("mode")) == "front"
	_checks["get_attachment_null_when_missing"] = attachment.get_attachment("missing") == null

	attachment.detach("never_attached")
	_checks["detach_unknown_is_noop"] = attachment.size() == 1

	# 5. Per-frame pass against a live target.
	target.transform = Transform3D(Basis(), Vector3(4.0, 5.0, 6.0))
	_checks["update_processes_attachment"] = attachment.update_attachments(anchor, "CardAnchor") == true
	_checks["update_applies_target_transform"] = anchor.global_transform.origin.is_equal_approx(Vector3(4.0, 5.0, 5.5)) \
		and anchor.visible == true
	_checks["update_fires_on_applied"] = _applied_count == 1
	var refreshed = attachment.last_resolved_position("CardAnchor")
	_checks["update_refreshes_last_transform"] = refreshed is Vector3 and Vector3(refreshed).is_equal_approx(Vector3(4.0, 5.0, 5.5))

	var empty_store = attachment_script.new()
	empty_store.set_resolver(_resolve_adapter)
	_checks["update_empty_store_skips"] = empty_store.update_attachments(anchor, "CardAnchor") == false

	# Primary selection: a single non-primary attachment is still driven, and
	# the default offset rule applies when the rule is omitted at attach time.
	var other_anchor := Node3D.new()
	other_anchor.name = "OtherAnchorProbe"
	stage.add_child(other_anchor)
	var single_other = attachment_script.new()
	single_other.set_resolver(_resolve_adapter)
	_checks["attach_default_rule_when_omitted"] = single_other.attach("OtherCard", "t1") == true
	_checks["update_single_other_card_processed"] = single_other.update_attachments(other_anchor, "CardAnchor") == true \
		and other_anchor.global_transform.origin.is_equal_approx(Vector3(4.0, 5.0, 6.0 - 0.35))
	single_other.attach("ThirdCard", "t1")
	_checks["update_two_attachments_without_primary_skips"] = single_other.update_attachments(other_anchor, "CardAnchor") == false

	# 6. Fallback: hold_last_pose (default) against an unavailable target,
	# then against a target the resolver no longer knows.
	anchor.global_transform = Transform3D(Basis(), Vector3(10.0, 10.0, 10.0))
	target.available = false
	_checks["fallback_hold_processes"] = attachment.update_attachments(anchor, "CardAnchor") == true
	_checks["fallback_hold_restores_last_pose"] = anchor.global_transform.origin.is_equal_approx(Vector3(4.0, 5.0, 5.5)) \
		and anchor.visible == true
	_checks["fallback_does_not_fire_on_applied"] = _applied_count == 1

	_adapters.erase("t1")
	anchor.global_transform = Transform3D(Basis(), Vector3(10.0, 10.0, 10.0))
	_checks["fallback_missing_target_holds"] = attachment.update_attachments(anchor, "CardAnchor") == true \
		and anchor.global_transform.origin.is_equal_approx(Vector3(4.0, 5.0, 5.5))
	_adapters["t1"] = target

	# 7. Fallback: fade_out hides the anchor without moving it.
	target.available = true
	attachment.attach("CardAnchor", "t1", {"mode": "front", "distance_m": 0.5, "fallback": "fade_out"})
	attachment.update_attachments(anchor, "CardAnchor")
	var faded_pose := anchor.global_transform.origin
	target.available = false
	_checks["fallback_fade_out_processes"] = attachment.update_attachments(anchor, "CardAnchor") == true
	_checks["fallback_fade_out_hides"] = anchor.visible == false
	_checks["fallback_fade_out_keeps_pose"] = anchor.global_transform.origin.is_equal_approx(faded_pose)

	# 8. Fallback: detach empties the local store when no card callback is
	# wired, and routes through the callback (the card's detach_card) when it
	# is.
	target.available = true
	attachment.attach("CardAnchor", "t1", {"fallback": "detach"})
	attachment.update_attachments(anchor, "CardAnchor")
	_checks["update_reapply_restores_visible"] = anchor.visible == true
	target.available = false
	_checks["fallback_detach_empties_store"] = attachment.update_attachments(anchor, "CardAnchor") == true \
		and attachment.is_empty()

	target.available = true
	attachment.set_on_detach_card(_on_detach)
	_attachment_for_detach = attachment
	attachment.attach("CardAnchor", "t1", {"fallback": "detach"})
	target.available = false
	attachment.update_attachments(anchor, "CardAnchor")
	_checks["fallback_detach_routes_callable"] = _detached_ids == ["CardAnchor"] and attachment.is_empty()

	# 9. apply_fallback called directly with a stored record (the card's VST
	# lost-state path).
	target.available = true
	anchor.visible = true
	attachment.attach("CardAnchor", "t1", {"mode": "front", "distance_m": 0.5, "fallback": "fade_out"})
	var vst_record = attachment.get_attachment("CardAnchor")
	attachment.apply_fallback(vst_record, anchor, "CardAnchor")
	_checks["apply_fallback_direct_fade_out"] = anchor.visible == false

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
