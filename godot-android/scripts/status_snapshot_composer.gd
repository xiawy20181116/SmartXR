extends RefCounted

## Dependency-free status snapshot composition for AndroidMovingCard.
##
## The card resolves live values from nodes and subsystems. This helper owns
## only the stable dictionary shape consumed by StatusHud and status files.


func build_status_snapshot(values: Dictionary) -> Dictionary:
	return {
		"ws_connected": values.get("ws_connected"),
		"last_command": values.get("last_command"),
		"anchor_mode": values.get("anchor_mode"),
		"camera_position": values.get("camera_position"),
		"camera_rotation_degrees": values.get("camera_rotation_degrees"),
		"xr_origin_position": values.get("xr_origin_position"),
		"bbox_center_px": values.get("bbox_center_px"),
		"bbox_size_px": values.get("bbox_size_px"),
		"bbox_depth_m": values.get("bbox_depth_m"),
		"anchor_yaw_deg": values.get("anchor_yaw_deg"),
		"anchor_pitch_deg": values.get("anchor_pitch_deg"),
		"anchor_depth_m": values.get("anchor_depth_m"),
		"bbox_angular_size_deg": values.get("bbox_angular_size_deg"),
		"card_rotation_degrees": values.get("card_rotation_degrees"),
		"speed_deg_per_second": values.get("speed_deg_per_second"),
		"paused": values.get("paused"),
		"corners": values.get("corners"),
		"viewport_use_xr": values.get("viewport_use_xr"),
		"viewport_transparent_bg": values.get("viewport_transparent_bg"),
		"xr": values.get("xr"),
		"vst": values.get("vst"),
		"proxy_targets": values.get("proxy_targets"),
		"passthrough_overlay": values.get("passthrough_overlay"),
	}


func build_xr_status_snapshot(interface_found: bool, initialize_ok: bool, active: bool, init_error: String) -> Dictionary:
	return {
		"interface_found": interface_found,
		"initialize_ok": initialize_ok,
		"active": active,
		"init_error": init_error,
	}


func build_vst_status_snapshot(capture_snapshot: Dictionary, target_state: String) -> Dictionary:
	var snapshot := capture_snapshot.duplicate(true)
	snapshot["target_state"] = target_state
	return snapshot


func build_proxy_targets_status_snapshot(values: Dictionary) -> Dictionary:
	return {
		"ws_connected": values.get("ws_connected"),
		"ws_subscribed": values.get("ws_subscribed"),
		"ws_url": values.get("ws_url"),
		"attachments": values.get("attachments"),
		"card_target_id": values.get("card_target_id"),
		"proxy_target_count": values.get("proxy_target_count"),
		"proxy_target_ids": values.get("proxy_target_ids"),
		"last_position": values.get("last_position"),
		"card_resolved_position": values.get("card_resolved_position"),
		"card_node_position": values.get("card_node_position"),
		"card_apply_count": values.get("card_apply_count"),
		"packets": values.get("packets"),
		"parsed": values.get("parsed"),
		"live": values.get("live"),
		"sequence": values.get("sequence"),
		"packet_bytes": values.get("packet_bytes"),
		"packet_preview": values.get("packet_preview"),
		"message_type": values.get("message_type"),
		"source_coordinate": values.get("source_coordinate"),
		"world_from_head_applied": values.get("world_from_head_applied"),
		"local_position": values.get("local_position"),
		"runtime_local_position": values.get("runtime_local_position"),
		"world_position": values.get("world_position"),
		"head_z_mode": values.get("head_z_mode"),
		"anchor_mode": values.get("anchor_mode"),
		"world_latched": values.get("world_latched"),
		"world_latch_state": values.get("world_latch_state"),
		"error": values.get("error"),
	}


func build_passthrough_overlay_status_snapshot(values: Dictionary) -> Dictionary:
	return {
		"enabled": values.get("enabled"),
		"requested_blend_mode": values.get("requested_blend_mode"),
		"blend_request_ok": values.get("blend_request_ok"),
		"layer_created": values.get("layer_created"),
		"layer_visible": values.get("layer_visible"),
		"layer_alpha_blend": values.get("layer_alpha_blend"),
		"layer_position": values.get("layer_position"),
	}
