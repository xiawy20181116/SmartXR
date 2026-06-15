extends RefCounted
class_name CommandDispatcher

## Dependency-free command state reducer extracted from AndroidMovingCard.gd.
##
## Parses control commands and updates only plain state Dictionaries. Scene
## side effects stay card-side: the reducer returns effect names for bbox
## anchor recompute, 3DoF transform apply, debug target operations, and VST
## bbox visibility. Keep this script loadable in no-project script-only probes:
## no preloads, no env reads, no tree access, and no self-reference to
## CommandDispatcher inside this file.

const EFFECT_APPLY_BBOX_ANCHOR := "apply_bbox_anchor"
const EFFECT_APPLY_3DOF_ANCHOR := "apply_3dof_anchor"
const EFFECT_DEBUG_TARGET_FREE := "debug_target_free"
const EFFECT_DEBUG_TARGET_RESET := "debug_target_reset"
const EFFECT_HIDE_VST_BBOX_FRAME := "hide_vst_bbox_frame"


static func default_config(overrides: Dictionary = {}) -> Dictionary:
	var config := {
		"start_yaw_deg": 0.0,
		"start_pitch_deg": 0.0,
		"start_depth_m": 1.35,
		"default_speed_deg_per_second": 0.0,
		"yaw_step_deg": 3.0,
		"pitch_step_deg": 3.0,
		"depth_step_m": 0.10,
		"bbox_center_step_px": 32.0,
		"bbox_depth_step_m": 0.10,
		"speed_step_deg_per_second": 2.0,
		"min_speed_deg_per_second": 0.0,
		"max_speed_deg_per_second": 45.0,
		"min_depth_m": 0.65,
		"max_depth_m": 4.0,
		"bbox_start_center_px": Vector2(436.0, 326.0),
		"bbox_start_size_px": Vector2(180.0, 240.0),
		"bbox_image_size": Vector2(872.0, 652.0),
	}
	for key in overrides.keys():
		config[key] = overrides[key]
	return config


static func default_state(config: Dictionary) -> Dictionary:
	return {
		"speed_deg_per_second": float(config.get("default_speed_deg_per_second", 0.0)),
		"anchor_yaw_deg": float(config.get("start_yaw_deg", 0.0)),
		"anchor_pitch_deg": float(config.get("start_pitch_deg", 0.0)),
		"anchor_depth_m": float(config.get("start_depth_m", 1.35)),
		"anchor_mode": "manual",
		"bbox_center_px": Vector2(config.get("bbox_start_center_px", Vector2(436.0, 326.0))),
		"bbox_size_px": Vector2(config.get("bbox_start_size_px", Vector2(180.0, 240.0))),
		"bbox_image_size": Vector2(config.get("bbox_image_size", Vector2(872.0, 652.0))),
		"bbox_depth_m": float(config.get("start_depth_m", 1.35)),
		"bbox_angular_size_deg": Vector2.ZERO,
		"paused": false,
		"last_command": "none",
		"effects": [],
	}


static func apply_command(state: Dictionary, command: String, config: Dictionary) -> Dictionary:
	var next_state := _copy_state(state)
	var effects := []
	next_state["last_command"] = command
	match command:
		"yaw_left", "left", "move_left", "a":
			next_state["anchor_mode"] = "manual"
			next_state["anchor_yaw_deg"] = float(next_state.get("anchor_yaw_deg", 0.0)) - float(config.get("yaw_step_deg", 3.0))
		"yaw_right", "right", "move_right", "d":
			next_state["anchor_mode"] = "manual"
			next_state["anchor_yaw_deg"] = float(next_state.get("anchor_yaw_deg", 0.0)) + float(config.get("yaw_step_deg", 3.0))
		"pitch_up", "up", "move_up", "w":
			next_state["anchor_mode"] = "manual"
			next_state["anchor_pitch_deg"] = float(next_state.get("anchor_pitch_deg", 0.0)) + float(config.get("pitch_step_deg", 3.0))
		"pitch_down", "down", "move_down", "s":
			next_state["anchor_mode"] = "manual"
			next_state["anchor_pitch_deg"] = float(next_state.get("anchor_pitch_deg", 0.0)) - float(config.get("pitch_step_deg", 3.0))
		"depth_in", "closer":
			next_state["anchor_mode"] = "manual"
			next_state["anchor_depth_m"] = clampf(
				float(next_state.get("anchor_depth_m", 1.35)) - float(config.get("depth_step_m", 0.10)),
				float(config.get("min_depth_m", 0.65)),
				float(config.get("max_depth_m", 4.0))
			)
		"depth_out", "farther":
			next_state["anchor_mode"] = "manual"
			next_state["anchor_depth_m"] = clampf(
				float(next_state.get("anchor_depth_m", 1.35)) + float(config.get("depth_step_m", 0.10)),
				float(config.get("min_depth_m", 0.65)),
				float(config.get("max_depth_m", 4.0))
			)
		"toggle_bbox_mode":
			next_state["anchor_mode"] = "manual" if str(next_state.get("anchor_mode", "manual")) == "bbox" else "bbox"
			if str(next_state.get("anchor_mode", "manual")) == "bbox":
				effects.append(EFFECT_APPLY_BBOX_ANCHOR)
		"bbox_left":
			next_state["anchor_mode"] = "bbox"
			next_state["bbox_center_px"] = _stepped_bbox_center(next_state, config, -float(config.get("bbox_center_step_px", 32.0)), 0.0)
			effects.append(EFFECT_APPLY_BBOX_ANCHOR)
		"bbox_right":
			next_state["anchor_mode"] = "bbox"
			next_state["bbox_center_px"] = _stepped_bbox_center(next_state, config, float(config.get("bbox_center_step_px", 32.0)), 0.0)
			effects.append(EFFECT_APPLY_BBOX_ANCHOR)
		"bbox_up":
			next_state["anchor_mode"] = "bbox"
			next_state["bbox_center_px"] = _stepped_bbox_center(next_state, config, 0.0, -float(config.get("bbox_center_step_px", 32.0)))
			effects.append(EFFECT_APPLY_BBOX_ANCHOR)
		"bbox_down":
			next_state["anchor_mode"] = "bbox"
			next_state["bbox_center_px"] = _stepped_bbox_center(next_state, config, 0.0, float(config.get("bbox_center_step_px", 32.0)))
			effects.append(EFFECT_APPLY_BBOX_ANCHOR)
		"bbox_depth_in":
			next_state["anchor_mode"] = "bbox"
			next_state["bbox_depth_m"] = clampf(
				float(next_state.get("bbox_depth_m", 1.35)) - float(config.get("bbox_depth_step_m", 0.10)),
				float(config.get("min_depth_m", 0.65)),
				float(config.get("max_depth_m", 4.0))
			)
			effects.append(EFFECT_APPLY_BBOX_ANCHOR)
		"bbox_depth_out":
			next_state["anchor_mode"] = "bbox"
			next_state["bbox_depth_m"] = clampf(
				float(next_state.get("bbox_depth_m", 1.35)) + float(config.get("bbox_depth_step_m", 0.10)),
				float(config.get("min_depth_m", 0.65)),
				float(config.get("max_depth_m", 4.0))
			)
			effects.append(EFFECT_APPLY_BBOX_ANCHOR)
		"speed_up", "plus":
			next_state["speed_deg_per_second"] = clampf(
				float(next_state.get("speed_deg_per_second", 0.0)) + float(config.get("speed_step_deg_per_second", 2.0)),
				float(config.get("min_speed_deg_per_second", 0.0)),
				float(config.get("max_speed_deg_per_second", 45.0))
			)
		"speed_down", "minus":
			next_state["speed_deg_per_second"] = clampf(
				float(next_state.get("speed_deg_per_second", 0.0)) - float(config.get("speed_step_deg_per_second", 2.0)),
				float(config.get("min_speed_deg_per_second", 0.0)),
				float(config.get("max_speed_deg_per_second", 45.0))
			)
		"pause", "toggle_pause", "space":
			next_state["paused"] = not bool(next_state.get("paused", false))
		"debug_target_free":
			effects.append(EFFECT_DEBUG_TARGET_FREE)
		"debug_target_reset":
			effects.append(EFFECT_DEBUG_TARGET_RESET)
		"reset", "r":
			next_state = default_state(config)
			next_state["last_command"] = command
			effects.append(EFFECT_HIDE_VST_BBOX_FRAME)
	effects.append(EFFECT_APPLY_3DOF_ANCHOR)
	next_state["effects"] = effects
	return next_state


static func _copy_state(state: Dictionary) -> Dictionary:
	var copied := {}
	for key in state.keys():
		copied[key] = state[key]
	return copied


static func _stepped_bbox_center(state: Dictionary, config: Dictionary, dx: float, dy: float) -> Vector2:
	var center := Vector2(state.get("bbox_center_px", config.get("bbox_start_center_px", Vector2(436.0, 326.0))))
	var image_size := Vector2(state.get("bbox_image_size", config.get("bbox_image_size", Vector2(872.0, 652.0))))
	return Vector2(
		clampf(center.x + dx, 0.0, image_size.x),
		clampf(center.y + dy, 0.0, image_size.y)
	)
