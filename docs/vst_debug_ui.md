# VSTDebugUI subsystem (Godot)

`godot-android/scripts/vst_debug_ui.gd` (`VSTDebugUI`) contains the VST debug
scene visuals that used to live inside `AndroidMovingCard.gd`.

The script is dependency-free and probe-loadable. It owns scene-node creation
and visual updates for the world-space bbox frame, raw right-image `Sprite3D`,
raw-image bbox overlay quads, and raw debug label. It does not own VST capture,
bbox math, target updates, attachment, or status snapshots.

## Responsibilities

| API | Meaning |
|---|---|
| `build_world_bbox_frame(parent)` | Creates the hidden `VSTBBoxFrame` anchor and four frame quads under the supplied scene parent. |
| `build_raw_debug_panel(camera)` | Creates `VSTRawDebugPanel`, `VSTRawRightImage`, four raw bbox quads, and the raw metadata label under the camera. |
| `update_world_bbox_frame(...)` | Applies visibility, position, optional card-provided orientation, and quad sizing for the world-space bbox frame. |
| `update_raw_image(image, image_size)` | Converts the latest right-eye `Image` into the raw debug sprite texture. |
| `update_raw_frame_metadata(frame_id, exposure_timestamp)` | Updates the raw debug label with the current frame id and exposure timestamp; negative timestamp renders as `n/a`. |
| `update_raw_bbox_overlay(boxes, image_size)` | Sizes and positions the raw-image bbox quads from normalized tracker boxes. |
| `set_world_bbox_visible(...)` / `set_raw_bbox_visible(...)` | Explicit visibility controls used when the card resets or loses boxes. |

## Card boundary

`AndroidMovingCard.gd` instantiates `VSTDebugUI` and delegates only visual work
to it. The card still owns:

- `VSTCapture` callbacks and polling.
- Bbox state (`_bbox_center_px`, `_bbox_size_px`, `_bbox_depth_m`,
  `_bbox_angular_size_deg`).
- Target-source updates and card attachment.
- Whether the world bbox frame should face the camera.
- Status snapshot composition for `StatusHud`.

This keeps the debug UI isolated without moving VST data ownership or changing
public card APIs such as `register_node3d_target`, `attach_to_target`, or
`update_vst_target`.

## Runtime verification

```powershell
powershell -File tools\run_godot_vst_debug_ui_probe.ps1
```

The probe runs `godot-android/tests/script_only_vst_debug_ui_probe.gd` in
no-project mode. It verifies node construction/parenting, raw image texture
updates, raw metadata label updates, raw bbox overlay sizing and hide behavior,
world bbox frame sizing, and explicit visibility control.
