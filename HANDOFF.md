# HANDOFF

## State (after VSTDebugUI extraction, YAN-100)

- All 190 Python tests pass (`python -m unittest discover -s tests -p "test_*.py"`).
- Schema gate passes on both fixtures.
- Full script-only Godot probe set passes on Godot 4.6.2, including the new
  VSTDebugUI probe.
- **YAN-100 done**: VST debug scene visuals moved out of
  `AndroidMovingCard.gd` into `godot-android/scripts/vst_debug_ui.gd`
  (`VSTDebugUI`). It owns the world bbox frame, raw right-image Sprite3D,
  raw-image bbox overlay quads, and raw debug label. The card now delegates
  texture/overlay/frame visual updates while keeping VSTCapture callbacks,
  bbox state, target updates, public APIs, orientation policy, and status
  snapshots. Docs: `docs/vst_debug_ui.md`. Probe:
  `tools/run_godot_vst_debug_ui_probe.ps1` ->
  `godot-android/tests/script_only_vst_debug_ui_probe.gd`.
- **YAN-99 done**: VSTCapture extraction moved GXRDualVstCapture setup,
  ncnn tracker asset staging, right-frame polling, tracker boxes,
  calibration diagnostics, and bbox-to-head math into
  `godot-android/scripts/vst_capture.gd` (`VSTCapture`). The card now wires
  callbacks for raw-image texture updates, debug bbox overlays, and target
  updates while keeping public APIs (`register_node3d_target`,
  `attach_to_target`, `update_vst_target`) unchanged. Docs:
  `docs/vst_capture.md`. Probe:
  `tools/run_godot_vst_capture_probe.ps1` →
  `godot-android/tests/script_only_vst_capture_probe.gd`.
- **M4 step 1 done** (YAN-80): the duplicated bbox→head math —
  `smartxr/geometry.py` vs `_anchor_from_bbox` /
  `_convert_vst_camera_point_to_head_convention` /
  `_transform_right_vst_point_to_head` /
  `_target_position_from_bbox_anchor` in `AndroidMovingCard.gd` — is locked
  to one checked-in fixture,
  `godot-android/fixtures/bbox_math_test_vectors.json` (schema_version 1:
  projection, head-conversion incl. the GDScript-only <16-element matrix
  fallback, full chain incl. the GDScript-only yaw/pitch/depth/angular
  decomposition and final position). Consumers:
  `tests/test_bbox_math_vectors.py` (Python, 1e-9) and
  `tools/run_godot_bbox_math_probe.ps1` →
  `godot-android/tests/script_only_bbox_math_probe.gd` (GDScript, 1e-4,
  float32; 32 checks). The probe loads the CARD itself, so the runner
  stages `scripts\` into `.tmp\bbox_math_probe\scripts\` (no project file)
  and runs Godot with that cwd — the compile-gate trick — and instantiates
  the card WITHOUT adding it to the tree (no `_ready`: no WS connects, no
  XR init; it is freed explicitly). Vector authoring:
  `tools/generate_bbox_math_test_vectors.py`. NO production code moved —
  this is the de-risking gate for M4-2/M4-3.
- **M3 step 1 done** (YAN-74): status HUD + diagnostics-file subsystem
  extracted into `godot-android/scripts/status_hud.gd` via the
  snapshot-Dictionary seam (ADR-4 in DECISIONS.md).
- **M3 step 2 done** (YAN-75): the TargetRegistry + Node3DTargetAdapter
  inner classes extracted from `AndroidMovingCard.gd` into
  `godot-android/scripts/target_registry.gd` (RefCounted, dependency-free,
  no class_name self-references). The card preloads it as
  `TargetRegistryScript` and keeps the same public API
  (`register_node3d_target` / `unregister_target` / `attach_to_target`).
  TrackableTarget and VSTTargetAdapter stay in the card (target-source
  subsystem, M4).
- **M3 step 3 done** (YAN-76): the two near-duplicate WebSocketPeer
  connect/poll/retry loops (control + proxy_targets) extracted into
  `godot-android/scripts/ws_transport.gd` (RefCounted, dependency-free, no
  class_name self-references). The card holds two instances (`_control_ws`,
  `_proxy_targets_ws`), wires them in `_setup_ws_transports()`, and keeps
  URL/enable resolution, packet handling, and the status snapshot per
  ADR-4. Also fixed the latent Godot-4 `set_write_mode()` subscribe bug
  (see Notes.md, YAN-76 section).
- **M3 step 4 done** (YAN-77): the card-attachment subsystem extracted from
  `AndroidMovingCard.gd` into `godot-android/scripts/card_attachment.gd`
  (RefCounted, dependency-free, no class_name self-references): the
  card_id -> attachment store (was `_card_attachments`), the
  `attach_to_target` / `detach_card` bodies, the per-frame
  `_update_target_attachments` pass, the fallback state machine
  (`hold_last_pose` / `detach` / `fade_out`), and all the offset-rule math
  (`normalize_offset_rule` / `offset_transform` / `world_offset_transform`
  / `local_offset_transform` / `offset_vector` as statics, plus
  `DEFAULT_OFFSET_RULE` and the `TARGET_FALLBACK_*` names). ADR-4 seam:
  the card keeps its public API, anchor-mode switching, orientation, and
  every status-snapshot key (identical values); target lookup is wired
  back into target_registry.gd via `set_resolver(_target_registry.resolve)`,
  the apply counter via `set_on_applied`, and the detach fallback routes
  back through the card's `detach_card` via `set_on_detach_card` so the
  anchor-mode flip stays card-side. Behavior-identical, including the
  "single non-primary attachment still drives the card" selection rule and
  "no attachment processed -> no re-orient" early-out.
- **M3 step 5 done** (YAN-79) — **M3 is complete**: the XR startup path
  (`_try_init_xr`: OpenXR interface lookup/initialize, viewport
  use_xr/transparent_bg, the alpha-blend environment request incl. the
  `set_environment_blend_mode` has_method branch, vsync disable, the
  "XR init:" prints and the exact error strings) and the camera/origin
  construction (`_setup_camera`: XROrigin3D + XRCamera3D when XR is
  active, FallbackCamera with look_at + make_current otherwise) extracted
  from `AndroidMovingCard.gd` into `godot-android/scripts/xr_bootstrap.gd`
  (RefCounted, dependency-free, no class_name self-references). ADR-4
  seam: the card calls `try_init_xr(get_viewport())` /
  `setup_camera(self)` and copies the results back into `_xr_active` /
  `_xr_interface_found` / `_xr_initialize_ok` / `_xr_init_error` /
  `_xr_origin` / `_camera` / `_passthrough_overlay_requested_blend_mode` /
  `_passthrough_overlay_blend_ok`, so every status-snapshot key keeps
  identical values. The interface lookup is injectable
  (`set_interface_provider`, duck-typed interface use) and the fallback
  camera's look_at target routes back through
  `_anchor_position_from_yaw_pitch_depth`
  (`set_fallback_look_at_provider`).
- **Godot runtime verification done on the dev machine** (Godot 4.6.2
  headless): the new XRBootstrap probe passes all 31 checks
  (`tools\run_godot_xr_bootstrap_probe.ps1`, fakes for the interface — the
  not-found, initialize-false, fallback-camera, XR-active origin+camera,
  and all three blend-request branches run headless), the CardAttachment
  probe all 48, the WSTransport probe all 30, the target-registry probe
  all 32, the StatusHud probe all 29, the options probe all 10, and both
  pipeline harnesses pass — `run_godot_script_only_websocket_probe.ps1`
  (`ws_connected=true, packets=1`) and
  `run_godot_proxy_targets_consumer_only.ps1` against a live
  `fake_proxy_targets_publisher.py` (`parsed=1, live=1,
  registered_targets=1, attachments=1`). `AndroidMovingCard.gd` (all eight
  preloads) + `xr_bootstrap.gd` pass the script-only load/can_instantiate
  compile check with clean stderr (staged into
  `.tmp\card_compile_gate\scripts\`).
- **Whole-app PCMR verification path**: headless project mode still boots the
  main scene and never exits, and `godot --check-only` still hangs in this repo
  (GXR extension + OpenXR boot), so keep using script-only/no-project probes for
  automated checks. For human headset inspection, use
  `tools/run_windows_pcmr_overlay_visual_check.ps1`; it holds Godot open until
  the user closes it.

## Unfinished / risks

- Const-from-preload now exists in the card:
  `VST_TARGET_OFFSET_RULE.fallback` references
  `CardAttachmentScript.TARGET_FALLBACK_HOLD_LAST_POSE`. This compiles and
  runs on Godot 4.6.2 (compile gate + probes); if a future Godot version
  complains, inline `"hold_last_pose"` (the debug-marker attach call
  already uses the literal).
- Script-only compile checks for scripts that `preload("res://...")` sibling
  scripts (like the card) must run from a working directory WITHOUT
  `project.godot`: running headless with cwd = `godot-android/` loads the
  project and hangs on the GXR/OpenXR boot. Stage `scripts/` into a temp dir
  (e.g. `.tmp\card_compile_gate\scripts\`) and run the loader probe from
  there so `res://scripts/*.gd` resolves in true no-project mode.
- Probes that read `Node3D.global_transform` must run their checks from the
  first main-loop iteration (`_process`), not `_initialize`: the root Window
  is not yet inside the tree during `_initialize` in script-only mode and
  `get_global_transform` errors with `!is_inside_tree()` (see
  `script_only_target_registry_probe.gd` / `script_only_card_attachment_probe.gd`).
- WebSocketPeer gotchas on Windows (discovered while building the WSTransport
  probe): connecting to a genuinely closed loopback port leaves the peer in
  STATE_CONNECTING for seconds (it does not reach STATE_CLOSED quickly), so
  retry-loop tests need an accept-then-close TCP listener that fails the
  handshake instead; and `connect_to_url("not a url")` returns OK (parsed as
  a host) — only a non-ws/wss scheme fails synchronously.
- `WS_URL` now defaults to `ws://127.0.0.1:8766/control` (flipped from the
  historical dev-machine LAN IP per the owner's decision on YAN-76).
  On-device deployments that relied on the old baked-in LAN address must set
  `SMARTXR_CONTROL_WS_URL` or `user://smartxr_options.json` to reach the
  control server.
- `resolve_bool` returning a Variant from `_config` may emit an UNSAFE_CAST
  style warning in strict Godot editors; harmless, but can be silenced with an
  explicit `bool()` cast if the project enables treat-warnings-as-errors.
- Scripts that script-only probes load must not self-reference their own
  `class_name` (it is unregistered in no-project mode). `smartxr_options.gd`,
  `status_hud.gd`, `target_registry.gd`, `ws_transport.gd`,
  `card_attachment.gd`, `xr_bootstrap.gd`, `target_source.gd`, and
  `vst_capture.gd` follow the rule; keep it for
  future probe-visible scripts. Inner-class references (`Node3DTargetAdapter` inside
  `target_registry.gd`) are script-scoped and safe. The card's untyped
  helpers (`_proxy_targets_card_resolved_position()` etc.) intentionally
  return Vector3-or-null; StatusHud renders null as "n/a".
- M4-2 (VST TargetSource extraction), M4-3 (remaining TargetSource
  sources), and M5 (per-subsystem docs) are complete. The M5 docs follow
  `docs/smartxr_options.md` style: `docs/status_hud.md`,
  `docs/target_registry.md`, `docs/ws_transport.md`,
  `docs/card_attachment.md`, `docs/xr_bootstrap.md`, and
  `docs/target_source.md`.
- PCMR overlay manual visual verification is wrapped in
  `tools/run_windows_pcmr_overlay_visual_check.ps1`. It starts the managed
  fake proxy_targets publisher on port 8767, disables/re-enables the GXR
  extension around the Windows run, sets `PROXY_TARGETS_WS_URL` and
  `SMARTXR_USE_PASSTHROUGH_OVERLAY`, then holds Godot open for headset
  inspection until the user closes it. Docs:
  `docs/pcmr_overlay_visual_check.md`. Use
  `tools/run_windows_pcmr_proxy_targets_live.ps1` for automated pass/fail
  validation; use the overlay visual check runner for human headset inspection.
- GDScript bbox math is now owned by `VSTCapture`; compatibility wrappers in
  `AndroidMovingCard.gd` keep the existing bbox probe/public debug path stable.
  It remains locked to `godot-android/fixtures/bbox_math_test_vectors.json`, so any
  move that changes the numbers fails the probe or the Python suite. The
  full-chain vectors are authored with the card's FOV consts (70/43); the
  probe fails on FOV drift (`chain:*:fov_matches_card`), so changing
  `BBOX_*_FOV_DEG` requires regenerating the fixture
  (`tools/generate_bbox_math_test_vectors.py` — keep its
  CARD_HFOV/VFOV in sync).

## How to continue

M1-M5 are complete for the current encapsulation roadmap: configuration,
Python packaging, Godot subsystem extractions, TargetSource routing, and
per-subsystem docs. Keep the ADR-4 boundary and the no-project-mode rules for
any new probe-visible script. Track the stripped-project live-harness Godot
4.6.2 crash separately if it becomes important; it is outside the completed
script-only/no-project path.

For a final PCMR overlay smoke check before moving to the next feature, run:

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_windows_pcmr_overlay_visual_check.ps1
```
