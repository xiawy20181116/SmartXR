# VSTCapture subsystem (Godot)

`godot-android/scripts/vst_capture.gd` (`VSTCapture`) contains the local VST
capture, right-eye tracker polling, calibration diagnostics, and bbox-to-head
math that used to live inside `AndroidMovingCard.gd`.

The script is dependency-free and probe-loadable. It owns SDK interaction and
calculation state; the card keeps target registration, attachment, and final
status snapshot composition. Scene-side VST debug visuals are delegated by the
card to `VSTDebugUI` (`docs/vst_debug_ui.md`).

## Responsibilities

| API | Meaning |
|---|---|
| `setup_capture(xr_active)` | Gates VST on OpenXR activity, instantiates `GXRDualVstCapture`, stages ncnn assets, initializes capture, and reads calibration diagnostics. |
| `poll()` | Polls the right image, tracker boxes, total tracker latency, and emits callbacks for card-owned side effects. |
| `shutdown()` | Calls the native capture shutdown method when available. |
| `anchor_from_bbox(...)` | Converts bbox center/size/image/depth into yaw, pitch, depth, and angular size. |
| `target_position_from_bbox_anchor(...)` | Converts an anchor dictionary into the head-space target position. |
| `store_right_eye_to_head_matrix(...)` | Stores the right-eye calibration matrix and enables the matrix path only on valid responses. |
| `tracker_box_to_target_transform(...)` | Converts the first tracker box into a target transform using the same bbox math. |
| `status_snapshot()` | Returns the VST status fields consumed by `AndroidMovingCard.gd` and `StatusHud`. |

## Callback seam

The card wires three callbacks:

| Callback | Payload |
|---|---|
| `set_raw_image_callback(callable)` | `Image`, image size, and frame count; the card forwards the visual update to `VSTDebugUI`. |
| `set_boxes_callback(callable)` | Tracker boxes plus image size; the card forwards raw overlay updates to `VSTDebugUI`. |
| `set_anchor_callback(callable)` | Bbox center/size/image, angular size, confidence, target transform, and update count for target-source update and diagnostics printing. |

This keeps native polling and math in the subsystem while preserving the card's
existing public API and scene ownership.

## Runtime verification

```powershell
powershell -File tools\run_godot_vst_capture_probe.ps1
```

The probe runs `godot-android/tests/script_only_vst_capture_probe.gd` in
no-project mode. It verifies default status fields, OpenXR-inactive gating,
head-convention conversion, the right-eye matrix path, bbox center math, tracker
box transform generation, and anchor callback payloads.

The legacy bbox fixture probe remains:

```powershell
powershell -File tools\run_godot_bbox_math_probe.ps1
```

That probe still locks the public card wrapper math to
`godot-android/fixtures/bbox_math_test_vectors.json`.
