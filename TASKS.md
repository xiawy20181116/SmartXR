# TASKS — encapsulation plan (YAN-73)

Roadmap agreed in Multica issue YAN-73: adopt xrblocks-style runtime
encapsulation on the Godot side and pi-style layered packaging on the Python
side.

## Completed

- [x] **M1 — Configuration**: `SmartXROptions` (`godot-android/scripts/smartxr_options.gd`)
  with env → `user://smartxr_options.json` → const-default resolution.
  Control WS URL (previously a hardcoded LAN IP at the call site),
  proxy_targets WS URL, and the live-consumer enable flag now route through it.
  Docs: `docs/smartxr_options.md`. Tests: `tests/test_godot_smartxr_options.py`.
- [x] **M2 — Python packaging**: `smartxr/` package
  (schema / geometry / transport / frames / publisher / cli) with strict
  one-way deps; `tools/*.py` reduced to compatibility wrappers; WebSocket
  framing deduplicated out of `ws_control.py`, `fake_*` and `vst_*`
  publishers; antman live publisher no longer imports private functions from
  sibling tools. `pyproject.toml` added.
- [x] **M3 step 1 — StatusHud** (YAN-74): status label rendering and the
  `user://` status-file writers (`proxy_targets_live_status.json`,
  `passthrough_overlay_status.json`) extracted from `AndroidMovingCard.gd`
  into `godot-android/scripts/status_hud.gd`. Seam: the card assembles a
  per-frame snapshot Dictionary (`_build_status_snapshot()`), StatusHud only
  formats and writes (ADR-4). Runtime probe:
  `tools/run_godot_status_hud_probe.ps1` (29 checks). Tests:
  `tests/test_godot_status_hud.py`.
- [x] **M3 step 2 — TargetRegistry** (YAN-75): the TargetRegistry and
  Node3DTargetAdapter inner classes extracted from `AndroidMovingCard.gd`
  into `godot-android/scripts/target_registry.gd` (RefCounted,
  dependency-free; the card passes itself as the adapters' lookup root).
  Card public API unchanged (`register_node3d_target`, `unregister_target`,
  `attach_to_target`). TrackableTarget / VSTTargetAdapter stay in the card
  (target-source subsystem, M4). Runtime probe:
  `tools/run_godot_target_registry_probe.ps1` (32 checks). Tests:
  `tests/test_godot_target_registry.py`.
- [x] **M3 step 3 — WSTransport** (YAN-76): the two near-duplicate
  WebSocketPeer connect/poll/retry loops (control + proxy_targets) extracted
  from `AndroidMovingCard.gd` into `godot-android/scripts/ws_transport.gd`
  (RefCounted, dependency-free; the card instantiates two and keeps URL /
  enable-gate resolution, packet handling, error formatting, and the status
  snapshot per ADR-4). Also fixed a latent bug: the old subscribe path
  called the nonexistent `WebSocketPeer.set_write_mode()`, so the subscribe
  payload was never actually sent; WSTransport uses `send_text()`. Runtime
  probe: `tools/run_godot_ws_transport_probe.ps1` (30 checks, live fake
  publisher + accept-then-close retry listener). Tests:
  `tests/test_godot_ws_transport.py`.
- [x] **M3 step 4 — CardAttachment** (YAN-77): the card_id -> attachment
  store (`_card_attachments`), the `attach_to_target` / `detach_card`
  bodies, the `_update_target_attachments` per-frame pass, the fallback
  state machine (`hold_last_pose` / `detach` / `fade_out`), and the
  offset-rule math (modes right_top / right / top / front / custom-xyz,
  offset_space world / target, `TARGET_DEFAULT_OFFSET_RULE` defaults)
  extracted from `AndroidMovingCard.gd` into
  `godot-android/scripts/card_attachment.gd` (RefCounted, dependency-free;
  target lookup wired back into target_registry.gd via a resolver Callable,
  apply counter and detach-fallback mode flip stay card-side per ADR-4).
  Card public API and every status-snapshot key unchanged. Runtime probe:
  `tools/run_godot_card_attachment_probe.ps1` (48 checks). Tests:
  `tests/test_godot_card_attachment.py`.
- [x] **M3 step 5 — XRBootstrap** (YAN-79): the XR startup path
  (`_try_init_xr`: OpenXR interface lookup/initialize, viewport
  use_xr/transparent_bg, the alpha-blend environment request incl. the
  `set_environment_blend_mode` has_method branch, vsync disable, the
  "XR init:" prints) and the camera/origin construction (`_setup_camera`:
  XROrigin3D + XRCamera3D when XR is active, FallbackCamera with look_at
  otherwise) extracted from `AndroidMovingCard.gd` into
  `godot-android/scripts/xr_bootstrap.gd` (RefCounted, dependency-free;
  the interface lookup is injectable via a provider Callable with
  duck-typed interface checks, and the fallback camera's look_at target
  routes back into the card's 3DoF anchor math per ADR-4). The card copies
  the bootstrap results into `_xr_*` / `_camera` / the passthrough_overlay
  blend fields, so every status-snapshot key keeps identical values. M3 is
  complete. Runtime probe: `tools/run_godot_xr_bootstrap_probe.ps1`
  (31 checks). Tests: `tests/test_godot_xr_bootstrap.py`.

- [x] **M4 step 1 — shared bbox math test vectors** (YAN-80): the duplicated
  bbox→head math (`smartxr/geometry.py` vs the four card methods
  `_anchor_from_bbox` / `_convert_vst_camera_point_to_head_convention` /
  `_transform_right_vst_point_to_head` / `_target_position_from_bbox_anchor`)
  locked to one checked-in fixture,
  `godot-android/fixtures/bbox_math_test_vectors.json` (projection,
  default-flip + row-major `right_eye_to_head` matrix conversion incl. the
  GDScript-only short-matrix fallback, and the full
  bbox→yaw/pitch/depth/angular→position chain). Python consumer:
  `tests/test_bbox_math_vectors.py` (tolerance 1e-9). GDScript consumer:
  `tools/run_godot_bbox_math_probe.ps1` +
  `godot-android/tests/script_only_bbox_math_probe.gd` (tolerance 1e-4,
  float32; stages `scripts\` into a temp no-project cwd because the card
  preloads nine siblings). Generator:
  `tools/generate_bbox_math_test_vectors.py`. Docs: "Shared math test
  vectors" section in `docs/proxy_targets_payload_contract.md`. No
  production code moved (de-risking slice before M4-2/M4-3).
- [x] **M4 step 2 — VST TargetSource** (YAN-84): TrackableTarget and
  VSTTargetAdapter extracted from `AndroidMovingCard.gd` into
  `godot-android/scripts/target_source.gd` behind a duck-typed
  `VSTTargetSource` boundary. The card keeps proxy node registration,
  attachment, bbox/head math, status snapshot assembly, and fallback side
  effects; target updates/lost state route back through Callables. Probe:
  `tools/run_godot_target_source_probe.ps1` (12 checks). Tests:
  `tests/test_godot_target_source.py`.
- [x] **M4 step 3 — remaining TargetSource sources** (YAN-86): remote
  proxy_targets WS payloads and fixture replay now route through
  `TargetSourceScript.ProxyTargetsTargetSource`, a dependency-free
  duck-typed boundary in `godot-android/scripts/target_source.gd`. The card
  still owns registry wiring, card attachment, live counters, diagnostics,
  status snapshot assembly, and fallback side effects; the source only parses
  JSON, delegates to the injected proxy_targets card adapter, and reports
  coarse errors. Probe: `tools/run_godot_target_source_probe.ps1` (15
  checks). Tests: `tests/test_godot_target_source.py`.
- [x] **M5 — Per-subsystem docs**: added subsystem docs following
  `docs/smartxr_options.md` style for StatusHud, TargetRegistry,
  WSTransport, CardAttachment, XRBootstrap, and TargetSource/proxy_targets.
  Docs: `docs/status_hud.md`, `docs/target_registry.md`,
  `docs/ws_transport.md`, `docs/card_attachment.md`,
  `docs/xr_bootstrap.md`, `docs/target_source.md`.
- [x] **M6 — VSTCapture + bbox math** (YAN-99): GXRDualVstCapture setup,
  ncnn tracker asset staging, right-frame polling, tracker boxes,
  calibration diagnostics, and bbox-to-head math extracted from
  `AndroidMovingCard.gd` into dependency-free
  `godot-android/scripts/vst_capture.gd` (`VSTCapture`). The card keeps
  public API, target-source updates, scene/debug UI side effects, and status
  snapshot composition. Runtime probe:
  `tools/run_godot_vst_capture_probe.ps1`; fixture math probe remains
  `tools/run_godot_bbox_math_probe.ps1`. Docs: `docs/vst_capture.md`.
- [x] **M7 — VSTDebugUI scene/debug visuals** (YAN-100): VST world bbox
  frame construction/update, raw right-image Sprite3D texture updates, raw
  bbox overlay quads, and the raw debug label extracted from
  `AndroidMovingCard.gd` into dependency-free
  `godot-android/scripts/vst_debug_ui.gd` (`VSTDebugUI`). The card keeps
  VSTCapture callbacks, bbox state, orientation policy, target updates,
  public API, and status snapshots. Runtime probe:
  `tools/run_godot_vst_debug_ui_probe.ps1`. Docs: `docs/vst_debug_ui.md`.
- [x] **YAN-86 follow-up — PCMR overlay visual check runner**: added
  `tools/run_windows_pcmr_overlay_visual_check.ps1`, a hold-open manual
  headset runner that manages the fake proxy_targets publisher, Windows GXR
  disable/restore, `PROXY_TARGETS_WS_URL`, and
  `SMARTXR_USE_PASSTHROUGH_OVERLAY`. Docs:
  `docs/pcmr_overlay_visual_check.md`. Tests:
  `tests/test_run_windows_pcmr.py`.

## Next

- [ ] Track the stripped-project live-harness Godot 4.6.2 crash separately
  if it becomes important; it is outside the completed M1-M5 encapsulation
  docs path.

## Verification

```powershell
# Full suite (151 tests)
python -m unittest (Get-ChildItem tests\test_*.py | ForEach-Object { "tests/$($_.Name)" })

# Schema gate
python tools\validate_proxy_targets_payload_schema.py --input godot-android\fixtures\proxy_targets_sample.json --input godot-android\fixtures\vst_proxy_targets_sample.json

# Godot runtime probes (headless, no-project mode)
powershell -File tools\run_godot_smartxr_options_probe.ps1
powershell -File tools\run_godot_status_hud_probe.ps1
powershell -File tools\run_godot_target_registry_probe.ps1
powershell -File tools\run_godot_ws_transport_probe.ps1
powershell -File tools\run_godot_card_attachment_probe.ps1
powershell -File tools\run_godot_xr_bootstrap_probe.ps1
powershell -File tools\run_godot_target_source_probe.ps1
powershell -File tools\run_godot_vst_capture_probe.ps1
powershell -File tools\run_godot_vst_debug_ui_probe.ps1
powershell -File tools\run_godot_bbox_math_probe.ps1
powershell -File tools\run_godot_script_only_websocket_probe.ps1
# consumer-only needs a publisher on :8766 first (fake_proxy_targets_publisher.py)
powershell -File tools\run_godot_proxy_targets_consumer_only.ps1

# Manual PCMR headset visual check; keeps Godot open until the user closes it.
powershell -File tools\run_windows_pcmr_overlay_visual_check.ps1
```
