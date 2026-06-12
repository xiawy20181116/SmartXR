# Notes — change log

## YAN-76 follow-up — WS_URL default flipped to loopback

- `godot-android/scripts/AndroidMovingCard.gd` — `WS_URL` default changed
  from the historical dev-machine LAN IP `ws://10.1.98.195:8766/control` to
  `ws://127.0.0.1:8766/control`, per the owner's decision on the YAN-76
  thread. Resolution order is unchanged (env `SMARTXR_CONTROL_WS_URL` ->
  `user://smartxr_options.json` -> const default, ADR-2); only the
  last-resort default moved. Deployments that relied on the baked-in LAN
  address must now set the env var or config file.
- `HANDOFF.md` risk bullet updated, ADR-2 in `DECISIONS.md` annotated.
- Verification (re-run after rebasing onto the merged M3-4, PR #13): full
  Python suite (131 tests) OK; smartxr options probe 10/10 PASS (resolution
  order unchanged); card compile gate clean; no test pinned the old literal.
  Re-verified after merging the M3-5 main (PR #15): 134 tests OK, options
  probe 10/10, card compile gate clean.

## M3 step 5 — XRBootstrap extraction (YAN-79)

### Files added

- `godot-android/scripts/xr_bootstrap.gd` — XRBootstrap subsystem
  (RefCounted, dependency-free, no class_name self-references): the XR
  startup path moved verbatim from the card's `_try_init_xr` (OpenXR
  interface lookup, initialize, viewport use_xr / transparent_bg, the
  alpha-blend environment request including the
  `set_environment_blend_mode` has_method branch and the
  `environment_blend_mode` property else-branch, vsync disable, and the
  byte-for-byte "XR init:" prints and error strings "OpenXR interface not
  found" / "OpenXR initialize returned false"), plus the camera/origin
  construction from `_setup_camera` (XROrigin3D "XROrigin" + XRCamera3D
  "XRCamera" far=50 when XR is active; "FallbackCamera" with
  look_at + make_current otherwise). Injection per the M3-3/M3-4 Callable
  pattern (ADR-4: state resolution stays in the card, never a back-pointer
  preload): `set_interface_provider` replaces the default
  `XRServer.find_interface("OpenXR")` lookup and the interface is used
  duck-typed only (initialize / has_method / call /
  environment_blend_mode), so probes can exercise every path headless with
  fakes; `set_fallback_look_at_provider` routes the fallback camera's
  look_at target back into the card's 3DoF anchor math. Results are
  exposed through read-only getters (`interface_found` / `initialize_ok` /
  `xr_active` / `init_error` / `requested_blend_mode` / `blend_request_ok`
  / `xr_origin` / `camera`) with defaults mirroring the card's pre-init
  state ("not attempted", "alpha_blend", false).
- `godot-android/tests/script_only_xr_bootstrap_probe.gd` — script-only
  runtime probe (31 checks: pre-init defaults; the interface-not-found
  fallback with the exact error string and untouched viewport; the
  initialize-false fallback with the exact error string, no blend request,
  untouched viewport; fallback camera construction — name/far/position
  zero/no origin/make_current/look_at toward an injected target and the
  one-meter-forward default; the XR-active path with a fake interface —
  flags, empty init_error, viewport use_xr/transparent_bg flips,
  blend-mode request bookkeeping including the recorded
  XR_ENV_BLEND_MODE_ALPHA_BLEND argument, XROrigin3D + XRCamera3D
  construction/parenting; the has_method branch returning false; and the
  property else-branch). Uses probe-local FakeXRInterface /
  FakePropertyXRInterface duck-typed fakes.
- `tools/run_godot_xr_bootstrap_probe.ps1` — headless no-project runner,
  following run_godot_card_attachment_probe.ps1 (env-injected script path +
  status JSON: SMARTXR_XR_BOOTSTRAP_SCRIPT /
  SMARTXR_XR_BOOTSTRAP_PROBE_STATUS_PATH).
- `tests/test_godot_xr_bootstrap.py` — 3 static tests pinning the
  subsystem contract, the card-side delegation/state copies, and the
  probe/runner pair.

### Files modified

- `godot-android/scripts/AndroidMovingCard.gd` — `_try_init_xr` and
  `_setup_camera` became thin delegating wrappers: the card calls
  `_xr_bootstrap.try_init_xr(get_viewport())` /
  `_xr_bootstrap.setup_camera(self)` and copies the results into its own
  state (`_xr_interface_found`, `_xr_initialize_ok`, `_xr_active`,
  `_xr_init_error`, `_passthrough_overlay_requested_blend_mode`,
  `_passthrough_overlay_blend_ok`, `_xr_origin`, `_camera`), so every
  status-snapshot key (`xr.*`, the passthrough_overlay blend fields,
  `camera_position` / `camera_rotation_degrees` / `xr_origin_position`)
  keeps identical values (ADR-4). Added
  `const XRBootstrapScript := preload(...)`; `_xr_bootstrap` is
  `= XRBootstrapScript.new()` (untyped `=`, same pattern as the other
  subsystems); `_setup_xr_bootstrap()` (after `_setup_card_attachment()`
  in `_ready`, before `_try_init_xr()` — the init order is unchanged)
  wires the fallback look_at provider to
  `_anchor_position_from_yaw_pitch_depth`. The interface lookup keeps the
  subsystem's default OpenXR lookup (the card never touches XRServer now).
- `tests/test_godot_android_mesh_card.py` — the transparent-composition
  pins in
  `test_xr_visibility_diagnostic_uses_alpha_blend_composition_for_pcmr_seethrough`
  (`transparent_bg = true`, `XR_ENV_BLEND_MODE_ALPHA_BLEND`,
  `blend=alpha`) repointed at `xr_bootstrap.gd` (per ADR-3); a delegation
  pin (`_xr_bootstrap.try_init_xr(get_viewport())`) was added on the card.
  `test_moving_card_reports_xr_pose_for_tracking_diagnosis` and the
  test_vst_ncnn_port.py XR pins needed no changes — the `_xr_*` state vars
  and the snapshot assembly stay on the card.
- `tests/validate_project.ps1` — registers `tests/test_godot_xr_bootstrap.py`.
- `TASKS.md` / `HANDOFF.md` — bookkeeping.

### Verification run

- `python -m unittest tests/test_*.py` → 134 tests, OK.
- Schema gate on both fixtures → ok.
- `tools\run_godot_xr_bootstrap_probe.ps1` → PASS (31/31 checks, clean
  stderr).
- `tools\run_godot_card_attachment_probe.ps1` → PASS (48/48 checks).
- `tools\run_godot_ws_transport_probe.ps1` → PASS (30/30 checks).
- `tools\run_godot_target_registry_probe.ps1` → PASS (32/32 checks).
- `tools\run_godot_status_hud_probe.ps1` → PASS (29/29 checks).
- `tools\run_godot_smartxr_options_probe.ps1` → PASS (10/10 checks).
- `tools\run_godot_script_only_websocket_probe.ps1` → ws_connected=true,
  packets=1.
- `tools\run_godot_proxy_targets_consumer_only.ps1` against a live
  `fake_proxy_targets_publisher.py` on :8766 → exit 0, parsed=1, live=1,
  registered_targets=1, attachments=1.
- Compile gate: `AndroidMovingCard.gd` (with all eight preloads) and
  `xr_bootstrap.gd` load + `can_instantiate()` in script-only mode
  (Godot 4.6.2 headless, staged into `.tmp\card_compile_gate\scripts\`,
  clean stderr).

### Next slice recommendation

- **M4: TargetSource strategy interface** — M3 is complete; the card is
  now scene building, command handling, bbox math, and the VST target
  source. Unify on-device ncnn (TrackableTarget / VSTTargetAdapter, still
  card-inner classes), the remote proxy_targets WS path, and fixture
  replay behind one source interface, and promote
  `docs/proxy_targets_payload_contract.md` into shared test vectors used
  by both `smartxr/geometry.py` and the GDScript bbox math.

## M3 step 4 — CardAttachment extraction (YAN-77)

### Files added

- `godot-android/scripts/card_attachment.gd` — CardAttachment subsystem
  (RefCounted, dependency-free, no class_name self-references): the
  card_id -> attachment store (was the card's `_card_attachments`), the
  attach/detach lifecycle (`attach` seeds `last_transform` from the
  target's current pose, exactly like the old `attach_to_target` body),
  the per-frame `update_attachments(card_anchor, primary_card_id)` pass
  (primary selection incl. the "single non-primary attachment still drives
  the card" rule, apply-to-anchor + visible=true, last_transform refresh),
  the fallback state machine `apply_fallback` (`hold_last_pose` /
  `detach` / `fade_out`), read-only accessors for the status snapshot
  (`size` / `is_empty` / `has_attachment` / `get_attachment` /
  `attached_target_id` / `last_resolved_position`, the latter
  Vector3-or-null for StatusHud's "n/a"), and the offset-rule math as
  statics (`normalize_offset_rule`, `offset_transform`,
  `world_offset_transform`, `local_offset_transform`, `offset_vector`;
  modes right_top / top_right / right / top / front / custom-xyz,
  offset_space world / target, `DEFAULT_OFFSET_RULE` +
  `TARGET_FALLBACK_*` consts moved here from the card). Wiring is three
  Callables (ADR-4: state resolution stays in the card):
  `set_resolver` (the card passes `_target_registry.resolve`, so target
  lookup stays in target_registry.gd), `set_on_applied` (the card keeps
  its `_proxy_targets_card_apply_count`), and `set_on_detach_card` (the
  detach fallback routes back through the card's `detach_card`, keeping
  the anchor-mode flip card-side; unwired, the store detaches locally for
  probe/standalone use).
- `godot-android/tests/script_only_card_attachment_probe.gd` — script-only
  runtime probe (48 checks: normalize defaults / merge / string form /
  const non-mutation, every offset_vector mode, world-vs-target
  offset_space against a rotated target transform, attach/detach lifecycle
  incl. resolver rejection and record shape, default rule when omitted,
  per-frame apply + on_applied counter, primary-selection rules, and each
  fallback mode against an unavailable and a resolver-missing target,
  detach both locally and via the callable, plus the direct
  `apply_fallback` VST-path call). Uses a probe-local FakeTargetAdapter
  (is_available/get_global_transform) so the subsystem contract is tested
  without target_registry.gd.
- `tools/run_godot_card_attachment_probe.ps1` — headless no-project runner,
  following run_godot_target_registry_probe.ps1 (env-injected script path +
  status JSON).
- `tests/test_godot_card_attachment.py` — 3 static tests pinning the
  subsystem contract, the card-side delegation/wiring, and the
  probe/runner pair.

### Files modified

- `godot-android/scripts/AndroidMovingCard.gd` — removed the
  `_card_attachments` store, the `attach_to_target` /
  `_update_target_attachments` / `_apply_target_fallback` bodies, the
  offset math (`_normalize_target_offset_rule`, `_target_offset_transform`,
  `_target_world_offset_transform`, `_target_local_offset_transform`,
  `_target_offset_vector`), and the `TARGET_FALLBACK_*` /
  `TARGET_DEFAULT_OFFSET_RULE` consts (~115 lines). Added
  `const CardAttachmentScript := preload(...)`; `_card_attachment` is
  `= CardAttachmentScript.new()` (untyped `=`, same pattern as the other
  subsystems); `_setup_card_attachment()` (first thing in `_ready`) wires
  resolver / on_applied / on_detach_card. `attach_to_target`,
  `detach_card`, and `_update_target_attachments` stay as thin public/
  per-frame wrappers (mode flip, `_last_command`, orientation +
  `_update_vst_bbox_frame` only when an attachment was actually
  processed — same early-out as before). `_apply_vst_target_fallback`
  reads the record via `get_attachment` and calls `apply_fallback`
  directly, matching the old direct `_apply_target_fallback` call.
  `VST_TARGET_OFFSET_RULE.fallback` now references
  `CardAttachmentScript.TARGET_FALLBACK_HOLD_LAST_POSE` (const-from-
  preload; verified by the compile gate). Snapshot key values unchanged
  (`attachments` = store size, `card_target_id`, `card_resolved_position`,
  `card_apply_count`, `anchor_mode`).
- `tests/test_godot_android_mesh_card.py` — store/offset-math pins in
  `test_card_can_attach_to_registered_node3d_targets` and
  `test_world_target_offset_ignores_target_rotation_for_card_position`
  repointed at `card_attachment.gd` (per ADR-3); public-API, anchor-mode,
  and snapshot pins stay on the card.
- `tests/test_godot_target_registry.py` — the card-side
  `_target_registry.resolve(target_id)` pin became the resolver wiring
  (`_card_attachment.set_resolver(_target_registry.resolve)`).
- `tests/validate_project.ps1` — registers `tests/test_godot_card_attachment.py`.
- `TASKS.md` / `HANDOFF.md` — bookkeeping.

### Verification run

- `python -m unittest tests/test_*.py` → 131 tests, OK.
- Schema gate on both fixtures → ok.
- `tools\run_godot_card_attachment_probe.ps1` → PASS (48/48 checks, clean
  stderr).
- `tools\run_godot_ws_transport_probe.ps1` → PASS (30/30 checks).
- `tools\run_godot_target_registry_probe.ps1` → PASS (32/32 checks).
- `tools\run_godot_status_hud_probe.ps1` → PASS (29/29 checks).
- `tools\run_godot_smartxr_options_probe.ps1` → PASS (10/10 checks).
- `tools\run_godot_script_only_websocket_probe.ps1` → ws_connected=true,
  packets=1.
- `tools\run_godot_proxy_targets_consumer_only.ps1` against a live
  `fake_proxy_targets_publisher.py` on :8766 → exit 0, parsed=1, live=1,
  registered_targets=1, attachments=1.
- Compile gate: `AndroidMovingCard.gd` (with all seven preloads) and
  `card_attachment.gd` load + `can_instantiate()` in script-only mode
  (Godot 4.6.2 headless, staged into `.tmp\card_compile_gate\scripts\`,
  clean stderr).

### Next slice recommendation

- **M3-5: XRBootstrap** — `_try_init_xr` + the camera/origin setup
  (`_setup_camera`) and the alpha-blend request that feeds the
  passthrough_overlay snapshot. Same ADR-4 seam; after that the card is
  down to scene building, command handling, bbox math (M4 shares vectors
  with `smartxr/geometry.py`), and the VST target source (M4).

## M3 step 3 — WSTransport extraction (YAN-76)

### Files added

- `godot-android/scripts/ws_transport.gd` — reusable WSTransport
  (RefCounted, dependency-free, no class_name self-references): owns one
  WebSocketPeer, `connect_to(url)`, per-frame `poll(delta)`, the 2.0 s
  retry-on-close loop (`RETRY_ON_CLOSE_SECONDS`), an optional
  subscribe-once-on-open text payload, a per-packet Callable back into the
  card, an optional connect-error Callable, and an optional url-provider
  Callable so every retry re-resolves the URL through the card (ADR-4 —
  identical to the old loops, which called
  `_control_ws_url()`/`_proxy_targets_ws_url()` on each reconnect).
  Read-only getters (`ws_connected()`, `ws_subscribed()`, `packets_seen()`,
  `last_packet_bytes()`, `retry_seconds()`, `current_url()`) feed the card's
  status snapshot; named `ws_*` to avoid shadowing `Object.is_connected()`.
- `godot-android/tests/script_only_ws_transport_probe.gd` — script-only
  runtime probe (30 checks: default state flags, invalid-URL connect error +
  callback, dropped-connection retry accumulation and the url-provider-driven
  reconnect, subscribe-once semantics offline and live, live packet delivery
  via the Callable with packets/bytes counters). Multi-frame `_process`
  state machine; quit() only from `_process` (no-project-mode rule).
- `tools/run_godot_ws_transport_probe.ps1` — headless no-project runner:
  starts `fake_proxy_targets_publisher.py` (port 8773) for the live path and
  an accept-then-close TCP listener (port 8799) for the retry path. Gotcha
  discovered here: a genuinely CLOSED port does NOT exercise the retry loop
  on Windows loopback — WebSocketPeer sits in STATE_CONNECTING for seconds
  instead of reaching STATE_CLOSED; the handshake-failing listener closes in
  one frame. Also: Godot 4.6 accepts `"not a url"` in `connect_to_url`
  (treated as a host) — only a bad scheme fails synchronously.
- `tests/test_godot_ws_transport.py` — 3 static tests pinning the transport
  contract, the card-side delegation/wiring, and the probe/runner pair.

### Bug fixed (the one deliberate behavior change)

The old card subscribe path called `WebSocketPeer.set_write_mode()`, which
does not exist in Godot 4: the call errored at runtime on every open-state
poll, so the subscribe payload was NEVER actually sent, `ws_subscribed`
never flipped true in the status snapshot, and the script error spammed the
log each frame while the proxy_targets WS was open (the fake publisher
broadcasts without requiring a subscribe, which hid it). WSTransport uses
`send_text(payload)` (the Godot 4 TEXT-frame API), so the documented
subscribe-once-on-open behavior now actually happens; everything else is
byte-for-byte behavior-identical (wire format, subscribe payload string,
2.0 s retry interval, reconnect-time URL re-resolution, status snapshot
keys/values).

### Files modified

- `godot-android/scripts/AndroidMovingCard.gd` — removed both WebSocketPeer
  loops (`_ws*` and `_proxy_targets_ws_*` connection vars,
  `_send_proxy_targets_subscribe`, the poll bodies). Added
  `const WSTransportScript := preload(...)`; `_control_ws` /
  `_proxy_targets_ws` are `= WSTransportScript.new()` (untyped `=`, same
  pattern as `_options`); `_setup_ws_transports()` (called from `_ready`
  before connecting) wires packet callbacks (`_handle_packet` /
  `_on_proxy_targets_ws_packet`), the subscribe payload, error formatters
  (`_on_control_ws_connect_error` / `_on_proxy_targets_ws_connect_error`,
  preserving the exact `_last_command` strings), and the url providers.
  URL/enable resolution, packet handling, and the status snapshot stay in
  the card; snapshot now reads `ws_connected/ws_subscribed/packets/
  packet_bytes` from the transports (same keys, same values).
- `tests/test_godot_android_mesh_card.py` — peer/retry/subscribe pins in
  `test_proxy_targets_live_websocket_consumer_is_wired` repointed at
  `ws_transport.gd` (per ADR-3); URL-resolution/packet-handling/snapshot
  pins stay on the card.
- `tests/test_godot_smartxr_options.py` — `connect_to_url(_control_ws_url())`
  pin updated to the card's `connect_to(_control_ws_url())` delegation.
- `tests/validate_project.ps1` — registers `tests/test_godot_ws_transport.py`.
- `TASKS.md` / `HANDOFF.md` — bookkeeping.

### Verification run

- `python -m unittest tests/test_*.py` → 128 tests, OK.
- Schema gate on both fixtures → ok.
- `tools\run_godot_ws_transport_probe.ps1` → PASS (30/30 checks).
- `tools\run_godot_target_registry_probe.ps1` → PASS (32/32 checks).
- `tools\run_godot_status_hud_probe.ps1` → PASS (29/29 checks).
- `tools\run_godot_smartxr_options_probe.ps1` → PASS (10/10 checks).
- `tools\run_godot_script_only_websocket_probe.ps1` → ws_connected=true,
  packets=1.
- `tools\run_godot_proxy_targets_consumer_only.ps1` against a live
  `fake_proxy_targets_publisher.py` on :8766 → exit 0, parsed=1, live=1,
  registered_targets=1.
- Compile gate: `AndroidMovingCard.gd` (with all six preloads) and
  `ws_transport.gd` load + `can_instantiate()` in script-only mode (Godot
  4.6.2 headless, staged into `.tmp\card_compile_gate\scripts\`, clean
  stderr).

## M3 step 2 — TargetRegistry extraction (YAN-75)

### Files added

- `godot-android/scripts/target_registry.gd` — the TargetRegistry and
  Node3DTargetAdapter classes, moved verbatim out of `AndroidMovingCard.gd`
  (Node3DTargetAdapter is now an inner class of the registry script).
  RefCounted, dependency-free (no preloads, no env reads, no tree walks of
  its own — the card passes the lookup root into each adapter), and no
  class_name self-references so it loads in no-project (script-only) mode.
- `godot-android/tests/script_only_target_registry_probe.gd` — script-only
  runtime probe (32 checks: register/unregister/resolve bookkeeping incl.
  empty-id / null-adapter / unknown-id / overwrite, direct-Node3D vs
  NodePath vs String adapter modes, path re-resolution after moves,
  is_available/get_global_transform on live, freed, missing, and
  non-Node3D targets, freed lookup root). Note: checks run from the first
  `_process` iteration, not `_initialize` — `get_global_transform` errors
  with `!is_inside_tree()` before the main loop starts.
- `tools/run_godot_target_registry_probe.ps1` — headless no-project runner
  for the probe, following run_godot_status_hud_probe.ps1.
- `tests/test_godot_target_registry.py` — 3 static tests pinning the
  registry contract, the card-side delegation, and the probe/runner pair.

### Files modified

- `godot-android/scripts/AndroidMovingCard.gd` — removed the
  `class Node3DTargetAdapter` / `class TargetRegistry` inner classes
  (~56 lines). Added `const TargetRegistryScript := preload(...)`;
  `_target_registry` is now `= TargetRegistryScript.new()` (untyped `=`, no
  class_name reference, same pattern as `_options`);
  `register_node3d_target` builds adapters via
  `TargetRegistryScript.Node3DTargetAdapter.new(self, node_or_path)` with an
  explicit `bool()` on the return; the two `resolve()` call sites use `=`
  instead of `:=` (Variant-returning receiver). Public API and behavior
  unchanged; TrackableTarget / VSTTargetAdapter stay in the card (M4
  territory).
- `tests/test_godot_android_mesh_card.py` — registry/adapter pins in
  `test_card_can_attach_to_registered_node3d_targets` repointed at
  `target_registry.gd` (per ADR-3); attach/fallback pins stay on the card.
- `tests/validate_project.ps1` — registers `tests/test_godot_target_registry.py`.
- `TASKS.md` / `HANDOFF.md` — bookkeeping.

### Verification run

- `python -m unittest tests/test_*.py` → 125 tests, OK.
- Schema gate on both fixtures → ok.
- `tools\run_godot_target_registry_probe.ps1` → PASS (32/32 checks, clean
  stderr).
- `tools\run_godot_status_hud_probe.ps1` → PASS (29/29 checks).
- `tools\run_godot_smartxr_options_probe.ps1` → PASS (10/10 checks).
- `tools\run_godot_script_only_websocket_probe.ps1` → ws_connected=true,
  packets=1.
- `tools\run_godot_proxy_targets_consumer_only.ps1` against a live
  `fake_proxy_targets_publisher.py` on :8766 → exit 0, parsed=1, live=1,
  registered_targets=1.
- Compile gate: `AndroidMovingCard.gd` (with all five preloads) and
  `target_registry.gd` load + `can_instantiate()` in script-only mode
  (Godot 4.6.2 headless). Gotcha: run the loader from a directory WITHOUT
  `project.godot` (scripts staged into `.tmp\card_compile_gate\scripts\`) —
  cwd = `godot-android/` makes headless Godot load the project and hang on
  the GXR/OpenXR boot.

## M3 step 1 — StatusHud extraction (YAN-74)

### Files added

- `godot-android/scripts/status_hud.gd` — StatusHud node: builds the
  `MeshCardStatus` Label3D, renders the status text, and writes
  `user://proxy_targets_live_status.json` and
  `user://passthrough_overlay_status.json` from a snapshot Dictionary.
  Owns the 0.25 s write throttle and all `_format_*` helpers
  (`_format_vec3`, `_format_vec3_or_na`, XR/VST/ProxyWS lines,
  `_source_coordinate_summary`, static `sanitize_status_text`). File paths
  are overridable vars so probes can redirect writes. No class_name
  self-references (no-project-mode rule).
- `godot-android/tests/script_only_status_hud_probe.gd` — script-only
  runtime probe (29 checks: label build/parenting, snapshot rendering,
  throttled writes, JSON keys/format parity, sanitize behavior).
- `tools/run_godot_status_hud_probe.ps1` — headless no-project runner for
  the probe, following run_godot_smartxr_options_probe.ps1.
- `tests/test_godot_status_hud.py` — 3 static tests pinning the StatusHud
  contract, the card-side snapshot seam, and the probe/runner pair.

### Files modified

- `godot-android/scripts/AndroidMovingCard.gd` — removed the label/file
  rendering code (~210 lines): `_build_status_label`, `_update_status_label`,
  `_format_vec3`, `_format_xr_status_line`, `_format_proxy_targets_status_line`,
  `_format_vst_status_line`, `_proxy_targets_source_coordinate_summary`,
  `_sanitize_proxy_targets_status_text`, both `_write_*_status_file` writers,
  both write-elapsed vars, `_status_label`, and the two `user://` status
  consts. Added `_status_hud` child node (created in `_build_status_hud()`),
  `_update_status_hud(delta)` in `_process`, and the snapshot builders
  (`_build_status_snapshot` + xr/vst/proxy_targets/passthrough_overlay
  sub-builders). `_proxy_targets_card_resolved_position`,
  `_proxy_targets_card_node_position`, `_passthrough_overlay_layer_position`
  now return Vector3-or-null (StatusHud formats null as "n/a"). Packet
  preview sanitizing now calls `StatusHudScript.sanitize_status_text`.
  No behavior change; the scene tree gains one runtime child (`StatusHud`).
- `tests/test_godot_android_mesh_card.py` — pinned display/format/file-writer
  assertions repointed at `status_hud.gd` (per ADR-3); snapshot-assembly
  assertions stay on the card.
- `tests/test_vst_ncnn_port.py` — XR/VST status-line pins repointed at
  `status_hud.gd`; card pins now target the snapshot builders.
- `tests/validate_project.ps1` — registers `tests/test_godot_status_hud.py`.
- `TASKS.md` / `DECISIONS.md` (ADR-4) / `HANDOFF.md` — bookkeeping.

### Verification run

- `python -m unittest tests/test_*.py` → 122 tests, OK.
- `tools\run_godot_status_hud_probe.ps1` → PASS (29/29 checks).
- `tools\run_godot_smartxr_options_probe.ps1` → PASS (10/10 checks).
- `tools\run_godot_script_only_websocket_probe.ps1` → ws_connected=true,
  packets=1.
- `tools\run_godot_proxy_targets_consumer_only.ps1` against a live
  `fake_proxy_targets_publisher.py` on :8766 → parsed=1, live=1,
  registered_targets=1.
- One-off compile check: `AndroidMovingCard.gd` + `status_hud.gd` load and
  `can_instantiate()` in script-only mode (Godot 4.6.2 headless). Note:
  `godot --check-only` hangs in this repo (GXR extension + OpenXR boot), so
  the loader-probe approach is the usable compile gate.

# M1+M2 change log (YAN-73)

## Files added

- `smartxr/__init__.py`, `smartxr/schema.py`, `smartxr/transport.py`,
  `smartxr/geometry.py`, `smartxr/frames.py`, `smartxr/publisher.py`,
  `smartxr/cli/{__init__,fake_publisher,vst_publisher,validate_payload}.py`,
  `smartxr/README.md` — the shared Python package (M2).
- `pyproject.toml` — minimal packaging metadata.
- `godot-android/scripts/smartxr_options.gd` — runtime options class (M1).
- `docs/smartxr_options.md` — options documentation.
- `tests/test_godot_smartxr_options.py` — 4 new tests.
- `TASKS.md`, `DECISIONS.md`, `HANDOFF.md`, `Notes.md` — project bookkeeping.

## Files modified

- `tools/fake_proxy_targets_publisher.py` — now a wrapper re-exporting from
  `smartxr` (same public names, same CLI).
- `tools/vst_proxy_targets_publisher.py` — same.
- `tools/validate_proxy_targets_payload_schema.py` — same.
- `tools/capture_vst_target_sample_session.py` — `normalize_frame` and its
  helpers moved to `smartxr/frames.py`; capture/session logic unchanged.
- `tools/antman_vst_proxy_targets_live_publisher.py` — imports switched from
  sibling-tool private functions to `smartxr.transport` /
  `smartxr.publisher` / `smartxr.frames`; serve loop unchanged.
- `windows_server/ws_control.py` — `make_websocket_accept_key` and
  `encode_server_text_frame` now come from `smartxr.transport`; local copies
  removed.
- `godot-android/scripts/AndroidMovingCard.gd` — added `_options`
  (SmartXROptions); `_connect_ws()` uses `_control_ws_url()`;
  `_proxy_targets_ws_url()` and the WS-enable gates route through options.
- `tests/validate_project.ps1` — registers the new options test file.
- `tests/test_fake_proxy_targets_publisher.py` — banner assertion repointed
  to `smartxr/cli/fake_publisher.py`.
- `tests/test_godot_android_mesh_card.py` — publisher-source and URL
  assertions repointed to the package / options delegation.

## Runtime verification addendum (same branch, follow-up commit)

- Added `godot-android/tests/script_only_smartxr_options_probe.gd` +
  `tools/run_godot_smartxr_options_probe.ps1`: headless no-project runtime
  probe for SmartXROptions (10 checks: default / config / env priority /
  bool parsing). PASSES on Godot 4.6.2.
- Fixed a real bug the probe caught: `smartxr_options.gd` self-referenced its
  `class_name` (typed static constructors + `SmartXROptions.new()`), which
  fails to compile in no-project (script-only) mode. Constructors are now
  untyped with bare `new()`; `AndroidMovingCard.gd` `_options` uses `=`
  instead of `:=` accordingly.
- `load_options_from(path)` added so the probe (and future tests) can point
  the config at a temp file instead of `user://`.
- Existing harnesses re-run against the refactored M2 publisher:
  `run_godot_script_only_websocket_probe.ps1` -> `ws_connected=true, packets=1`;
  `run_godot_proxy_targets_consumer_only.ps1` + live fake publisher ->
  `parsed=1, registered_targets=1`.
- `docs/smartxr_options.md` gained a "Runtime verification" section;
  `tests/test_godot_smartxr_options.py` pins the probe/runner contract
  (now 5 test methods).

## Verification run

- `python -m unittest tests/test_*.py` → 118 tests, OK.
- Schema gate on both fixtures → ok.
- `vst_proxy_targets_publisher.py --print-once` against the VST fixture →
  canonical message printed.
