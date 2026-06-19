# GDScript probes CI

The `gdscript-probes` job in `.github/workflows/ci.yml` runs the Godot
script-only probes on a self-hosted runner. It is intentionally gated behind
`workflow_dispatch` so normal `push` and `pull_request` runs keep using the
GitHub-hosted Python job and do not block when no local Godot runner is online.

## Runner requirements

- Register a GitHub Actions self-hosted runner for this repository on the
  Windows machine that has Godot 4.6.2 installed.
- Ensure PowerShell is available on the runner.
- Ensure the Godot executable exists at:

```powershell
E:\xia\Godot_v4.6.2-stable_win64.exe\Godot_v4.6.2-stable_win64.exe
```

The workflow sets `GODOT_BIN` to that path and passes it to each probe wrapper
with `-GodotExe`. If the runner uses a different Godot 4.6.2 location, update
the workflow `GODOT_BIN` value before dispatching the job.

## What the job runs

The job checks out the repository, verifies `GODOT_BIN`, then runs:

```powershell
powershell -ExecutionPolicy Bypass -File tools/run_godot_smartxr_options_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_status_hud_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_target_registry_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_ws_transport_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_card_attachment_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_command_dispatcher_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_proxy_targets_status_fragment_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_validation_scene_builder_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_xr_bootstrap_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_status_snapshot_composer_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_passthrough_overlay_presenter_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_card_view_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_card_lifecycle_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_card_state_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_card_receiver_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_target_source_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_vst_capture_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_vst_debug_ui_probe.ps1 -GodotExe $env:GODOT_BIN
powershell -ExecutionPolicy Bypass -File tools/run_godot_bbox_math_probe.ps1 -GodotExe $env:GODOT_BIN
```

Each wrapper owns its no-project staging behavior. The CI job must not launch
Godot with `--path godot-android`, because full project headless startup can
hang on the GXR/OpenXR path.

## Expected failure mode

Any non-zero probe exit fails the job. The VSTCapture probe guards the
dependency-free VST capture/bbox math subsystem. The VSTDebugUI probe guards
the dependency-free scene/debug visual subsystem for the VST world frame and
raw-image overlay. The bbox math probe is the shared guard for
`godot-android/fixtures/bbox_math_test_vectors.json`; changing an expected
value in that fixture should make the probe fail, and restoring the fixture
should make the job pass again.

The StatusSnapshotComposer probe guards the dependency-free status Dictionary
layout used by `AndroidMovingCard.gd` and `StatusHud`.

The PassthroughOverlayPresenter probe guards the dependency-free overlay
viewport/layer/UI construction and camera-relative transform update.

The CardView probe guards the dependency-free main card viewport, UI, card
panel mesh/material, and XR render probe construction.

The CardState probe guards the dependency-free tracked-card data snapshot used
by command dispatch, bbox anchoring, manual motion, and target attach/detach
mode transitions.

The CardReceiver probe guards the dependency-free proxy_targets receiver glue:
transport setup, subscribe payload, live-payload status updates, parsed-message
head diagnostics, and scene-supplied status values.

The CardLifecycle probe guards the dependency-free C3 card-lifecycle state
machine in `godot-android/scripts/card_lifecycle.gd`: the canonical
attach/appear -> expand -> contract -> expand -> detach/disappear round-trip,
illegal-transition rejection (e.g. `update` before `attach`, `appear -> contract`),
schema command/card_state coupling, and the default per-state animation
durations. It is the runtime mirror of `tests/test_card_lifecycle_payload_schema.py`
(the Python `CardLifecycleConsumer`), keeping both sides of the C3 seam in
lock-step.
