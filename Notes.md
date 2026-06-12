# Notes — change log

## M3 step 4 — CardAttachment extraction (YAN-78)

### Files added

- `godot-android/scripts/card_attachment.gd` — the card attachment subsystem
  (RefCounted, dependency-free, no class_name self-references): owns the
  card_id -> attachment bookkeeping (`_attachments`, formerly the card's
  `_card_attachments`), `attach` / `detach` / `update_attachments` /
  `apply_fallback`, the offset-rule math moved byte-for-byte
  (`_normalize_target_offset_rule`, `_target_offset_transform`,
  `_target_world_offset_transform`, `_target_local_offset_transform`,
  `_target_offset_vector`), the `TARGET_FALLBACK_*` /
  `TARGET_DEFAULT_OFFSET_RULE` constants, and the apply counter. Wiring
  follows the WSTransport Callable pattern: `set_primary_card_id`
  (CardAnchor), `set_resolve_target` (registry lookups — the registry stays
  card-owned, ADR-4), `set_card_anchor_provider` (Node3D-or-null, matching
  the old `if _card_anchor == null` guard), `set_on_attachments_updated`
  (the old function tail: `_face_camera_enabled` orientation + VST bbox
  frame refresh, card-side), and `set_on_all_detached` (the old
  detach-to-manual transition: the card checks `_anchor_mode == "target"`
  and applies the 3DoF transform). Snapshot-feeding getters
  (`attachment_count`, `card_target_id`, `card_resolved_position`,
  `apply_count`, plus `has_attachment` / `get_attachment` for the VST
  paths) keep the status snapshot values identical.
- `godot-android/tests/script_only_card_attachment_probe.gd` — script-only
  runtime probe (64 checks: constant parity; rule normalization incl.
  string-vs-dictionary input, unsupported types, default-rule merge and
  non-mutation; every offset mode — right_top/top_right alias, right, top,
  front, custom x_m/y_m/z_m with the -distance z default; world vs target
  offset spaces against a rotated target transform; attach/detach
  bookkeeping incl. unknown-target rejection and the all-detached hook;
  all three fallbacks (hold_last_pose restore, fade_out hide, detach +
  mode transition) against registered-then-freed and unregistered targets;
  last_transform tracking; primary-key-first vs only-entry attachment
  lookup and the ambiguous two-entry early return; snapshot getters; an
  unwired instance stays inert). Probe-side stand-ins inject the resolve /
  anchor / hook Callables, mirroring the card wiring.
- `tools/run_godot_card_attachment_probe.ps1` — headless no-project runner,
  following run_godot_target_registry_probe.ps1 (env-injected script path +
  status JSON).
- `tests/test_godot_card_attachment.py` — 3 static tests pinning the
  subsystem contract, the card-side delegation/wiring, and the probe/runner
  pair.

### Files modified

- `godot-android/scripts/AndroidMovingCard.gd` — removed the attach/fallback
  state machine, the offset math (~110 lines), `var _card_attachments`,
  `var _proxy_targets_card_apply_count`, and the `TARGET_FALLBACK_*` /
  `TARGET_DEFAULT_OFFSET_RULE` consts (`VST_TARGET_OFFSET_RULE` now
  references `CardAttachmentScript.TARGET_FALLBACK_HOLD_LAST_POSE`). Added
  `const CardAttachmentScript := preload(...)` (seventh preload);
  `_card_attachment = CardAttachmentScript.new()` (untyped `=`, same
  pattern as `_options`); `_setup_card_attachment()` (called from `_ready`
  right after `_build_card_anchor()`) wires the five Callables.
  `attach_to_target` keeps its exact signature and the
  `_anchor_mode = "target"` / `_last_command = "attach_target:<id>"`
  transitions around the subsystem calls; `detach_card` delegates; the VST
  paths (`_advance_vst_target_state`, `_apply_vst_target_fallback`) read
  the CardAnchor attachment through `has_attachment` / `get_attachment` and
  call `apply_fallback` directly, byte-for-byte equivalent to before. The
  status snapshot reads `attachments` / `card_apply_count` from the
  subsystem getters (same keys, same values).
- `tests/test_godot_android_mesh_card.py` — attach/offset/fallback pins in
  `test_card_can_attach_to_registered_node3d_targets`,
  `test_world_target_offset_ignores_target_rotation_for_card_position`, and
  the apply-count/attachments pins in
  `test_proxy_targets_live_websocket_consumer_is_wired` repointed at
  `card_attachment.gd` (per ADR-3); public-API, `_anchor_mode`, and
  snapshot-assembly pins stay on the card.
- `tests/validate_project.ps1` — registers `tests/test_godot_card_attachment.py`.
- `TASKS.md` / `HANDOFF.md` — bookkeeping.

### Verification run

- `python -m unittest tests/test_*.py` → 131 tests, OK.
- Schema gate on both fixtures → ok.
- `tools\run_godot_card_attachment_probe.ps1` → PASS (64/64 checks, clean
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
  (Godot 4.6.2 headless, staged into `.tmp\card_compile_gate\scripts\`
  without `project.godot`, clean stderr).

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
