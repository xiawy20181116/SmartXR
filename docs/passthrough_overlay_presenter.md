# PassthroughOverlayPresenter

`godot-android/scripts/passthrough_overlay_presenter.gd` owns the Antman
passthrough overlay scene nodes.

The script is dependency-free and probe-loadable. It does not own XR startup,
blend-mode negotiation, status file writes, or VST state. `AndroidMovingCard.gd`
keeps those lifecycle decisions and passes the resolved state into the
presenter.

## Boundary

| API | Caller | Responsibility |
| --- | --- | --- |
| `overlay_enabled_from_env(env_name)` | Card | Reads the existing overlay enable env var through the presenter boundary. |
| `overlay_enabled_from_value(value)` | Probe / tests | Pure parser for accepted truthy values: `1`, `true`, `yes`, `on`. |
| `build_layer(parent, xr_active, enabled)` | Card / probes | Creates the transparent `SubViewport`, overlay UI, and `OpenXRCompositionLayerQuad` only when both gates are true. |
| `update_layer(camera)` | Card / probes | Places the overlay layer in front of the camera at the configured depth. |
| `status_values(enabled, requested_blend_mode, blend_request_ok)` | Card / probes | Returns the overlay status fragment values consumed by `StatusSnapshotComposer`. |
| `layer_alpha_blend()` / `layer_position()` | Card / probes | Probe-visible helpers matching the historical card status keys. |

## Verification

```powershell
powershell -File tools\run_godot_passthrough_overlay_presenter_probe.ps1
```

The probe runs
`godot-android/tests/script_only_passthrough_overlay_presenter_probe.gd` in
no-project mode. It locks env parsing, XR/enabled gating, viewport/layer/UI
construction, alpha blending, camera-relative placement, and the status values.

This extraction is a scene-node refactor around the existing overlay path. It
does not touch VST capture, bbox math, target tracking, calibration, or Android
SDK calls, so it does not require a real-device VST smoke test.
