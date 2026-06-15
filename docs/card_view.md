# CardView

`godot-android/scripts/card_view.gd` owns the main SmartXR card viewport,
card panel mesh, card UI, material binding, and the small XR render probe.

The script is dependency-free and probe-loadable. It does not own motion,
orientation, target attachment, XR lifecycle, VST state, status snapshots, or
status-file writes. `AndroidMovingCard.gd` keeps those orchestration decisions
and only retains the built node handles.

## Boundary

| API | Caller | Responsibility |
| --- | --- | --- |
| `_init(options)` | Card / probes | Receives the historical viewport size, card size, and XR probe size values. |
| `build(parent, anchor_name)` | Card / probes | Creates `CardViewport`, `MovingCardUI`, `CardAnchor`, `CardPanel`, the `QuadMesh`, and the unshaded viewport material. |
| `build_xr_render_probe()` | Card / probes | Creates the red `XRRenderProbe` mesh under the card anchor. |
| `viewport()` / `anchor()` / `card_mesh()` / `xr_probe_mesh()` | Card / probes | Returns the handles that `AndroidMovingCard.gd` keeps for status, orientation, and validation. |

## Verification

```powershell
powershell -File tools\run_godot_card_view_probe.ps1
```

The probe runs `godot-android/tests/script_only_card_view_probe.gd` in
no-project mode. It locks the viewport configuration, UI labels and offsets,
panel mesh size, viewport texture material binding, XR probe size, color, and
position.

This extraction is a scene-node construction refactor. It does not touch VST
capture, bbox math, target tracking, calibration, Android SDK calls, or live
proxy_targets IO, so it does not require PCMR, a headset, or a real-device VST
smoke test.
