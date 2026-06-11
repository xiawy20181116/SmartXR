# HANDOFF

## State (after M3 step 1, YAN-74)

- All 122 Python tests pass (`python -m unittest tests/test_*.py`).
- Schema gate passes on both fixtures.
- **M3 step 1 done**: status HUD + diagnostics-file subsystem extracted from
  `AndroidMovingCard.gd` into `godot-android/scripts/status_hud.gd`. The card
  assembles a per-frame snapshot Dictionary (`_build_status_snapshot()`);
  StatusHud renders the label and writes the two `user://` status files with
  the identical JSON shape and 0.25 s throttle. See ADR-4 in DECISIONS.md.
- **Godot runtime verification done on the dev machine** (Godot 4.6.2
  headless): the new StatusHud probe passes all 29 checks
  (`tools\run_godot_status_hud_probe.ps1`), the options probe passes all 10
  checks, and both pipeline harnesses pass —
  `run_godot_script_only_websocket_probe.ps1` (`ws_connected=true,
  packets=1`) and `run_godot_proxy_targets_consumer_only.ps1` against a live
  `fake_proxy_targets_publisher.py` (`parsed=1, live=1,
  registered_targets=1`). `AndroidMovingCard.gd` + `status_hud.gd` also pass
  a script-only load/can_instantiate compile check.
- **Still not verified**: `AndroidMovingCard.gd` as a whole app — headless
  project mode boots the main scene which never exits, so that path needs
  the editor or a device. `godot --check-only` also hangs in this repo (GXR
  extension + OpenXR boot); use the script-only loader-probe pattern instead.

## Unfinished / risks

- M3 steps 2+ not started: WSTransport, TargetRegistry, CardAttachment,
  XRBootstrap extractions. Reuse the ADR-4 seam (resolve state in the card,
  format/act in the subsystem node) and keep each script loadable in
  no-project mode (no class_name self-references).
- `WS_URL` still defaults to the historical LAN IP `ws://10.1.98.195:8766/control`
  (kept deliberately for behavior parity). Override via `SMARTXR_CONTROL_WS_URL`
  or `user://smartxr_options.json`; consider changing the default to
  `127.0.0.1` in a follow-up.
- `resolve_bool` returning a Variant from `_config` may emit an UNSAFE_CAST
  style warning in strict Godot editors; harmless, but can be silenced with an
  explicit `bool()` cast if the project enables treat-warnings-as-errors.
- Scripts that script-only probes load must not self-reference their own
  `class_name` (it is unregistered in no-project mode). `smartxr_options.gd`
  and `status_hud.gd` follow the rule; keep it for future probe-visible
  scripts. The card's untyped helpers
  (`_proxy_targets_card_resolved_position()` etc.) intentionally return
  Vector3-or-null; StatusHud renders null as "n/a".
- M4 (TargetSource interface), M5 (docs) not started — see TASKS.md.
- GDScript bbox math in `AndroidMovingCard.gd` still duplicates
  `smartxr/geometry.py`; shared test vectors are planned for M4.

## How to continue

Continue M3 with the next lowest-risk slice (TargetRegistry +
Node3DTargetAdapter are self-contained inner classes today, or WSTransport
for the two WebSocketPeer poll/retry loops), updating the pinned assertions
in `tests/test_godot_android_mesh_card.py` in the same commit, with a
script-only probe per extracted node.
