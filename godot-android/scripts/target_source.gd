extends RefCounted
class_name TargetSource

## VST target-source subsystem (M4 step 2 of the YAN-73 encapsulation
## roadmap, extracted from AndroidMovingCard.gd).
##
## Owns the standard TrackableTarget record, the VST target adapter state
## machine (confidence gate, smoothing, velocity, predict/stale/lost timing),
## and a small duck-typed VSTTargetSource boundary. The card still owns scene
## registration, attachment, fallback side effects, bbox-to-head math, and
## status snapshot assembly; those side effects are injected as Callables.
##
## Keep this script dependency-free and loadable in no-project mode: no
## preloads, no env reads, no tree access of its own, and never reference its
## own class_name inside this file (global class registration does not happen
## in script-only probes; see tools/run_godot_target_source_probe.ps1).

const TRACKABLE_SOURCE_VST := "vst"
const TRACKABLE_SOURCE_EXTERNAL := "external"
const TRACKABLE_STATE_TRACKED := "tracked"
const TRACKABLE_STATE_PREDICTED := "predicted"
const TRACKABLE_STATE_STALE := "stale"
const TRACKABLE_STATE_LOST := "lost"


class TrackableTarget:
	var id: String = ""
	var transform: Transform3D = Transform3D.IDENTITY
	var velocity: Vector3 = Vector3.ZERO
	var confidence: float = 0.0
	var timestamp_ms: float = 0.0
	var state: String = TRACKABLE_STATE_LOST
	var source: String = TRACKABLE_SOURCE_EXTERNAL


class VSTTargetAdapter:
	var target := TrackableTarget.new()
	var _proxy: Node3D = null
	var _last_stable_transform := Transform3D.IDENTITY
	var _has_sample := false
	var _confidence_threshold := 0.45
	var _predict_ms := 180.0
	var _stale_ms := 650.0
	var _lost_ms := 1400.0
	var _smoothing_alpha := 0.38

	func _init(
		target_id: String,
		proxy: Node3D,
		confidence_threshold: float,
		predict_ms: float,
		stale_ms: float,
		lost_ms: float,
		smoothing_alpha: float
	) -> void:
		target.id = target_id
		target.source = TRACKABLE_SOURCE_VST
		_proxy = proxy
		_confidence_threshold = confidence_threshold
		_predict_ms = predict_ms
		_stale_ms = stale_ms
		_lost_ms = lost_ms
		_smoothing_alpha = clampf(smoothing_alpha, 0.0, 1.0)

	func update_target(target_id: String, transform: Transform3D, confidence: float, timestamp_ms: float) -> bool:
		if target_id.is_empty() or confidence < _confidence_threshold:
			return false
		var previous_origin := target.transform.origin
		var next_transform := transform
		if _has_sample:
			next_transform.origin = previous_origin.lerp(transform.origin, _smoothing_alpha)
			var dt_seconds := maxf((timestamp_ms - target.timestamp_ms) / 1000.0, 0.001)
			target.velocity = (next_transform.origin - previous_origin) / dt_seconds
		else:
			target.velocity = Vector3.ZERO
		target.id = target_id
		target.transform = next_transform
		target.confidence = clampf(confidence, 0.0, 1.0)
		target.timestamp_ms = timestamp_ms
		target.source = TRACKABLE_SOURCE_VST
		_last_stable_transform = next_transform
		_has_sample = true
		_set_state(TRACKABLE_STATE_TRACKED)
		_apply_to_proxy()
		return true

	func advance(now_ms: float) -> void:
		if not _has_sample:
			return
		var age_ms := now_ms - target.timestamp_ms
		if age_ms <= _predict_ms:
			_hold_last_pose()
		elif age_ms <= _stale_ms:
			_predict_pose(age_ms)
			_set_state(TRACKABLE_STATE_PREDICTED)
		elif age_ms <= _lost_ms:
			_hold_last_pose()
			_set_state(TRACKABLE_STATE_STALE)
		else:
			_hold_last_pose()
			_set_state(TRACKABLE_STATE_LOST)
		_apply_to_proxy()

	func _hold_last_pose() -> void:
		target.transform = _last_stable_transform

	func _predict_pose(age_ms: float) -> void:
		var predicted := _last_stable_transform
		predicted.origin += target.velocity * (age_ms / 1000.0)
		target.transform = predicted

	func _set_state(next_state: String) -> void:
		target.state = next_state

	func _apply_to_proxy() -> void:
		if _proxy != null and is_instance_valid(_proxy):
			_proxy.global_transform = target.transform


class VSTTargetSource:
	var _adapter = null
	var _on_target_updated := Callable()
	var _on_target_lost := Callable()
	var _last_reported_state := TRACKABLE_STATE_LOST

	func _init(
		target_id: String,
		proxy: Node3D,
		confidence_threshold: float,
		predict_ms: float,
		stale_ms: float,
		lost_ms: float,
		smoothing_alpha: float
	) -> void:
		_adapter = VSTTargetAdapter.new(
			target_id,
			proxy,
			confidence_threshold,
			predict_ms,
			stale_ms,
			lost_ms,
			smoothing_alpha
		)
		_last_reported_state = _adapter.target.state

	func set_on_target_updated(on_target_updated: Callable) -> void:
		_on_target_updated = on_target_updated

	func set_on_target_lost(on_target_lost: Callable) -> void:
		_on_target_lost = on_target_lost

	func update_target(target_id: String, transform: Transform3D, confidence: float, timestamp_ms: float) -> bool:
		if _adapter == null:
			return false
		if not _adapter.update_target(target_id, transform, confidence, timestamp_ms):
			return false
		_last_reported_state = _adapter.target.state
		if _on_target_updated.is_valid():
			_on_target_updated.call(_adapter.target.id, _adapter.target.transform)
		return true

	func advance(now_ms: float) -> void:
		if _adapter == null:
			return
		var previous_state := str(_adapter.target.state)
		_adapter.advance(now_ms)
		var next_state := str(_adapter.target.state)
		if next_state == TRACKABLE_STATE_LOST and previous_state != TRACKABLE_STATE_LOST:
			if _on_target_lost.is_valid():
				_on_target_lost.call(_adapter.target.id)
		_last_reported_state = next_state

	func target_state() -> String:
		if _adapter == null:
			return TRACKABLE_STATE_LOST
		return str(_adapter.target.state)

	func target() -> TrackableTarget:
		return _adapter.target
