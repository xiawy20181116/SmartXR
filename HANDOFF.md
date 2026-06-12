# HANDOFF

## State (after M3 step 4, YAN-77)

- All 131 Python tests pass (`python -m unittest tests/test_*.py`).
- Schema gate passes on both fixtures.
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
- **Godot runtime verification done on the dev machine** (Godot 4.6.2
  headless): the new CardAttachment probe passes all 48 checks
  (`tools\run_godot_card_attachment_probe.ps1`), the WSTransport probe all
  30, the target-registry probe all 32, the StatusHud probe all 29, the
  options probe all 10, and both pipeline harnesses pass —
  `run_godot_script_only_websocket_probe.ps1` (`ws_connected=true,
  packets=1`) and `run_godot_proxy_targets_consumer_only.ps1` against a
  live `fake_proxy_targets_publisher.py` (`parsed=1, live=1,
  registered_targets=1, attachments=1`). `AndroidMovingCard.gd` (all seven
  preloads) + `card_attachment.gd` pass the script-only
  load/can_instantiate compile check with clean stderr (staged into
  `.tmp\card_compile_gate\scripts\`).
- **Still not verified**: `AndroidMovingCard.gd` as a whole app — headless
  project mode boots the main scene which never exits, so that path needs
  the editor or a device. `godot --check-only` also hangs in this repo (GXR
  extension + OpenXR boot); use the script-only loader-probe pattern instead.

## Unfinished / risks

- M3 step 5 not started: XRBootstrap (`_try_init_xr` + camera/origin setup)
  is the last card subsystem slated for extraction. Reuse the ADR-4 seam
  (resolve state in the card, format/act in the subsystem) and keep the
  script loadable in no-project mode (no class_name self-references).
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
- `WS_URL` still defaults to the historical LAN IP `ws://10.1.98.195:8766/control`
  (kept deliberately for behavior parity). Override via `SMARTXR_CONTROL_WS_URL`
  or `user://smartxr_options.json`; consider changing the default to
  `127.0.0.1` in a follow-up.
- `resolve_bool` returning a Variant from `_config` may emit an UNSAFE_CAST
  style warning in strict Godot editors; harmless, but can be silenced with an
  explicit `bool()` cast if the project enables treat-warnings-as-errors.
- Scripts that script-only probes load must not self-reference their own
  `class_name` (it is unregistered in no-project mode). `smartxr_options.gd`,
  `status_hud.gd`, `target_registry.gd`, `ws_transport.gd` and
  `card_attachment.gd` follow the rule; keep it for future probe-visible
  scripts. Inner-class references (`Node3DTargetAdapter` inside
  `target_registry.gd`) are script-scoped and safe. The card's untyped
  helpers (`_proxy_targets_card_resolved_position()` etc.) intentionally
  return Vector3-or-null; StatusHud renders null as "n/a".
- M4 (TargetSource interface), M5 (docs) not started — see TASKS.md.
- GDScript bbox math in `AndroidMovingCard.gd` still duplicates
  `smartxr/geometry.py`; shared test vectors are planned for M4.

## How to continue

Continue M3 with the last slice: XRBootstrap (`_try_init_xr` + the
camera/origin setup in `_setup_camera`, plus the blend-mode request that
feeds the passthrough_overlay snapshot) as M3 step 5. Update the pinned
assertions in `tests/test_godot_android_mesh_card.py` in the same commit,
add a script-only probe per extracted script, and register the new static
test in `tests/validate_project.ps1`. After that, M4 (TargetSource strategy
interface: TrackableTarget / VSTTargetAdapter and target-source
unification) and M5 (per-subsystem docs).
