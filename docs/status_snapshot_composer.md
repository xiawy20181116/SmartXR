# StatusSnapshotComposer

`godot-android/scripts/status_snapshot_composer.gd` owns the stable
diagnostics Dictionary shape assembled once per frame by
`AndroidMovingCard.gd`.

The script is dependency-free and probe-loadable. It does not read scene nodes,
websocket state, XR state, VST state, or overlay state directly. The card
continues to resolve those live values and passes plain values into the
composer.

## Boundary

| API | Caller | Responsibility |
| --- | --- | --- |
| `build_status_snapshot(values)` | Card / probes | Builds the top-level snapshot consumed by `StatusHud`. |
| `build_xr_status_snapshot(...)` | Card / probes | Builds the `xr` fragment. |
| `build_vst_status_snapshot(capture_snapshot, target_state)` | Card / probes | Copies the VST capture snapshot and adds `target_state`. |
| `build_proxy_targets_status_snapshot(values)` | Card / probes | Builds the `proxy_targets` fragment. |
| `build_passthrough_overlay_status_snapshot(values)` | Card / probes | Builds the `passthrough_overlay` fragment. |

## Verification

```powershell
powershell -File tools\run_godot_status_snapshot_composer_probe.ps1
```

The probe runs
`godot-android/tests/script_only_status_snapshot_composer_probe.gd` in
no-project mode. It locks the ordered top-level keys, each extracted fragment,
and the VST copy-with-target-state behavior.

This extraction is a pure dictionary-composition refactor. It does not touch
VST capture, bbox math, target tracking, passthrough overlay rendering, or
Android SDK calls, so it does not require a real-device VST smoke test.
