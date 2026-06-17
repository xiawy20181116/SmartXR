extends RefCounted
class_name TrackedTargetCardView

## Module-2 View seam for the tracked-target card (D2 Phase C, §16). Mirrors the
## assistant trio's AssistantCardView: presentation only. It composes the two
## existing presenter helpers the card already used directly:
##   - card_view.gd               (main card SubViewport/UI, panel mesh, XR probe)
##   - passthrough_overlay_presenter.gd (Antman passthrough composition layer)
##
## AndroidMovingCard keeps the XR lifecycle, motion, orientation, attachment, and
## status assembly; it news the two helpers (it owns the res:// preloads) and
## injects them here via bind(). This seam only forwards build/update/status
## calls, so runtime behaviour is byte-for-byte the same as the inline calls.
##
## Keep this script dependency-free and loadable in no-project mode: no preloads,
## no env reads, no tree access of its own, and never reference its own
## class_name inside this file (see tools/run_godot_tracked_target_card_view_probe.ps1).

var _card_view = null
var _overlay_presenter = null


func bind(card_view, overlay_presenter) -> void:
	_card_view = card_view
	_overlay_presenter = overlay_presenter


# --- Main card view (delegates to card_view.gd) ---

func build_card(parent: Node, anchor_name: String) -> void:
	if _card_view != null:
		_card_view.build(parent, anchor_name)


func build_xr_render_probe():
	if _card_view == null:
		return null
	return _card_view.build_xr_render_probe()


func viewport():
	if _card_view == null:
		return null
	return _card_view.viewport()


func anchor():
	if _card_view == null:
		return null
	return _card_view.anchor()


func card_mesh():
	if _card_view == null:
		return null
	return _card_view.card_mesh()


# --- Passthrough overlay (delegates to passthrough_overlay_presenter.gd) ---

func overlay_enabled_from_env(env_name: String) -> bool:
	if _overlay_presenter == null:
		return false
	return _overlay_presenter.overlay_enabled_from_env(env_name)


func build_overlay_layer(parent: Node, xr_active: bool, enabled: bool) -> void:
	if _overlay_presenter != null:
		_overlay_presenter.build_layer(parent, xr_active, enabled)


func update_overlay_layer(camera: Node3D) -> void:
	if _overlay_presenter != null:
		_overlay_presenter.update_layer(camera)


func overlay_layer_alpha_blend() -> bool:
	if _overlay_presenter == null:
		return false
	return _overlay_presenter.layer_alpha_blend()


## Untyped return: Vector3 when the layer exists, null otherwise (StatusHud
## formats null as "n/a").
func overlay_layer_position():
	if _overlay_presenter == null:
		return null
	return _overlay_presenter.layer_position()


func overlay_status_values(enabled: bool, requested_blend_mode: String, blend_request_ok: bool) -> Dictionary:
	if _overlay_presenter == null:
		return {}
	return _overlay_presenter.status_values(enabled, requested_blend_mode, blend_request_ok)
