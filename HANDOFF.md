# HANDOFF

## State (after M3 step 2, YAN-75)

- All 125 Python tests pass (`python -m unittest tests/test_*.py`).
- Schema gate passes on both fixtures.
- **M3 step 1 done** (YAN-74): status HUD + diagnostics-file subsystem
  extracted into `godot-android/scripts/status_hud.gd` via the
  snapshot-Dictionary seam (ADR-4 in DECISIONS.md).
- **M3 step 2 done** (YAN-75): the TargetRegistry + Node3DTargetAdapter
  inner classes extracted from `AndroidMovingCard.gd` into
  `godot-android/scripts/target_registry.gd` (RefCounted, dependency-free,
  no class_name self-references). The card preloads it as
  `TargetRegistryScript` and keeps the same public API
  (`register_node3d_target` / `unregister_target` / `attach_to_target`);
  adapters are built with the card as lookup root
  (`TargetRegistryScript.Node3DTargetAdapter.new(self, node_or_path)`).
  TrackableTarget and VSTTargetAdapter stay in the card — they belong to
  the target-source subsystem (M4), not the registry.
- **Godot runtime verification done on the dev machine** (Godot 4.6.2
  headless): the new target-registry probe passes all 32 checks
  (`tools\run_godot_target_registry_probe.ps1`), the StatusHud probe passes
  all 29 checks, the options probe passes all 10 checks, and both pipeline
  harnesses pass — `run_godot_script_only_websocket_probe.ps1`
  (`ws_connected=true, packets=1`) and
  `run_godot_proxy_targets_consumer_only.ps1` against a live
  `fake_proxy_targets_publisher.py` (`parsed=1, live=1,
  registered_targets=1`). `AndroidMovingCard.gd` + `target_registry.gd`
  pass a script-only load/can_instantiate compile check.
- **Still not verified**: `AndroidMovingCard.gd` as a whole app — headless
  project mode boots the main scene which never exits, so that path needs
  the editor or a device. `godot --check-only` also hangs in this repo (GXR
  extension + OpenXR boot); use the script-only loader-probe pattern instead.

## Unfinished / risks

- M3 steps 3+ not started: WSTransport, CardAttachment, XRBootstrap
  extractions. Reuse the ADR-4 seam (resolve state in the card, format/act
  in the subsystem) and keep each script loadable in no-project mode (no
  class_name self-references).
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
  `script_only_target_registry_probe.gd`).
- `WS_URL` still defaults to the historical LAN IP `ws://10.1.98.195:8766/control`
  (kept deliberately for behavior parity). Override via `SMARTXR_CONTROL_WS_URL`
  or `user://smartxr_options.json`; consider changing the default to
  `127.0.0.1` in a follow-up.
- `resolve_bool` returning a Variant from `_config` may emit an UNSAFE_CAST
  style warning in strict Godot editors; harmless, but can be silenced with an
  explicit `bool()` cast if the project enables treat-warnings-as-errors.
- Scripts that script-only probes load must not self-reference their own
  `class_name` (it is unregistered in no-project mode). `smartxr_options.gd`,
  `status_hud.gd` and `target_registry.gd` follow the rule; keep it for
  future probe-visible scripts. Inner-class references
  (`Node3DTargetAdapter` inside `target_registry.gd`) are script-scoped and
  safe. The card's untyped helpers
  (`_proxy_targets_card_resolved_position()` etc.) intentionally return
  Vector3-or-null; StatusHud renders null as "n/a".
- M4 (TargetSource interface), M5 (docs) not started — see TASKS.md.
- GDScript bbox math in `AndroidMovingCard.gd` still duplicates
  `smartxr/geometry.py`; shared test vectors are planned for M4.

## How to continue

Continue M3 with the next slice: WSTransport (the two WebSocketPeer
poll/retry loops, control + proxy_targets) is the natural next candidate, or
CardAttachment (the attach/fallback state machine around
`_card_attachments`). Update the pinned assertions in
`tests/test_godot_android_mesh_card.py` in the same commit, add a
script-only probe per extracted script, and register the new static test in
`tests/validate_project.ps1`.
